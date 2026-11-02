"""Zero-cost, rule-based classification of exchange announcements.

Categories follow ENAM's reference document. Rules handle the bulk of the
feed for free; anything they can't place confidently is marked
`needs_llm=True`, so a cheap model only sees the leftovers. That split is the
"smart model routing" the brief asks for.

Priority is separate from category on purpose: a results *intimation*
("board meets on the 25th") matters far less than the results themselves,
even though both are category "results".
"""
import re

# Ordered: the first matching rule wins, so specific rules come before broad ones.
RULES = [
    ("results", [r"financial results?", r"\bresults? for the (quarter|year|period)",
                 r"integrated filing.{0,10}financ", r"un-?audited", r"\baudited financial",
                 r"outcome of board meeting.*result", r"limited review"]),
    # Not "con. call" alone: NSE puts that in the generic subject it uses for
    # investor-meeting schedules too. The detail text decides (see GENERIC_SUBJECTS).
    ("earnings_call", [r"conference call", r"earnings call", r"con\.? ?call (transcript|recording)",
                       r"transcript", r"audio recording", r"call recording"]),
    ("insider_trading", [r"insider trading", r"regulation 7\(2\)", r"\bsast\b",
                         r"takeover regulations", r"acquisition of shares by promoter",
                         r"disclosure under sebi \(?substantial"]),
    ("pledging", [r"pledg", r"encumbrance"]),
    ("management_change", [r"change in (director|management|key managerial|kmp)",
                           r"\bresign", r"\bappoint(?!ment of (statutory|secretarial|internal|cost) auditor)", r"cessation", r"re-?designat",
                           r"\b(ceo|cfo|managing director|whole[- ]time director|company secretary)\b.*(join|exit|retire)"]),
    ("M&A", [r"acqui(re|sition)", r"amalgamation", r"\bmerger", r"demerger",
             r"scheme of arrangement", r"joint venture", r"\bjv\b", r"divest",
             r"stake (sale|purchase)", r"incorporation of (a )?(wholly owned )?subsidiary",
             r"investment in (wholly owned )?subsidiar"]),
    ("fund_raise", [r"rights issue", r"\bqip\b", r"qualified institution",
                    r"preferential (issue|allotment)", r"buy-?back", r"commercial paper",
                    r"non-convertible debenture", r"\bncds?\b", r"raising of funds", r"fund raising"]),
    ("credit_rating", [r"credit rating", r"\brating(s)? (assign|reaffirm|upgrad|downgrad|revis)",
                       r"\b(crisil|icra|care ratings|india ratings|brickwork)\b"]),
    ("litigation", [r"litigation", r"\border(s)? passed", r"action\(s\) initiated", r"penalty",
                    r"\bfine\b", r"show cause", r"insolvency", r"\bnclt\b", r"\bsebi order",
                    r"tax demand", r"regulatory action", r"\bgst\b.*(demand|order)"]),
    ("dividend", [r"dividend"]),
    ("bonus_split", [r"\bbonus\b", r"sub-?division", r"stock split", r"split of (equity )?shares"]),
    ("capex", [r"capex", r"capital expenditure", r"capacity expansion", r"new (plant|facility|unit)",
               r"commencement of (commercial )?(production|operations)", r"greenfield", r"brownfield"]),
    ("investor_meetings", [r"analysts?/institutional investor meet", r"investor meet",
                           r"analyst meet", r"investor conference", r"schedule of (analyst|investor|meet)",
                           r"\bnon-deal roadshow", r"one-on-one"]),
    ("postal_ballot", [r"postal ballot"]),
    ("agm_egm", [r"\bagm\b", r"\begm\b", r"annual general meeting", r"extraordinary general",
                 r"shareholders?'? meeting", r"voting results", r"scrutinizer"]),
    ("press_release", [r"press release", r"order (win|received|inflow)", r"bagging", r"receiving of orders",
                       r"new (product|launch)", r"partnership", r"clarification", r"\bmou\b",
                       r"agreement", r"contract"]),
    ("unclassified", [r"newspaper", r"trading window", r"esop|esos|esps", r"allotment of (equity )?shares under",
                      r"compliance certificate", r"certificate under", r"regulation 74\(5\)",
                      r"loss of share certificate", r"duplicate share", r"\besg\b", r"business responsibility",
                      r"statutory auditor", r"secretarial", r"registered office", r"record date",
                      r"investor complaints", r"reg\. 40\(9\)", r"cut-off date"]),
]
COMPILED = [(cat, [re.compile(p, re.I) for p in pats]) for cat, pats in RULES]

