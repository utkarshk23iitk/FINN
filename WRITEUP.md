**To:** assessment@enam.com
**Subject:** ENAM - IIT screening - 2027

Hello ENAM team,

Here is my submission for the FINN challenge.

- **Prototype (open on a phone):** https://finn-portfolio-gamma.vercel.app
- **Repository:** https://github.com/utkarshk23iitk/FINN
- **AI build history:** [claude.ai planning chat link] and [Claude Code session export, attached]

## What I built

FINN has two tabs.

**Today (push).** A triage queue for an 18-company portfolio, not a feed. It
opens with one sentence: "5 things need you". Each alert has a Done button,
and the screen ends with "All clear". Below that sit "worth a look" items (one
line each), then routine filings folded into one line with counts. The window
(24h / 3 days / week / month) and the alert rules (volume multiple, % move,
which filing types alert) are set by the user and applied instantly.

- A price or volume alert shows the filing that most likely explains it
  (DEEPAKNTR traded 24x its usual volume the day after its results).
- A results filing becomes a card with Revenue, EBITDA, PBT and PAT, QoQ and
  YoY, read from the company's own filing, with one line on what happened:
  "PAT −18.5% YoY on revenue +43.9% · EBITDA margin −13.0 pts".
- **Push and pull meet.** A call transcript is usually routine, so it stays
  one line, with the company's track record. When the new call changes the
  story (a revised target, a pushed-out timeline, an earlier promise now
  shown missed), it becomes a "Guidance change" alert that says what
  changed. 13 companies have this check; the newest call is read from the
  NSE filing itself, because screener.in lagged by days.
- **"▶ Listen"** reads the queue aloud with the phone's own voice and
  outlines each card as it goes. It is built by code from the same data: no
  model, no cost, nothing invented.

**Research (pull).** "Promised vs delivered" for any NSE ticker: what
management guided in its last four earnings calls, against what it then
reported. The page leads with the count ("0 of 2 settled promises
delivered"), shows misses first, and every promise opens to the exact quote
and a link to the transcript. It also shows where the story moved between
calls. Five companies are prepared; any other ticker is analysed on demand
in about 20 seconds.

## Key decisions

1. **Code does the maths; the model only reads.** For results, code finds the
   P&L page, the model copies the line items, and code computes EBITDA,
   QoQ/YoY and units. For research, code sums fiscal years and decides any
   numeric verdict.
2. **Checks decide trust, not the model.** Each one exists because of a real
   error in real data:
   - ITC's OCR text reads "51B6.55"; the model returned 5156.55. PBT − tax
     says 5186.55, so the card is flagged.
   - Maruti reports in ₹ million; the model said crore. A cross-check with
     screener.in caught the 100x slip.
   - Every quote from a transcript is matched word for word; 5 invented
     quotes were dropped.
   - IRCTC guided "15% growth this year" and delivered 11.5%; the model said
     "delivered". The numbers now decide, and the page shows that the model
     disagreed (4 such overrides).
3. **Rules first, models for the rest.** 274 filings are classified and
   ranked by rules at zero cost. Priority is separate from category: a CFO
   resignation is promoted, an auditor appointment buried.
4. **Cheap model by default, stronger only when needed.** 49 model calls,
   about 250k tokens in total, all on Gemini's free tier. Flash-Lite does the
   reading; a stronger model is used only when a check fails. Everything is
   cached, so nothing is paid for twice.
5. **The demo never depends on a live scrape.** The Today tab is a static site
   built from a cache. Research for a new ticker runs as one serverless
   function, and its answer is cached for a day.

## Deliberately left out

- **Management-change bios.** The brief suggests LinkedIn; scraping it is
  against its terms, and I did not want a fragile source in the demo.
- **Real push notifications and a nightly refresh.** NSE blocks cloud
  servers, so the data is a snapshot from 3 Nov.
- **The other research sections** (business snapshot, bull vs bear, and so
  on). I chose to do one section well.
- **Accounts and an editable portfolio.**

## Known limits

- The free tier allows 20 stronger-model calls a day and no Pro access, so
  the research judgments ran on Flash-Lite. Its verdicts can change between
  runs (PIDILITIND: 3 of 4 delivered, then 5 of 5). Quotes, sums and numeric
  verdicts are fixed by code; the rest needs a stronger model.
- A "missed" verdict is sometimes given before a promise's horizon has
  ended.

## Where it goes next

- A nightly refresh from a machine NSE accepts, with real notifications.
- Management bios from the company's own filings (appointment letters carry
  a short profile).
- The stronger model for research judgments, with a longer cache.

All design choices and the reasons for them are in `DECISIONS.md` in the
repository.

Thank you,
[Your name]
