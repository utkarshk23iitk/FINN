"""FINN data-layer settings. Edit this file to change your portfolio or alert rules."""
from pathlib import Path

# --- Companies ---------------------------------------------------------------
# NSE symbols (no ".NS" suffix). This is a starting suggestion: a mix of sectors
# and sizes so the demo has variety. Swap in companies you find interesting —
# choosing the portfolio is part of the judgment ENAM is grading.
PORTFOLIO = [
    # Large caps
    "RELIANCE",    # Energy / conglomerate
    "HDFCBANK",    # Private bank
    "TCS",         # IT services
    "BHARTIARTL",  # Telecom
    "ITC",         # FMCG
    "LT",          # Engineering & infrastructure
    "SUNPHARMA",   # Pharma
    "MARUTI",      # Autos
    "TATASTEEL",   # Metals
    "BAJFINANCE",  # NBFC / lending
    "TITAN",       # Consumer discretionary
    "ADANIPORTS",  # Ports & logistics (busy announcement feed)
    "HAL",         # Defence PSU
    # Mid caps
    "TRENT",       # Retail
    "DIXON",       # Electronics manufacturing
    "POLYCAB",     # Cables & wires
    "PERSISTENT",  # Mid-size IT
    "DEEPAKNTR",   # Chemicals
]

SECTORS = {
    "RELIANCE": "Energy", "HDFCBANK": "Bank", "TCS": "IT", "BHARTIARTL": "Telecom",
    "ITC": "FMCG", "LT": "Infra", "SUNPHARMA": "Pharma", "MARUTI": "Auto",
    "TATASTEEL": "Metals", "BAJFINANCE": "NBFC", "TITAN": "Consumer",
    "ADANIPORTS": "Ports", "HAL": "Defence", "TRENT": "Retail", "DIXON": "Electronics",
    "POLYCAB": "Cables", "PERSISTENT": "IT", "DEEPAKNTR": "Chemicals",
}

# Companies for the on-demand ("pull") research demo. Can be outside the portfolio.
RESEARCH = ["INFY", "ASIANPAINT", "IRCTC", "KAYNES"]

# --- Push-side alert rules (the user decides what "unusual" means) ------------
ALERTS = {
    "volume_multiple": 2.0,     # alert if volume > 2x its recent average
    "volume_lookback_days": 20, # "recent average" = previous 20 trading days
    "price_move_pct": 5.0,      # alert if close-to-close move is beyond +/-5%
}

# Announcement types that count as "material" by default. The user can change
# this in the app; high-tier items outside it still show, just not as alerts.
ALERT_CATEGORIES = ["results", "M&A", "management_change", "fund_raise",
                    "litigation", "credit_rating", "pledging"]

# --- Fetch settings -------------------------------------------------------------
PRICE_HISTORY_PERIOD = "1y"     # how much EOD history to keep
ANNOUNCEMENT_DAYS = 30          # default window for the first announcements fetch
TRANSCRIPTS_PER_COMPANY = 4     # last 4 quarters, for "promised vs delivered"
REQUEST_PAUSE_SECONDS = 1.0     # be polite to NSE / screener.in

DATA_DIR = Path(__file__).resolve().parent / "data"
