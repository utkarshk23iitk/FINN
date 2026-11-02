# FINN: handoff from the planning chat

Context for Claude Code, written at the end of a claude.ai planning session
(Fri 30 Oct 2026). Work may have moved on since then, so check the repo
before trusting the Status section.

Full brief and glossary: @brief.md

## The task

ENAM Holdings "AI Engineer Build Challenge". Build FINN, a mobile-first
financial investment agent for Indian equities (NSE/BSE).

- **Push**
  - Windowed digest: every announcement across a 15–20 company portfolio
    for a window the user picks (default last 24h), important first,
    routine items collapsed or hidden.
  - Triggered alerts: material announcement types the user cares about;
    EOD volume > ~2x recent average or price move beyond ±X% (thresholds
    configurable by the user).
  - Management change → short background/bio of the incoming person.
  - Quarterly results → Revenue, EBITDA, PBT, PAT, QoQ and YoY, from the
    actual results filing.
  - Other types: decide what earns attention (one-line summary vs. just
    the filing at the right priority). That judgment is graded.
- **Pull**: on-demand research on any NSE ticker (never hard-wired to the
  demo set), grounded ONLY in primary sources: annual reports + concall
  transcripts. No news, broker notes, or the model's own knowledge of the
  company. Most valued output: "numbers vs narrative" — over the last four
  quarters, what management guided vs. what was actually delivered.
- **Interaction model** is open (chat, voice, copilot, feed, something
  new). They want a point of view on how an investor should interact,
  not just what data to show. Everything mobile-first.

## How it's graded

- Creativity, product sense, judgment, architecture. Not completeness.
- Thin-but-working beats broad-but-broken. A demo that doesn't run is the
  worst outcome. "Build the smallest thing that proves you can build the
  real thing well."
- "No AI slop": concise, dense, beautifully presented, interactive.
- Cost efficiency earns bonus points: cheap models for bulk extraction, a
  strong model only where reasoning needs it; caching; chunking. Doable on
  free tiers.
- They read the AI build history, so it should show planning, critique of
  AI output, and the owner's own decisions.

## Submission

Email to `assessment@enam.com`, subject `ENAM - IIT screening - 2027`, with:
- the mobile-first prototype (deployed link, Expo/TestFlight, or responsive
  web), easy to try on a phone
- the GitHub repo
- the AI build history: the claude.ai planning chat + Claude Code
  transcripts (`/export` in each session)
- a short writeup in the email: what was built, key decisions and
  trade-offs, what was deliberately left out, where it goes next

Deadline: Tuesday 3 November 2026 (extended from Sunday 1 Nov in the brief).

## Status as of Mon 2 Nov (checked in Claude Code)

Deadline extended to Tue 3 Nov, so 3 Nov is the last day to submit.

Nothing new was built since the planning chat. What is true now:
- **No git history.** `finn-data/` has no repo of its own. It sits untracked
  inside a parent repo at `~/Desktop` (remote: Coupon-Wallet, branch
  `feat/diagnosis-prototype`). FINN has zero commits.
- **`.gitignore`** lists only `docs/brief.md`. Missing: `.env`,
  `__pycache__/`, and a decision on whether `data/` is committed.
- **Tests:** 10/10 pass, but only with `/opt/miniconda3/bin/python`. The
  default `python3` (3.13) has no numpy.
- **Cached data (`data/`, 2.2 MB):**
  - announcements: 242 items for all 18 companies, 30 Sep to 30 Oct.
    Tiers: 64 high, 48 medium, 130 low. 82 have `needs_llm`. The latest
    item is from 30 Oct, so a "last 24h" window run today is empty.
  - prices: TCS only (to 30 Oct). The other 17 companies have none.
  - fundamentals: TCS only. None for the 4 research companies.
- **Bug:** TCS has 3 transcripts, not 4. screener.in lists a 2025 call
  under the label "Jul 2026". It maps to the same file name as the real
  Jul 2026 call, so it is skipped, and the 4th transcript (Jan 2026) is
  never fetched. `summary.json` also stores the wrong `source_url` for it.
- **Not started:** LLM pass, results card, promised-vs-delivered, API,
  frontend, deploy, `DECISIONS.md`.

## Status as of Fri 30 Oct (end of planning chat)

Python data layer, done and tested:
- `config.py`: 18-company portfolio, 4 research companies, alert
  thresholds, fetch settings
- `finn/prices.py`: yfinance EOD (`.NS`, falls back to `.BO`), CSV cache,
  `compute_signals` / `scan_alerts` (volume average excludes the current day)
- `finn/announcements.py`: NSE client (cookie warm-up, retries once on
  401/403), `normalise`, dedupe cache, `digest(symbols, since, until)`
- `finn/classify.py`: rule-based categories (ENAM's list), priority 0–100,
  tier high/medium/low; `needs_llm=True` marks items the rules can't place
- `finn/fundamentals.py`: screener.in quarterly table, concall and annual
  report links, transcripts saved as PDF + `.txt`, `headline_numbers()`
  with QoQ/YoY
- `fetch_all.py` CLI; `tests/test_offline.py` (offline, all passing)

Verified live on the owner's Mac: TCS prices (248 days), screener.in (13
quarters, 4 transcripts, 15 annual reports), NSE (19 TCS announcements in
October).

NSE quirks found in real data (already handled, with tests):
- `sort_date` sometimes lacks the space: `2026-10-1911:30:07`
- Generic subjects ("Updates", "Analysts/Institutional Investor Meet/Con.
  Call Updates") carry no information; the real content is in
  `attchmntText`, so the classifier reads the text first for those.

## Decisions so far (for the writeup)

1. Rules classify most announcements for free; only `needs_llm` leftovers
   go to a cheap model.
2. Priority is separate from category. A results intimation ranks below
   actual results; CFO resignations and rating downgrades are promoted;
   auditor appointments are buried, auditor resignations flagged.
3. Everything is cached in `data/` and the app reads from the cache, so
   the demo works even if a source is down.
4. screener.in's "Operating Profit" excludes other income, so it is
   labelled an EBITDA proxy and used only to cross-check numbers extracted
   from the results filing.

## Planned next steps (adjust to what is already done)

1. LLM pass for `needs_llm` announcements (cheap model, cached by
   announcement id) + one-line summaries for medium-tier items.
2. Results card: extract the four numbers from the results filing PDF with
   a cheap model; cross-check against screener.in.
3. Pull: "promised vs delivered" from the last 4 transcripts. Extract
   guidance per quarter with source quotes, compare with reported numbers.
   Use the strong model only here.
4. Small API (e.g. FastAPI) over the cache + mobile-first web frontend.
   Deploy early, not at the end.
5. If time allows: management-change bios, more research sections.
6. Writeup and AI-history export.

## Working rules

- Run `python -m unittest discover -s tests` after changing data code.
  When a bug comes from real data, add that real case as a test.
- The demo must never depend on a live scrape working.
- Research code must work for any NSE ticker; don't hard-code the demo set.
- API keys go in `.env` (gitignored). Keep `docs/brief.md` out of the
  public repo (it is ENAM's material).
- Commit in small steps with clear messages; the history is evaluated.
- Explain decisions briefly as you go, and record lasting ones in
  `DECISIONS.md`.
- The owner's first language isn't English: keep explanations plain and
  short.

## First thing to do in a new session

Check the real state (git log, `ls data/`, run the tests, look for any
frontend code), update the Status section above, then propose the next step.
