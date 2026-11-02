"""Results card: Revenue, EBITDA, PBT, PAT with QoQ and YoY, read from the
company's own results filing.

Split of work:
- code picks the 1-2 PDF pages that hold the P&L (no model needed),
- a cheap model copies the line items for every quarter column, with dates,
- code works out which column is QoQ / YoY, computes EBITDA, and checks the
  arithmetic (PBT - tax = PAT). If a check fails, the stronger model gets
  one try; if that also fails the card is marked "check the filing".
"""
import io
import re
import time
from datetime import date

import requests
from pypdf import PdfReader, PdfWriter

from finn import announcements, llm
from finn.announcements import HEADERS
from finn.classify import classify
from finn.storage import data_path, read_json, write_json

# "(₹ in million)", "(Rs. in Lakhs)", "(INR crore)": the statement says its own unit.
UNIT_RE = re.compile(r"(?:₹|rs\.?|inr|rupees)\s*(?:in\s*)?(crores?|lakhs?|lacs?|million|thousands?)"
                     r"|(?:crores?|lakhs?|million)\s*(?:of\s*)?(?:₹|rs\.?|inr|rupees)"
                     r"|\(\s*\S{0,3}\s*in\s+(crores?|lakhs?|million)\b", re.I)  # OCR'd "(' in Crores)"

# NSE's own wording when the attachment is the results themselves.
RESULTS_TEXT = re.compile(r"financial results|results for the (quarter|period)", re.I)
NOT_RESULTS = re.compile(r"^(transcript|audio|video|recording)|newspaper|intimation|scheduled", re.I)
TO_CRORE = {"crore": 1, "lakh": 0.01, "million": 0.1, "thousand": 1e-4, "rupees": 1e-7}

NUM = {"type": "NUMBER", "nullable": True}
SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "basis": {"type": "STRING", "enum": ["consolidated", "standalone"]},
        "unit": {"type": "STRING", "enum": list(TO_CRORE)},
        "lender": {"type": "BOOLEAN", "description": "true for a bank, NBFC or insurer (interest-income format)"},
        "periods": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "end_date": {"type": "STRING", "description": "period end, YYYY-MM-DD"},
            "months": {"type": "INTEGER", "description": "3 for a quarter, 6 half-year, 12 year"},
            "revenue": {**NUM, "description": "Revenue from operations. Lenders: Total income"},
            "other_income": NUM,
            "total_expenses": NUM,
            "finance_costs": NUM,
            "depreciation": NUM,
            "pbt_before_exceptional": {**NUM, "description": "Profit before exceptional items and tax"},
            "pbt": {**NUM, "description": "Profit before tax, after exceptional items"},
            "tax": {**NUM, "description": "Total tax expense"},
            "pat": {**NUM, "description": "Profit for the period, before minority split"},
            "pre_provision_profit": {**NUM, "description": "Lenders only: operating profit before provisions"},
            "impairment": {**NUM, "description": "Lenders only: provisions / impairment on financial instruments"},
            "associates_after_tax": {**NUM, "description": "Share of associates/JVs, only if added AFTER tax"},
        }, "required": ["end_date", "months", "revenue", "pbt", "pat"]}},
    },
    "required": ["basis", "unit", "lender", "periods"],
}

PROMPT = """You read Indian listed-company results filings.
Below is the text of the page(s) holding the {basis_hint} statement of profit and loss.
Return every column that covers a single quarter (3 months), with its period-end date.
Copy numbers exactly as printed, in the unit the statement uses. Numbers in
brackets are negative. The text comes from OCR: if a digit is garbled (for
example "51B6.55"), correct it only when the statement's own arithmetic makes
the right value certain. Use null for a line that is not in the statement.
Do not use anything except this text.

---
{text}"""


def results_filings(symbol: str) -> list:
    """Cached announcements that carry the results PDF, newest first."""
    out = []
    for a in announcements.load_announcements(symbol):
        if not a.get("url", "").lower().endswith(".pdf") or not a.get("time"):
            continue
        body = f"{a['subject']} {a['text']}"
        if (classify(a["subject"], a["text"])["category"] == "results"
                and RESULTS_TEXT.search(body) and not NOT_RESULTS.search(a["text"].strip())):
            out.append(a)
    return sorted(out, key=lambda a: a["time"], reverse=True)


def download(a: dict) -> bytes:
    path = data_path("filings", f"{a['id']}.pdf")
    if not path.exists():
        resp = requests.get(a["url"], headers={**HEADERS, "Accept": "application/pdf,*/*"}, timeout=90)
        resp.raise_for_status()
        path.write_bytes(resp.content)
    return path.read_bytes()


