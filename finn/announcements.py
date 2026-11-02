"""Corporate announcements from NSE, normalised, classified and cached.

NSE has no official public API. Its website calls JSON endpoints that only
answer browser-like requests carrying cookies from a normal page visit, so
the client below "warms up" a session first. Expect occasional 401/403s:
the client re-warms once and retries. If NSE blocks you persistently, run
from your home connection (not a cloud server) and slow down the requests.
"""
import hashlib
import time
from datetime import date, datetime, timedelta

import requests

import config
from finn.classify import classify
from finn.storage import data_path, read_json, write_json

NSE = "https://www.nseindia.com"
ANNOUNCEMENTS_PAGE = NSE + "/companies-listing/corporate-filings-announcements"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": ANNOUNCEMENTS_PAGE,
}


class NSEClient:
    def __init__(self, timeout: int = 20):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.timeout = timeout
        self._warm = False

    def warm_up(self) -> None:
        # Visiting normal pages first sets the cookies the API checks for.
        for url in (NSE, ANNOUNCEMENTS_PAGE):
            self.session.get(url, timeout=self.timeout,
                             headers={"Accept": "text/html,application/xhtml+xml"})
        self._warm = True

    def get_json(self, path: str, params: dict):
        if not self._warm:
            self.warm_up()
        for attempt in (1, 2):
            resp = self.session.get(NSE + path, params=params, timeout=self.timeout)
            if resp.status_code in (401, 403) and attempt == 1:
                time.sleep(2)
                self.warm_up()
                continue
            resp.raise_for_status()
            return resp.json()


def _parse_time(item: dict):
    # NSE sometimes drops the space in sort_date ("2026-10-1911:30:07"),
    # hence the second format and the fallbacks.
    for key, fmt in (("sort_date", "%Y-%m-%d %H:%M:%S"),
                     ("sort_date", "%Y-%m-%d%H:%M:%S"),
                     ("an_dt", "%d-%b-%Y %H:%M:%S"),
                     ("exchdisstime", "%d-%b-%Y %H:%M:%S"),
                     ("dt", "%d%m%Y%H%M%S")):
        value = item.get(key)
        if value:
            try:
                return datetime.strptime(str(value).strip(), fmt)
            except ValueError:
                continue
    return None


def normalise(item: dict, symbol: str) -> dict:
    """Map NSE's raw fields onto a stable shape the app can rely on."""
    subject = (item.get("desc") or item.get("subject") or "").strip()
    text = (item.get("attchmntText") or item.get("details") or "").strip()
    when = _parse_time(item)
    url = item.get("attchmntFile") or ""
    raw_id = item.get("seq_id") or f"{symbol}|{subject}|{when}|{url}"
    rec = {
        "id": hashlib.sha1(str(raw_id).encode()).hexdigest()[:16],
        "symbol": item.get("symbol") or symbol,
        "company": item.get("sm_name") or symbol,
        "subject": subject,
        "text": text,
        "time": when.isoformat() if when else None,
        "url": url,
        "source": "NSE",
    }
    rec.update(classify(subject, text))
    return rec


def fetch_announcements(client: NSEClient, symbol: str, start: date, end: date) -> list:
    data = client.get_json("/api/corporate-announcements", {
        "index": "equities",
        "symbol": symbol,
        "from_date": start.strftime("%d-%m-%Y"),
        "to_date": end.strftime("%d-%m-%Y"),
    })
    if isinstance(data, dict):  # some responses wrap the list
        data = data.get("data") or data.get("rows") or []
    return [normalise(item, symbol) for item in data or []]


def save_merged(symbol: str, new_items: list) -> list:
    """Merge with what's already cached (dedupe by id), newest first."""
    path = data_path("announcements", f"{symbol}.json")
    existing = {a["id"]: a for a in read_json(path, default=[])}
    for item in new_items:
        existing[item["id"]] = item
    merged = sorted(existing.values(), key=lambda a: a.get("time") or "", reverse=True)
    write_json(path, merged)
    return merged


def load_announcements(symbol: str) -> list:
    return read_json(data_path("announcements", f"{symbol}.json"), default=[])


def fetch_all_announcements(symbols, days: int = config.ANNOUNCEMENT_DAYS) -> dict:
    end = date.today()
    start = end - timedelta(days=days)
    client = NSEClient()
    out = {}
    for sym in symbols:
        try:
            items = fetch_announcements(client, sym, start, end)
            save_merged(sym, items)
            high = sum(1 for a in items if a["tier"] == "high")
            print(f"  {sym:<12} {len(items):>3} announcements ({high} high priority)")
            out[sym] = items
        except Exception as exc:
            print(f"  {sym:<12} FAILED: {exc}")
        time.sleep(config.REQUEST_PAUSE_SECONDS)
    return out


def digest(symbols, since: datetime, until: datetime = None) -> list:
    """The push 'windowed digest': cached announcements in a time window,
    most important first. Reads only from the cache, so it's instant."""
    until = until or datetime.now()
    items = []
    for sym in symbols:
        for a in load_announcements(sym):
            if a.get("time") and since <= datetime.fromisoformat(a["time"]) <= until:
                items.append(a)
    return sorted(items, key=lambda a: (a["priority"], a["time"]), reverse=True)
