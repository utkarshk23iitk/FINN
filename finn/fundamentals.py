"""Company fundamentals from screener.in: quarterly numbers, concall
transcripts and annual-report links. All primary documents, as the brief
requires for the pull side.

screener.in's page layout can change. The parsers look for content (link
text like "Transcript", row labels like "Net Profit") rather than exact CSS
paths, so small layout changes shouldn't break them.
"""
import re
import time

import requests
from bs4 import BeautifulSoup

import config
from finn.storage import data_path, write_json

SCREENER = "https://www.screener.in"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"),
    "Accept-Language": "en-US,en;q=0.9",
}
# Exchange PDF servers often reject requests without a browser-like Referer.
PDF_HEADERS = {**HEADERS, "Accept": "application/pdf,*/*", "Referer": "https://www.bseindia.com/"}


# --- Fetching -------------------------------------------------------------------

def fetch_company_html(symbol: str, session: requests.Session = None) -> str:
    """Consolidated numbers first (they include subsidiaries); fall back to standalone."""
    s = session or requests.Session()
    for path in (f"/company/{symbol}/consolidated/", f"/company/{symbol}/"):
        resp = s.get(SCREENER + path, headers=HEADERS, timeout=20)
        if resp.status_code == 200 and "quarters" in resp.text:
            html = resp.text
            # Some companies have an empty consolidated table; check it has data.
            if parse_quarters(html)["periods"]:
                return html
        time.sleep(config.REQUEST_PAUSE_SECONDS)
    raise RuntimeError(f"screener.in has no usable page for {symbol}")


# --- Parsing ------------------------------------------------------------------

def _to_number(cell: str):
    cell = cell.replace(",", "").replace("%", "").replace("\xa0", " ").strip()
    try:
        return float(cell)
    except ValueError:
        return None


def _clean_label(label: str) -> str:
    return re.sub(r"\s+", " ", label.replace("\xa0", " ").replace("+", "")).strip()


def parse_quarters(html: str) -> dict:
    """The 'Quarterly Results' table -> {periods: [...], rows: {label: [values]}}.
    Values are in Rs crore (percent rows as plain numbers)."""
    soup = BeautifulSoup(html, "html.parser")
    section = soup.find("section", id="quarters")
    table = section.find("table") if section else None
    if table is None:
        return {"periods": [], "rows": {}}
    periods = [th.get_text(strip=True) for th in table.find("thead").find_all("th")][1:]
    rows = {}
    for tr in table.find("tbody").find_all("tr"):
        cells = tr.find_all("td")
        if len(cells) < 2:
            continue
        label = _clean_label(cells[0].get_text(" ", strip=True))
        if label and not label.lower().startswith("raw pdf"):
            rows[label] = [_to_number(td.get_text(strip=True)) for td in cells[1:]]
    return {"periods": periods, "rows": rows}


def parse_documents(html: str) -> dict:
    """Concall links (by quarter) and annual-report links."""
    soup = BeautifulSoup(html, "html.parser")

    concalls = []
    box = soup.find(lambda t: t.name == "div" and "concalls" in (t.get("class") or []))
    for li in (box.find_all("li") if box else []):
        links = {a.get_text(strip=True): a.get("href") for a in li.find_all("a") if a.get("href")}
        label_div = li.find("div")
        concalls.append({
            "period": label_div.get_text(strip=True) if label_div else "",
            "transcript": links.get("Transcript"),
            "ppt": links.get("PPT"),
            "recording": links.get("REC"),
        })

    annual_reports = []
    box = soup.find(lambda t: t.name == "div" and "annual-reports" in (t.get("class") or []))
    for a in (box.find_all("a") if box else []):
        title = " ".join(a.find_all(string=True, recursive=False)).strip() or a.get_text(" ", strip=True)
        if a.get("href"):
            annual_reports.append({"title": title, "url": a["href"]})

    return {"concalls": concalls, "annual_reports": annual_reports}


# --- Headline numbers for the results card -------------------------------------

# screener.in labels differ for banks/NBFCs ("Revenue", "Financing Profit").
ROW_ALIASES = {
    "Revenue": ["Sales", "Revenue", "Revenue from Operations"],
    "EBITDA": ["Operating Profit", "Financing Profit"],
    "PBT": ["Profit before tax"],
    "PAT": ["Net Profit"],
}


def _pct_change(new, old):
    if new is None or old in (None, 0):
        return None
    return round((new - old) / abs(old) * 100, 1)