def _score(text: str) -> int:
    t = text.lower()
    s = 0
    s += 3 * any(k in t for k in ("revenue from operations", "interest earned", "total income"))
    s += 3 * ("before tax" in t)
    s += 2 * ("quarter ended" in t or "months ended" in t or "3 months" in t or "three months" in t)
    s += 1 * ("profit for the period" in t or "net profit" in t)
    # The full statement lists the expense lines; the short "extract"
    # published for newspapers doesn't, and has no last-quarter column.
    s += sum(2 for k in ("finance cost", "depreciation", "total expenses", "tax expense") if k in t)
    s -= 3 * ("segment" in t[:400])
    s -= 8 * ("extract of" in t[:600])
    return s


def statement_pages(pdf: bytes) -> tuple:
    """(text of the P&L page plus the next page, basis). Prefers consolidated."""
    pages = [(p.extract_text() or "") for p in PdfReader(io.BytesIO(pdf)).pages]
    best = None
    for basis in ("consolidated", "standalone"):
        ranked = sorted(((_score(t), i) for i, t in enumerate(pages) if basis in t.lower()), reverse=True)
        if ranked and ranked[0][0] >= 7:
            best = (ranked[0][1], basis)
            break
    if best is None:
        return "", "consolidated"
    i, basis = best
    text = pages[i] + ("\n" + pages[i + 1][:2500] if i + 1 < len(pages) else "")
    return text[:9000], basis


def detect_unit(text: str):
    """The unit printed on the statement, or None. Code reads it, because a
    model guessing "crore" for a "₹ million" statement is off by 10x and no
    arithmetic check can catch that."""
    m = UNIT_RE.search(text)
    if not m:
        return None
    word = (m.group(1) or m.group(2) or m.group(0)).lower()
    return next(u for u, k in (("crore", "crore"), ("lakh", "lak"), ("lakh", "lac"), ("million", "million"),
                               ("thousand", "thousand")) if k in word)


def _first_pages(pdf: bytes, n: int = 8) -> bytes:
    reader, writer = PdfReader(io.BytesIO(pdf)), PdfWriter()
    for page in reader.pages[:n]:
        writer.add_page(page)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _months_between(a: str, b: str) -> int:
    x, y = date.fromisoformat(a), date.fromisoformat(b)
    return (x.year - y.year) * 12 + x.month - y.month


def _metrics(p: dict, scale: float, lender: bool) -> dict:
    g = lambda k: None if p.get(k) is None else p[k] * scale
    rev, pbt, pat = g("revenue"), g("pbt"), g("pat")
    ebitda = None
    if lender:
        # Ind AS lenders (most NBFCs) print no pre-provision line: add back
        # the impairment charge instead.
        ebitda = g("pre_provision_profit")
        if ebitda is None and None not in (pbt, g("impairment")):
            ebitda = pbt + g("impairment")
    elif None not in (rev, g("total_expenses"), g("finance_costs"), g("depreciation")):
        # Operating EBITDA: revenue minus operating costs. Other income,
        # associates and exceptional items are left out on purpose.
        ebitda = rev - (g("total_expenses") - g("finance_costs") - g("depreciation"))
    return {"revenue": rev, "ebitda": ebitda, "pbt": pbt, "pat": pat}


def _change(cur, prev):
    if cur is None or prev is None or prev == 0:
        return None
    return round((cur - prev) / abs(prev) * 100, 1)


def build_card(ext: dict, unit: str = None) -> dict:
    """Pure function: extracted columns -> card. `unit` is the one printed
    on the statement and wins over the model's. Raises ValueError if the
    filing has no current quarter."""
    scale = TO_CRORE.get(unit or ext.get("unit"), 1)
    quarters = sorted((p for p in ext.get("periods", []) if p.get("months") == 3 and p.get("end_date")),
                      key=lambda p: p["end_date"], reverse=True)
    if not quarters:
        raise ValueError("no quarterly column found")
    cur = quarters[0]
    find = lambda gap: next((p for p in quarters[1:] if _months_between(cur["end_date"], p["end_date"]) == gap), None)
    prev_q, prev_y = find(3), find(12)

    issues = [f"no {label} column" for label, p in (("last-quarter", prev_q), ("last-year", prev_y)) if not p]
    for label, p in (("this quarter", cur), ("last quarter", prev_q), ("last year", prev_y)):
        if p and None not in (p.get("pbt"), p.get("tax"), p.get("pat")):
            expected = p["pbt"] - p["tax"] + (p.get("associates_after_tax") or 0)
            # 0.1%: enough for rounding, not for a misread digit (5156 vs 5186).
            if abs(expected - p["pat"]) > max(1.0, 0.001 * abs(p["pat"])):
                issues.append(f"PBT − tax ≠ PAT for {label}")
    lender = bool(ext.get("lender"))
    m = {k: _metrics(p, scale, lender) if p else None for k, p in (("cur", cur), ("qoq", prev_q), ("yoy", prev_y))}
    rows = []
    for key in ("revenue", "ebitda", "pbt", "pat"):
        v = m["cur"][key]
        rows.append({
            "metric": key, "value": None if v is None else round(v, 1),
            "qoq": _change(v, m["qoq"] and m["qoq"][key]), "yoy": _change(v, m["yoy"] and m["yoy"][key]),
        })
    rev = m["cur"]["revenue"]
    margin = lambda mm: None if not mm or not mm["revenue"] or mm["ebitda"] is None else round(mm["ebitda"] / mm["revenue"] * 100, 1)
    return {
        "basis": ext.get("basis"), "lender": lender, "quarter_end": cur["end_date"],
        "qoq_end": prev_q and prev_q["end_date"], "yoy_end": prev_y and prev_y["end_date"],
        "rows": rows, "ebitda_margin": margin(m["cur"]), "ebitda_margin_yoy": margin(m["yoy"]),
        "issues": issues, "ok": not issues and prev_q is not None and prev_y is not None
              and all(r["value"] is not None for r in rows if not (lender and r["metric"] == "ebitda")),
    }


