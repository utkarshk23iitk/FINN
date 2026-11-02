"""Pull side: "promised vs delivered" over the last four earnings calls.

Grounded only in primary sources: the company's own call transcripts, and
its reported quarterly numbers (screener.in's table of the filed results).
No news, no broker notes, and the prompts forbid outside knowledge.

Pipeline, cheapest step first:
1. code trims each transcript to forward-looking and number-bearing
   sentences, with the speaker's name (about 40% of the text),
2. a cheap model lists, per call, the guidance given and the results
   reported, each with a verbatim quote,
3. code checks every quote against the transcript and drops any that
   are not there (the model may not put words in management's mouth),
4. one call to the strong model compares guidance with what later calls
   and the reported numbers show; its evidence quotes are checked too.
Everything is cached per company, so a second look costs nothing.
"""
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from finn import fundamentals, llm
from finn.storage import data_path, read_json, write_json

LIGATURES = {"ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl", "Ư": "ff"}
SPEAKER = re.compile(r"\n\s*([A-Z][a-z]+(?:\s+[A-Z][a-zA-Z.']+){0,3})\s*:\s")
NOT_NAMES = {"Our", "The", "We", "This", "That", "Our Priority", "Note", "Disclaimer"}
FORWARD = re.compile(
    r"\b(expect|guid|outlook|target|aspir|going forward|next (year|quarter|few)|FY ?2?\d\b|H[12]\b|"
    r"will (be|see|continue|grow|improve|remain)|confident|band|trajectory|pipeline|deal wins?|TCV|"
    r"order book|capex|margin|grow(th)?|demand|ramp)", re.I)
NUMBER = re.compile(r"\d+(\.\d+)?\s?(%|percent|bps|basis points|crore|billion|million|lakh)", re.I)


def clean(text: str) -> str:
    for bad, good in LIGATURES.items():
        text = text.replace(bad, good)
    return re.sub(r"Page \d+ of \d+", "", text)


def trim(text: str) -> str:
    """Keep forward-looking or number-bearing sentences, tagged with who said
    them. The moderator's lines are dropped."""
    text = clean(text)
    out, speaker, pos = [], "", 0
    marks = [m for m in SPEAKER.finditer(text) if m.group(1) not in NOT_NAMES]
    chunks = []
    for m in marks:
        chunks.append((speaker, text[pos:m.start()]))
        speaker, pos = m.group(1), m.end()
    chunks.append((speaker, text[pos:]))
    for name, chunk in chunks:
        if name.lower().startswith("moderator"):
            continue
        for s in re.split(r"(?<=[.?!])\s+", re.sub(r"\s+", " ", chunk)):
            if len(s) > 25 and (FORWARD.search(s) or NUMBER.search(s)):
                out.append(f"{name}: {s}" if name else s)
    return "\n".join(out)


def _squash(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", clean(s).lower())


def quote_found(quote: str, source: str) -> bool:
    """Is the quote really in the transcript? Compared on letters and digits
    only, because PDF text breaks words and lines at random."""
    q = _squash(quote)
    return len(q) >= 12 and q in source


def call_quarter(period: str) -> tuple:
    """screener.in labels a call by its month ("Oct 2026"). The call covers
    the quarter that ended before it: Oct 2026 -> Q2 FY27 (ended 30 Sep)."""
    m = date(int(period[-4:]), ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep",
                                "Oct", "Nov", "Dec"].index(period[:3]) + 1, 1)
    end_month = {1: 12, 2: 12, 3: 12, 4: 3, 5: 3, 6: 3, 7: 6, 8: 6, 9: 6, 10: 9, 11: 9, 12: 9}[m.month]
    end_year = m.year - 1 if m.month <= 3 else m.year
    fy = end_year + 1 if end_month >= 4 else end_year
    q = {6: 1, 9: 2, 12: 3, 3: 4}[end_month]
    return f"Q{q} FY{fy % 100:02d}", f"{end_year}-{end_month:02d}"


# ---------- step 2: per-call extraction (cheap model) ----------

ITEM = {"type": "OBJECT", "properties": {
    "metric": {"type": "STRING", "description": "short name, e.g. revenue growth, EBIT margin, order inflow, capex"},
    "claim": {"type": "STRING", "description": "what was said, in 15 words or fewer, plain English"},
    "quote": {"type": "STRING", "description": "verbatim words from the transcript, 8-40 words"},
    "speaker": {"type": "STRING"},
    "horizon": {"type": "STRING", "nullable": True, "description": "for guidance: e.g. next quarter, H2 FY27, FY27, medium term"},
    "quantified": {"type": "BOOLEAN", "description": "true if it has a number or range"},
}, "required": ["metric", "claim", "quote", "quantified"]}

