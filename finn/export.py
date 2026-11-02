"""Turn the data/ cache into one JSON file the web app reads.

The app is static: no server is needed for the push side. Thresholds are
applied in the browser, so the user can change what "unusual" means and see
the feed update at once. This module only prepares the numbers.
"""
import re
from datetime import datetime

import pandas as pd

import config
from finn import announcements, prices
from finn.classify import BASE_PRIORITY, PROMOTE_BONUS, TIER_HIGH, classify
from finn.storage import data_path, write_json

SESSIONS = 22   # about one month of trading days per company
SPARK_DAYS = 30

# "ITC Limited has informed the Exchange about Amalgamation/Merger" -> "Amalgamation/Merger"
BOILERPLATE = re.compile(
    r"^.{0,120}?\bhas (informed|submitted to|intimated) the Exchange,?\s*"
    r"(about|regarding|that|of|the)?\s*", re.I)


def clean_headline(subject: str, text: str) -> str:
    """One readable line: the detail text without NSE's boilerplate opening,
    or the subject when the text adds nothing."""
    body = BOILERPLATE.sub("", (text or "").strip()).strip(" .'\"")
    body = re.sub(r"\s+", " ", body)
    if len(body) < 8:
        return subject
    body = body[0].upper() + body[1:]
    return body if len(body) <= 160 else body[:157].rsplit(" ", 1)[0] + "…"


def _as_of() -> datetime:
    """When FINN last checked NSE. Every fetch rewrites the announcement
    files, so their newest modification time is the refresh time. Windows in
    the app count back from here, so the demo never shows an empty feed just
    because it is opened a few days later."""
    files = list(data_path("announcements", "x").parent.glob("*.json"))
    if not files:
        return datetime.now()
    return datetime.fromtimestamp(max(f.stat().st_mtime for f in files)).replace(microsecond=0)


def _company(symbol: str) -> dict:
    df = prices.load_prices(symbol)
    out = {"symbol": symbol, "sector": config.SECTORS.get(symbol, ""), "sessions": [], "spark": []}
    if df.empty:
        return out
    # Fixed 20-day lookback here; the multiple and the % move are the user's.
    sig = prices.compute_signals(df).tail(SESSIONS)
    out["sessions"] = [{
        "date": pd.Timestamp(d).date().isoformat(),
        "close": round(float(r["Close"]), 2),
        "change_pct": round(float(r["change_pct"]), 2) if pd.notna(r["change_pct"]) else None,
        "volume": int(r["Volume"]),
        "volume_ratio": round(float(r["volume_ratio"]), 2) if pd.notna(r["volume_ratio"]) else None,
    } for d, r in sig.iterrows()]
    out["spark"] = [round(float(c), 2) for c in df["Close"].tail(SPARK_DAYS)]
    return out


def _announcement(a: dict) -> dict:
    # Re-classify on export so rule fixes apply without fetching again.
    c = classify(a["subject"], a["text"])
    return {
        "id": a["id"], "symbol": a["symbol"], "company": a["company"], "time": a["time"],
        "subject": a["subject"], "headline": clean_headline(a["subject"], a["text"]),
        "url": a["url"], "category": c["category"], "priority": c["priority"],
        "tier": c["tier"], "matched": c["matched"], "needs_llm": c["needs_llm"],
    }


def build_feed(symbols=None) -> dict:
    symbols = symbols or config.PORTFOLIO
    names, items = {}, []
    for sym in symbols:
        for a in announcements.load_announcements(sym):
            if a.get("time"):
                items.append(_announcement(a))
                names.setdefault(sym, a["company"])
    items.sort(key=lambda a: a["time"], reverse=True)
    companies = [{**_company(s), "name": names.get(s, s)} for s in symbols]
    return {
        "as_of": _as_of().isoformat(),
        "generated_at": datetime.now().replace(microsecond=0).isoformat(),
        "defaults": {**config.ALERTS, "alert_categories": config.ALERT_CATEGORIES},
        "categories": list(BASE_PRIORITY),
        # Only types that can reach the high tier can become alerts; offering
        # a toggle for the others would be a switch that does nothing.
        "alertable": [c for c, p in BASE_PRIORITY.items() if p + PROMOTE_BONUS >= TIER_HIGH],
        "companies": companies,
        "announcements": items,
    }


def write_feed(path) -> dict:
    feed = build_feed()
    write_json(path, feed)
    return feed
