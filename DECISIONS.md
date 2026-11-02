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