CALL_SCHEMA = {"type": "OBJECT", "properties": {
    "guidance": {"type": "ARRAY", "items": ITEM,
                 "description": "forward-looking statements by management about the company's own performance"},
    "reported": {"type": "ARRAY", "items": ITEM,
                 "description": "results management reports for the quarter just ended"},
}, "required": ["guidance", "reported"]}

CALL_PROMPT = """These are sentences from {company}'s earnings call for {quarter} (held {period}),
trimmed to forward-looking and number-bearing lines, each prefixed with the speaker.

List:
1. guidance: what MANAGEMENT says about the company's own future performance
   (growth, margins, orders, capex, demand, targets). Not analysts' questions.
   At most 8, most specific first. Skip vague mood ("we remain confident").
2. reported: the headline results management states for the quarter just
   ended (growth, margin, order inflow...). At most 6.

Every quote must be copied word for word from the text below. Use only this
text; do not add anything you know about the company from elsewhere.

---
{text}"""


def extract_call(symbol: str, t: dict) -> dict:
    path = data_path("research", symbol, f"call-{fundamentals._slug(t['period'])}.json")
    cached = read_json(path)
    if cached:
        return cached
    source = data_path(t["text"]).read_text(encoding="utf-8")
    quarter, _ = call_quarter(t["period"])
    trimmed = trim(source)
    out, usage = llm.generate_json(
        CALL_PROMPT.format(company=symbol, quarter=quarter, period=t["period"], text=trimmed[:40000]),
        CALL_SCHEMA, llm.CHEAP)
    squashed = _squash(source)
    kept, dropped = {}, 0
    for kind in ("guidance", "reported"):
        kept[kind] = [i for i in out.get(kind, []) if quote_found(i["quote"], squashed)]
        dropped += len(out.get(kind, [])) - len(kept[kind])
    result = {"symbol": symbol, "period": t["period"], "quarter": quarter, "source_url": t["source_url"],
              "chars": {"transcript": len(source), "sent": len(trimmed[:40000])},
              "dropped_unverified": dropped, "usage": usage, **kept}
    write_json(path, result)
    return result


# ---------- step 4: promised vs delivered (strong model) ----------

VERDICTS = ["delivered", "partly", "missed", "pending", "dropped"]
REVIEW_SCHEMA = {"type": "OBJECT", "properties": {
    "headline": {"type": "STRING", "description": "one sentence, at most 25 words: the overall pattern"},
    "promises": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
        "made_in": {"type": "STRING", "description": "quarter label of the call, e.g. Q3 FY26"},
        "promise": {"type": "STRING", "description": "the guidance, 12 words or fewer"},
        "quote": {"type": "STRING", "description": "the guidance quote exactly as given in the input"},
        "horizon": {"type": "STRING", "nullable": True},
        "verdict": {"type": "STRING", "enum": VERDICTS},
        "evidence": {"type": "STRING", "description": "what actually happened, with the number, 25 words or fewer"},
        "evidence_from": {"type": "STRING", "description": "e.g. 'Q4 FY26 call' or 'reported numbers'"},
        "evidence_quote": {"type": "STRING", "nullable": True,
                           "description": "if the evidence is from a later call: its quote exactly as given in the input"},
        "direction": {"type": "STRING", "enum": ["at_least", "at_most", "within", "none"],
                      "description": "how the target is meant; none if not numeric"},
        "target_low": {"type": "NUMBER", "nullable": True},
        "target_high": {"type": "NUMBER", "nullable": True},
        "actual": {"type": "NUMBER", "nullable": True, "description": "the outcome, same unit and basis as the target"},
        "unit": {"type": "STRING", "nullable": True, "description": "e.g. %, ₹ crore, bps, days"},
    }, "required": ["made_in", "promise", "quote", "verdict", "evidence", "evidence_from"]}},
    "shifts": {"type": "ARRAY", "description": "where the story changed between calls; at most 3",
               "items": {"type": "OBJECT", "properties": {
                   "topic": {"type": "STRING"},
                   "change": {"type": "STRING", "description": "how the message moved, 25 words or fewer"},
                   "from_quarter": {"type": "STRING"}, "to_quarter": {"type": "STRING"},
               }, "required": ["topic", "change", "from_quarter", "to_quarter"]}},
}, "required": ["headline", "promises", "shifts"]}

