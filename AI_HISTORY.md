# AI build history: a guide for reviewers

FINN was built with two AI tools: claude.ai for planning, and Claude Code
for the build. The full conversations are attached to the submission email.
This page shows where to look in them, and links each moment to the commit
it produced.

## The conversations

| # | Where | When | What happened |
|---|---|---|---|
| 1 | claude.ai planning chat (share link in the email) | 30 Oct | Read the brief, set the portfolio and research companies, built and tested the Python data layer, wrote `docs/handoff.md` for Claude Code |
| 2 | Claude Code: main build session | 2–3 Nov | Checked the real state against the handoff, then built the Today tab, results card, research, deploy, writeup |
| 3 | Claude Code: Q&A session | 3 Nov | My questions about the app: what "5 things need you" means, what the rules line means, how often data refreshes |
| 4 | Claude Code: short session | 3 Nov | "We are not using any database?", checking the architecture |

## Who decided what

**My decisions (the owner):**
- The planning-chat choices, carried into `DECISIONS.md` 1–4: rules first
  with a model only for leftovers, priority kept separate from category,
  everything cached so the demo never depends on a live scrape, and
  screener.in's operating profit used only as an EBITDA cross-check.
- The order of work and what to build: the push screen, the results card,
  promised vs delivered, then the two additions (guidance-change alerts and
  the spoken brief) picked from options Claude proposed.
- Gemini as the model provider. I created the key and kept it out of the
  chat (it went straight from `.env` to Vercel's encrypted settings).
- Each outward step needed my approval in the session: the production
  deploy (Claude Code's permission check blocked the first attempt until I
  said yes), storing the key on Vercel, and pushing to the GitHub repo I
  created.

**Claude Code's work:** proposing designs, writing the code and tests,
running them against real data, and reporting what failed. The
implementation was AI-written; the transcripts show where it was checked
and corrected.

## Where AI output was caught and corrected

Each of these came from real data, and most became a test.

**The handoff itself was out of date** (start of session 2). It said the
data layer was done. The check found no git history at all (the folder sat
inside another repo), prices for 1 company instead of 18, and a transcript
bug that silently lost one quarter. → `95ad7ba`, `63ef00c`

**Classifier.** A RELIANCE call transcript ranked as "results" (priority
90) because its text says "unaudited financial results". → `e819a1d`

**Results card.** The model's first answers looked plausible and were
wrong in four ways:
- It read the newspaper "extract" page, which has no expense lines, and
  the card was still marked OK. The page ranking and the OK rule were
  tightened. → `de4838d`
- ITC's OCR text printed "51B6.55"; the model returned 5156.55. PBT − tax
  says 5186.55, and a 1% tolerance had let it through, so it was tightened
  to 0.1%. → `de4838d`
- Maruti reports in ₹ million; the model said crore (100x off). The unit is
  now read by code and cross-checked with screener.in. → `4c6fbf5`
- RELIANCE prints PAT twice (before and after associates); the model took
  the first. → `4c6fbf5`

**Promised vs delivered.** The first full run read well and was wrong:
- INFY scored "5 of 5 delivered" because management *repeated* its targets.
  Repeating is not delivering.
- IRCTC's FY26 target was "pending" although FY26 had ended.
- After the prompt fix, IRCTC's "15% growth this year" was still
  "delivered" with 11.5% actual. Code now settles numeric promises, and the
  page shows when it overruled the model (6 times). → `b398281`
- Claude Code's own fix had a bug: a band with one edge ("mid-single-digit,
  at least 4%") marked 4.9% as partly. → `61cac93`
- When code overruled the model, the model's prose still argued the
  opposite on the same card. → `3585a05`
- 8 quotes the model attributed to management were not in the transcripts
  and were dropped automatically.

**Deploy.** Two over-broad `.vercelignore` patterns first hid the API, then
the site's data. Both were caught by checking the live URLs after each
deploy. → `c636a3f`, `382d12e`

**Claude Code correcting its own reports.** It told me 28 tests passed (it
was 24), 13 companies had results cards (14), and that 13 companies had the
story check (9). Each was corrected when the numbers were re-counted from
the data. → `ee65461`

## Limits stated rather than hidden

- The free tier allows 20 stronger-model calls a day and no Pro, so the
  research judgments ran on Flash-Lite, and they vary between runs
  (PIDILITIND: 3 of 4, then 5 of 5). Recorded in `DECISIONS.md` 23.
- The data is a snapshot from 3 Nov; NSE blocks cloud servers, so there is
  no nightly refresh.

## How to check any of this

- `git log`: 36+ small commits, each saying what changed and why.
- `DECISIONS.md`: 26 decisions, each with the real case that caused it.
- `python -m unittest discover -s tests`: 25 offline tests, many built
  from the real failures above.