# Base importance, 0-100. Tunable — and worth defending in the writeup.
BASE_PRIORITY = {
    "results": 90, "M&A": 85, "management_change": 80, "fund_raise": 75,
    "litigation": 70, "pledging": 70, "credit_rating": 60, "insider_trading": 55,
    "capex": 55, "press_release": 45, "bonus_split": 45, "dividend": 40,
    "earnings_call": 35, "investor_meetings": 15, "agm_egm": 15,
    "postal_ballot": 10, "unclassified": 5,
}

# Wording that changes how much an item matters, regardless of category.
DEMOTE = [r"intimation", r"\bnotice\b", r"newspaper", r"advertisement", r"schedule of",
          r"prior intimation", r"record date", r"\bcorrigendum"]
PROMOTE = [r"downgrad", r"\b(ceo|cfo|managing director|chairman)\b", r"resign", r"default",
           r"insolvency", r"\bsebi order", r"fraud", r"search (and|&) seizure", r"\braid\b"]
DEMOTE_RE = [re.compile(p, re.I) for p in DEMOTE]
# Note: only auditor *appointments* are routine; an auditor resigning is a red flag.
ROUTINE_FIRST = [r"(re-?)?appointment of (the )?(statutory|secretarial|internal|cost) auditors?", r"newspaper (publication|advertisement)",
                 r"closure of trading window", r"loss of share certificate"]
ROUTINE_RE = [re.compile(p, re.I) for p in ROUTINE_FIRST]

# NSE subjects that say little on their own; the detail text says what happened.
GENERIC_SUBJECTS = {
    "updates", "general updates", "analysts/institutional investor meet/con. call updates",
    "outcome of board meeting", "board meeting intimation", "press release",
    "announcement under regulation 30 (lodr)",
}
PROMOTE_RE = [re.compile(p, re.I) for p in PROMOTE]


def classify(subject: str, text: str = "") -> dict:
    """Return {category, priority, tier, needs_llm, matched}.

    The subject line is usually checked first (it's the exchange's own label).
    For catch-all subjects like "Updates", the detail text is checked first,
    because that's where the real information is.
    """
    subject = subject or ""
    text = (text or "")[:600]
    category, matched = None, None
    # Routine paperwork often hides behind generic subjects ("Appointment"),
    # so check the full text for it before anything else.
    routine = next((p.pattern for p in ROUTINE_RE if p.search(f"{subject} {text}")), None)
    if routine:
        category, matched = "unclassified", routine
    generic = subject.strip().lower() in GENERIC_SUBJECTS
    order = (text, f"{subject} {text}") if generic else (subject, f"{subject} {text}")
    for source in (() if category else order):
        for cat, patterns in COMPILED:
            hit = next((p.pattern for p in patterns if p.search(source)), None)
            if hit:
                category, matched = cat, hit
                break
        if category:
            break

    combined = f"{subject} {text}"
    needs_llm = category is None or (category == "press_release" and len(text) > 40)
    category = category or "unclassified"

    priority = BASE_PRIORITY[category]
    if any(p.search(combined) for p in DEMOTE_RE):
        priority -= 30
    if any(p.search(combined) for p in PROMOTE_RE) and category != "unclassified":
        priority += 15
    priority = max(0, min(100, priority))

    tier = "high" if priority >= 70 else "medium" if priority >= 35 else "low"
    return {"category": category, "priority": priority, "tier": tier,
            "needs_llm": needs_llm, "matched": matched}