def extract(a: dict) -> dict:
    """Card for one results announcement, cached by announcement id."""
    path = data_path("results", f"{a['id']}.json")
    cached = read_json(path)
    if cached:
        return cached
    pdf = download(a)
    text, basis = statement_pages(pdf)
    attempts, ext, card = [], None, None
    for model in (llm.CHEAP, llm.STRONG):
        try:
            if text:
                got, usage = llm.generate_json(PROMPT.format(basis_hint=basis, text=text), SCHEMA, model)
            else:  # scanned PDF with no text layer: send the first pages themselves
                got, usage = llm.generate_json(PROMPT.format(basis_hint="consolidated", text="(see the attached PDF)"),
                                               SCHEMA, model, pdf=_first_pages(pdf))
        except llm.LLMError:
            if ext is None:
                raise
            break  # the escalation failed: keep the first answer, flagged
        ext = got
        attempts.append(usage)
        try:
            card = build_card(ext, detect_unit(text))
        except ValueError as exc:
            card = {"ok": False, "issues": [str(exc)]}
        if card["ok"]:
            break
        time.sleep(2)
    out = {"id": a["id"], "symbol": a["symbol"], "url": a["url"], "time": a["time"],
           "source": "text" if text else "pdf", "usage": attempts, "extracted": ext, "card": card}
    write_json(path, out)
    return out


SCREENER_MONTH = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def cross_check(symbol: str, card: dict) -> dict:
    """Compare revenue and PAT with screener.in's table (in ₹ crore). Catches
    unit slips and wrong columns. Never changes the numbers, only flags."""
    summary = read_json(data_path("fundamentals", symbol, "summary.json"))
    if not summary or not card.get("rows") or not card.get("quarter_end"):
        return card
    q = summary["quarters"]
    y, m = card["quarter_end"][:4], int(card["quarter_end"][5:7])
    label = f"{SCREENER_MONTH[m]} {y}"
    if label not in q["periods"]:
        return card
    i = q["periods"].index(label)
    ours = {r["metric"]: r["value"] for r in card["rows"]}
    theirs = {"revenue": (q["rows"].get("Sales") or q["rows"].get("Revenue") or [None] * (i + 1))[i],
              "pat": (q["rows"].get("Net Profit") or [None] * (i + 1))[i]}
    off = [k for k, v in theirs.items()
           if v and ours.get(k) and abs(ours[k] - v) > 0.03 * abs(v)]
    out = {**card, "screener": {"period": label, **theirs, "match": not off}}
    if off:
        out["ok"] = False
        out["issues"] = card["issues"] + [f"{k} differs from screener.in ({ours[k]:,.0f} vs {theirs[k]:,.0f})" for k in off]
    return out


def load_cards() -> dict:
    """{announcement id: card} for everything extracted so far, cross-checked."""
    folder = data_path("results", "x").parent
    return {r["id"]: cross_check(r["symbol"], r["card"]) for r in (read_json(p) for p in folder.glob("*.json")) if r}


def extract_latest(symbols) -> list:
    """The latest results filing per company. Tries the next filing of the
    same day if the first one isn't the statement (e.g. a cover letter)."""
    done = []
    for sym in symbols:
        filings = results_filings(sym)
        if not filings:
            continue
        day = filings[0]["time"][:10]
        for a in [f for f in filings if f["time"][:10] == day]:
            try:
                r = extract(a)
            except Exception as exc:
                print(f"  {sym:<12} ! {exc}")
                continue
            c = r["card"]
            tokens = sum(u["input_tokens"] + u["output_tokens"] for u in r["usage"])
            models = "+".join(u["model"].replace("gemini-", "") for u in r["usage"])
            print(f"  {sym:<12} {'ok ' if c.get('ok') else 'CHECK'} {c.get('quarter_end', '')} "
                  f"{c.get('basis', '')}  [{models}, {tokens} tok] {'; '.join(c.get('issues', []))}")
            done.append(r)
            if c.get("ok"):
                break
            time.sleep(1)
    return done
