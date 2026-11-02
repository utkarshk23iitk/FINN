# Decisions

Short record of choices that shape FINN, and why. Newest last.

## Data layer (30 Oct, planning chat)

1. **Rules first, model for leftovers.** Regex rules classify most NSE
   announcements for free. Only items they can't place (`needs_llm`) go to
   a cheap model.
2. **Priority is separate from category.** A results *intimation* ranks
   below the results. CFO resignations and rating downgrades are promoted.
   Auditor appointments are buried, auditor resignations flagged.
3. **Cache everything.** The app reads only from `data/`, so the demo works
   even if NSE, Yahoo or screener.in is down.
4. **screener.in "Operating Profit" is only an EBITDA proxy** (it excludes
   other income). It is used to cross-check numbers taken from the results
   filing, never shown as EBITDA on its own.

## Push screen (3 Nov)

5. **A triage queue, not a feed.** The screen answers one question first:
   "how many things need me?" Each alert has a Done button. Done items
   collapse into "cleared", so the investor can finish the morning check
   instead of scrolling forever. Below that: "worth a look" (one line each),
   then routine filings folded into a single line with counts.
6. **Price moves explain themselves.** A price or volume alert looks for the
   most important filing from 3 days before to the morning after, and shows
   it as "Likely why". When there is none, it says so, which is a signal
   in itself.
7. **One card per company, type and day.** A results day brings 3–5 filings
   (outcome, results, deck, press release). They fold into one card with
   "+N related".
8. **The user owns the thresholds.** Volume multiple, % move and which
   filing types alert are set in the app and applied in the browser, so the
   queue re-sorts instantly. Only types that can reach high priority are
   offered as toggles; a switch that never changes anything is worse than
   no switch.
9. **Static site, no server, for the push side.** `export_web.py` turns the
   cache into one `feed.json`; the page is plain HTML/JS. Nothing to cold
   start, nothing to break during a demo. A server is added only where it is
   needed (pull-side research).
10. **Windows count back from the last refresh, not from "now".** The header
    says "as of" that time. A reviewer opening the link days later sees a
    real "last 24h", not an empty screen.

## Results card (3 Nov)

11. **Code finds the page, the model copies, code does the maths.** Code
    picks the 1–2 pages with the full P&L (about 3k tokens instead of a
    20-page PDF). A cheap model copies line items for every quarter column
    with its date. Code then decides which column is QoQ and YoY (ITC
    prints this quarter, last year, last quarter), computes EBITDA, and
    converts units.
12. **EBITDA = revenue − (total expenses − finance costs − depreciation).**
    Operating only: other income, associates and exceptional items are out.
    It matches screener.in's "Operating Profit" for TCS to the rupee crore.
    For lenders EBITDA means nothing; the card shows pre-provision profit
    (printed, or PBT + impairment).
13. **Checks decide trust, not the model.** PBT − tax (+ associates added
    after tax) must equal PAT within 0.1%. A real case: ITC's OCR text
    reads "51B6.55"; a model returned 5156.55; the check says 5186.55. A
    failed check gets one retry on the stronger model; if it still fails,
    the card says "check the filing" instead of showing wrong numbers as
    fact.
14. **The unit is read from the statement by code.** Maruti reports in
    ₹ million; the model said crore (a 10× error no arithmetic check can
    catch). Revenue and PAT are also compared with screener.in (±3%); a
    mismatch flags the card.

## Promised vs delivered (3 Nov)

15. **Primary sources only, enforced in code.** Inputs are the last four
    call transcripts and the filed quarterly numbers. Every quote the model
    returns is matched word for word (letters and digits) against the
    transcript; a quote that isn't there is dropped, and the page says how
    many were. The model cannot put words in management's mouth.
16. **Three steps, priced by difficulty.** Code trims each transcript to
    forward-looking and number-bearing sentences (about 40% of the text).
    The cheap model lists guidance and reported results per call (4 calls,
    in parallel). One stronger call judges promises against outcomes.
    About 25k tokens per company; cached, so a second look is free.
17. **Code does the year sums.** Fiscal-year totals and growth (Apr–Mar)
    are computed from the reported quarters and handed to the model, so
    "15% growth this year" is judged against 11.5% actual, not guessed.
18. **Reaffirming is not delivering.** The first run marked INFY 5 of 5
    "delivered" because targets were repeated in later calls, and kept
    IRCTC's ended FY26 target "pending". The prompt now says both rules
    outright, and the latest reported quarter is given.
19. **Lead with the misses.** The page shows "N of M settled promises
    delivered", then missed, partly, dropped, delivered, pending. Each
    promise opens to the exact quote and a link to the transcript.
20. **Free tier limits shape the routing.** Flash allows 20 requests a
    day, Pro none. The judging step asks for `gemini-3.8-flash`, falls back
    to Flash-Lite when it is busy or out of quota, and the page says which
    model answered. `GEMINI_REASONING_MODEL` switches it.
21. **Any ticker, on demand.** `/api/research?symbol=X` runs the same
    pipeline on Vercel (writing to /tmp) and the CDN keeps the answer for a
    day. Pre-built companies load as static files and cost nothing.
22. **Numbers settle numeric promises, not the model.** The judge returns
    target, actual, unit and direction; code decides delivered / partly
    (within 1 pt, or 10% for amounts) / missed. Real case: IRCTC guided
    "15% sustainable growth this year", FY26 sales grew 11.5%, Flash-Lite
    said "delivered". Code says missed, and the page shows both.