REVIEW_PROMPT = """You are an analyst checking management's credibility for {company}.
Below: (A) guidance and reported results extracted from its last {n} earnings
calls, oldest first, each with a verified quote; (B) its reported quarterly
numbers (₹ crore, from the filed results).

For each material piece of guidance (skip trivial ones, merge repeats, at
most 10), decide what happened, using ONLY later calls in (A) and the numbers
in (B):
- delivered: the outcome met the guidance
- partly: direction right, size or timing short
- missed: the outcome contradicts the guidance
- pending: its horizon has not ended yet, or no later data covers it
- dropped: management stopped mentioning it or quietly replaced it
Quote guidance and evidence exactly as they appear in (A). Do not use any
outside knowledge of the company, its industry or the economy. If the data
cannot settle a promise, say pending; do not guess.

Rules:
- Repeating or reaffirming guidance is NOT delivery. "Delivered" needs an
  outcome: a reported number, or management saying it has happened.
- Indian fiscal years run April to March: FY26 = Apr 2025 to Mar 2026.
  A horizon has ended once (B) includes its last quarter; then judge it
  from (B) and the calls, do not call it pending. The latest reported
  quarter is {latest}.
- Prefer headline guidance (revenue growth, margins, orders, capex) over
  operational detail. Always include revenue growth and margin guidance
  if any was given.
- A promise never mentioned again after its horizon ended is "dropped".
- For numeric guidance whose outcome is known, fill target_low/target_high,
  actual, unit and direction, in the same unit and basis (growth % against
  growth %, ₹ crore against ₹ crore). Code will compare them.

Then list up to 3 shifts: places where management's message on a topic
changed from one call to a later one (a revised target, a pushed-out
timeline, a new explanation). A changed growth guidance range is a shift.

(A) CALLS
{calls}

(B) REPORTED QUARTERLY NUMBERS
{numbers}"""


def fiscal_totals(periods: list, values: list) -> dict:
    """Sum quarters into Indian fiscal years (Apr-Mar) and the half-year so
    far, so growth claims for a year can be checked against real totals.
    Code does this sum; the model only reads the result."""
    fy = {}
    for p, v in zip(periods, values):
        if v is None:
            continue
        month = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"].index(p[:3]) + 1
        year = int(p[-4:])
        label = f"FY{(year + 1 if month >= 4 else year) % 100:02d}"
        fy.setdefault(label, []).append((month, v))
    out = {}
    for label, qs in fy.items():
        if len(qs) == 4:
            out[label] = sum(v for _, v in qs)
        elif {m for m, _ in qs} == {6, 9}:
            out[f"H1 {label}"] = sum(v for _, v in qs)
    return out


def _growth_lines(q: dict) -> list:
    lines = []
    for k in ("Sales", "Revenue", "Net Profit"):
        if k not in q["rows"]:
            continue
        t = fiscal_totals(q["periods"], q["rows"][k])
        parts = []
        for label, v in t.items():
            prev = t.get(label.replace(label[-2:], f"{int(label[-2:]) - 1:02d}"))
            parts.append(f"{label} {v:,.0f}" + (f" ({(v / prev - 1) * 100:+.1f}% vs year before)" if prev else ""))
        if parts:
            lines.append(f"{k} by fiscal year: " + "; ".join(parts))
    return lines


def _numbers_table(summary: dict, quarters: int = 8) -> str:
    q = summary["quarters"]
    periods = q["periods"][-quarters:]
    keep = [k for k in q["rows"] if k in ("Sales", "Revenue", "Operating Profit", "OPM %", "Financing Profit",
                                          "Financing Margin %", "Profit before tax", "Net Profit")]
    lines = ["Metric | " + " | ".join(periods)]
    for k in keep:
        lines.append(f"{k} | " + " | ".join("" if v is None else f"{v:g}" for v in q["rows"][k][-quarters:]))
    return "\n".join(lines + [""] + _growth_lines(q))


def _calls_block(calls: list) -> str:
    parts = []
    for c in calls:
        g = "\n".join(f"  - [{i['metric']}] {i['claim']} (horizon: {i.get('horizon') or '?'}) \"{i['quote']}\""
                      for i in c["guidance"]) or "  (none)"
        r = "\n".join(f"  - [{i['metric']}] {i['claim']} \"{i['quote']}\"" for i in c["reported"]) or "  (none)"
        parts.append(f"## {c['quarter']} call ({c['period']})\nGuidance:\n{g}\nReported:\n{r}")
    return "\n\n".join(parts)


