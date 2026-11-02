# FINN data layer

Fetches and caches the three data sources from the ENAM brief:

| Source | Module | Saved to |
|---|---|---|
| End-of-day price & volume (Yahoo Finance) | `finn/prices.py` | `data/prices/SYMBOL.csv` |
| NSE corporate announcements | `finn/announcements.py` | `data/announcements/SYMBOL.json` |
| Quarterly numbers, concall transcripts, annual-report links (screener.in) | `finn/fundamentals.py` | `data/fundamentals/SYMBOL/` |

Everything is cached locally, so the app reads from `data/` and the demo works even if a site is down.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m unittest discover -s tests   # offline tests, no internet needed
```

## Run

```bash
python fetch_all.py                                 # everything
python fetch_all.py --only prices
python fetch_all.py --only announcements --days 7
python fetch_all.py --only fundamentals --symbols INFY
python fetch_all.py --summary                       # print what's cached
```

Edit `config.py` to change the portfolio, research companies, or alert thresholds.

## What's already built in

- **Configurable alerts** (`prices.scan_alerts`): volume above N× its 20-day average, or a daily move beyond ±X%. The average excludes the current day, so a spike can't inflate its own baseline.
- **Free classification** (`finn/classify.py`): rules map each announcement to ENAM's categories and give it a priority. Only items the rules can't place get `needs_llm=True`, so a model only sees the leftovers. This is the cost-efficiency point the brief rewards.
- **Priority is not the same as category.** A results *intimation* scores lower than the results themselves; a CFO resignation or rating downgrade scores higher; an auditor resigning is flagged, while an auditor appointment is buried.
- **Windowed digest** (`announcements.digest`): cached announcements in any time window, most important first.
- **Headline numbers** (`fundamentals.headline_numbers`): Revenue, EBITDA, PBT, PAT with QoQ and YoY change.
- **Transcripts as text**: each PDF is converted to `.txt` once, so you never pay to process the same file twice.

## Known caveats

- **NSE has no official API.** The client copies what the website does (visit a page for cookies, then call the JSON endpoint). It retries once on 401/403. Run it from your own internet connection, not a cloud server. If NSE still blocks you, BSE has a similar feed.
- **screener.in's "Operating Profit" excludes other income**, so it's an EBITDA *proxy*. Label it that way in the app. The brief wants the results card built from the results filing itself; use these numbers to cross-check what your model extracts.
- Some transcript links point to web pages instead of PDFs. Those are skipped with a message.
- The fetchers could not be tested against the live sites while they were being built (only the offline tests ran). Run `python fetch_all.py --symbols TCS --days 7` first and check the output.