def headline_numbers(quarters: dict) -> dict:
    """Latest quarter's Revenue/EBITDA/PBT/PAT with QoQ and YoY change.

    Note: screener's 'Operating Profit' excludes other income, so treat it as
    an EBITDA proxy, and say so in the UI. For the results card the brief
    wants numbers from the results filing itself; use this as a cross-check.
    """
    periods, rows = quarters["periods"], quarters["rows"]
    if not periods:
        return {}
    out = {"period": periods[-1],
           "vs_qoq": periods[-2] if len(periods) >= 2 else None,
           "vs_yoy": periods[-5] if len(periods) >= 5 else None,
           "metrics": {}}
    for metric, aliases in ROW_ALIASES.items():
        values = next((rows[a] for a in aliases if a in rows), None)
        if not values:
            continue
        latest = values[-1]
        prev = values[-2] if len(values) >= 2 else None
        year_ago = values[-5] if len(values) >= 5 else None
        out["metrics"][metric] = {"value": latest, "qoq_pct": _pct_change(latest, prev),
                                  "yoy_pct": _pct_change(latest, year_ago)}
    return out


# --- Transcripts ----------------------------------------------------------------

def _pdf_to_text(pdf_path) -> str:
    from pypdf import PdfReader
    reader = PdfReader(str(pdf_path))
    return "\n\n".join((page.extract_text() or "") for page in reader.pages)


def _slug(period: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", period).strip("-") or "unknown"


def pick_transcripts(concalls: list) -> list:
    """Concalls with a transcript, one per period label, newest first.
    screener.in sometimes lists an older call under a newer label (TCS, Oct
    2026: a Jul 2025 call shown as "Jul 2026"). The first entry per label is
    the real one; a duplicate must not use up one of the n slots."""
    seen, out = set(), []
    for c in concalls:
        if c.get("transcript") and _slug(c["period"]) not in seen:
            seen.add(_slug(c["period"]))
            out.append(c)
    return out


def download_transcripts(symbol: str, concalls: list, n: int = config.TRANSCRIPTS_PER_COMPANY) -> list:
    """Save the latest n transcripts as PDF + extracted text (the text is what
    you'll send to the model; extracting once and caching keeps LLM costs down).
    A failed download moves on to the next quarter, so n are saved if possible."""
    saved = []
    for c in pick_transcripts(concalls):
        if len(saved) >= n:
            break
        slug = _slug(c["period"])
        pdf_path = data_path("fundamentals", symbol, "transcripts", f"{slug}.pdf")
        txt_path = pdf_path.with_suffix(".txt")
        if not txt_path.exists():
            try:
                resp = requests.get(c["transcript"], headers=PDF_HEADERS, timeout=40)
                resp.raise_for_status()
                if not resp.content.startswith(b"%PDF"):
                    raise ValueError("link did not return a PDF (may be a web page)")
                pdf_path.write_bytes(resp.content)
                txt_path.write_text(_pdf_to_text(pdf_path), encoding="utf-8")
            except Exception as exc:
                print(f"    ! transcript {c['period']}: {exc}")
                continue
            time.sleep(config.REQUEST_PAUSE_SECONDS)
        # Paths relative to data/, so the cache works on any machine.
        rel = lambda p: p.relative_to(config.DATA_DIR).as_posix()
        saved.append({"period": c["period"], "pdf": rel(pdf_path), "text": rel(txt_path),
                      "source_url": c["transcript"]})
    return saved


def fetch_fundamentals(symbol: str, transcripts: int = config.TRANSCRIPTS_PER_COMPANY) -> dict:
    session = requests.Session()
    html = fetch_company_html(symbol, session)
    quarters = parse_quarters(html)
    docs = parse_documents(html)
    saved = download_transcripts(symbol, docs["concalls"], transcripts) if transcripts else []
    result = {
        "symbol": symbol,
        "source": "screener.in",
        "quarters": quarters,
        "headline": headline_numbers(quarters),
        "concalls": docs["concalls"],
        "annual_reports": docs["annual_reports"],
        "transcripts_saved": saved,
    }
    write_json(data_path("fundamentals", symbol, "summary.json"), result)
    return result


def fetch_all_fundamentals(symbols, transcripts: int = config.TRANSCRIPTS_PER_COMPANY) -> dict:
    out = {}
    for sym in symbols:
        try:
            r = fetch_fundamentals(sym, transcripts)
            print(f"  {sym:<12} {len(r['quarters']['periods'])} quarters, "
                  f"{len(r['transcripts_saved'])} transcripts, {len(r['annual_reports'])} annual reports")
            out[sym] = r
        except Exception as exc:
            print(f"  {sym:<12} FAILED: {exc}")
        time.sleep(config.REQUEST_PAUSE_SECONDS)
    return out