def settle(p: dict) -> dict:
    """Numbers decide a numeric promise, not the model. Delivered if met;
    partly if within 1 point (for %) or 10% (for amounts); else missed.
    Pending and dropped are about timing, so the model's call stands."""
    lo, hi, act, d = p.get("target_low"), p.get("target_high"), p.get("actual"), p.get("direction")
    if act is None or d in (None, "none") or (lo is None and hi is None) or p["verdict"] in ("pending", "dropped"):
        return p
    if d == "within" and (lo is None or hi is None):  # a band with one edge is a floor or a ceiling
        d = "at_least" if lo is not None else "at_most"
    lo, hi = (lo if lo is not None else hi), (hi if hi is not None else lo)
    pct = (p.get("unit") or "").strip() in ("%", "percent", "pp")
    tol = 1.0 if pct else 0.10 * max(abs(lo), abs(hi))
    if d == "at_least":
        met, near = act >= lo, act >= lo - tol
    elif d == "at_most":
        met, near = act <= hi, act <= hi + tol
    else:
        met, near = lo <= act <= hi, lo - tol <= act <= hi + tol
    verdict = "delivered" if met else "partly" if near else "missed"
    out = {**p, "verdict_by": "numbers"}
    if verdict != p["verdict"]:
        out.update(verdict=verdict, model_verdict=p["verdict"])
    return out


def rescore(symbol: str) -> dict:
    """Re-apply settle() to a saved review. Free: no model calls."""
    path = data_path("research", symbol, "review.json")
    r = read_json(path)
    r["promises"] = [settle({**p, "verdict": p.get("model_verdict", p["verdict"])}) for p in r["promises"]]
    for p in r["promises"]:
        if p.get("model_verdict") == p["verdict"]:
            p.pop("model_verdict")
    r["counts"] = {v: sum(1 for p in r["promises"] if p["verdict"] == v) for v in VERDICTS}
    write_json(path, r)
    return r


def review(symbol: str, refresh: bool = False, transcripts: int = 4) -> dict:
    """Promised vs delivered for any NSE symbol screener.in covers."""
    path = data_path("research", symbol, "review.json")
    cached = read_json(path)
    if cached and not refresh:
        return cached
    summary = read_json(data_path("fundamentals", symbol, "summary.json"))
    if not summary or len(summary.get("transcripts_saved", [])) < transcripts:
        summary = fundamentals.fetch_fundamentals(symbol, transcripts)
    saved = summary["transcripts_saved"][:transcripts]
    if not saved:
        raise ValueError(f"no concall transcripts found for {symbol}")
    # The four calls are independent: read them in parallel (an on-demand
    # request should take seconds, not minutes).
    with ThreadPoolExecutor(max_workers=4) as pool:
        calls = list(pool.map(lambda t: extract_call(symbol, t), saved))
    calls.sort(key=lambda c: call_quarter(c["period"])[1])
    out, usage = llm.generate_json(
        REVIEW_PROMPT.format(company=symbol, n=len(calls), calls=_calls_block(calls),
                             numbers=_numbers_table(summary), latest=summary["quarters"]["periods"][-1]),
        REVIEW_SCHEMA, llm.REASONING, retries=1, timeout=90)  # busy? step down at once

    # The strong model may only quote what step 2 verified.
    verified = {_squash(i["quote"]) for c in calls for k in ("guidance", "reported") for i in c[k]}
    ok = lambda q: bool(q) and any(_squash(q) in v or v in _squash(q) for v in verified)
    promises = []
    for p in out.get("promises", []):
        if not ok(p["quote"]):
            continue
        if p.get("evidence_quote") and not ok(p["evidence_quote"]):
            p["evidence_quote"] = None
        promises.append(settle(p))
    counts = {v: sum(1 for p in promises if p["verdict"] == v) for v in VERDICTS}
    result = {
        "symbol": symbol, "headline": out.get("headline", ""), "counts": counts,
        "promises": promises, "shifts": out.get("shifts", [])[:3],
        "calls": [{"quarter": c["quarter"], "period": c["period"], "url": c["source_url"],
                   "guidance": len(c["guidance"]), "reported": len(c["reported"]),
                   "dropped_unverified": c["dropped_unverified"]} for c in calls],
        "numbers": {"periods": summary["quarters"]["periods"][-8:],
                    "rows": {k: v[-8:] for k, v in summary["quarters"]["rows"].items()
                             if k in ("Sales", "Revenue", "OPM %", "Financing Margin %", "Net Profit")}},
        "dropped_from_review": len(out.get("promises", [])) - len(promises),
        "usage": [c["usage"] for c in calls] + [usage],
    }
    write_json(path, result)
    return result
