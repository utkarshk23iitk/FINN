"""Fetch and cache all FINN data.

Examples:
    python fetch_all.py                      # everything, default settings
    python fetch_all.py --only prices
    python fetch_all.py --only announcements --days 7
    python fetch_all.py --only fundamentals --symbols INFY TCS
    python fetch_all.py --only results       # results cards (needs GEMINI_API_KEY)
    python fetch_all.py --summary            # just print what's cached
"""
import argparse
from datetime import datetime, timedelta

import config
from finn import announcements, fundamentals, prices, results


def print_summary(portfolio, hours: int = 24 * 7) -> None:
    print("\n=== Price/volume alerts (last 5 trading days) ===")
    found = False
    for sym in portfolio:
        df = prices.load_prices(sym)
        if df.empty:
            continue
        for a in prices.scan_alerts(sym, df, last_n_days=5):
            found = True
            print(f"  {a['date']}  {sym:<12} close {a['close']:>10,.2f}  {', '.join(a['reasons'])}")
    if not found:
        print("  none (or no price data cached yet)")

    since = datetime.now() - timedelta(hours=hours)
    items = announcements.digest(portfolio, since)
    print(f"\n=== Announcement digest, last {hours // 24} days: {len(items)} items ===")
    for tier in ("high", "medium", "low"):
        tier_items = [a for a in items if a["tier"] == tier]
        print(f"\n  [{tier.upper()}] {len(tier_items)} items")
        for a in tier_items[: 8 if tier != "low" else 3]:
            flag = " (check w/ LLM)" if a["needs_llm"] else ""
            print(f"    {a['time'][:16]}  {a['symbol']:<11} {a['category']:<18} {a['subject'][:60]}{flag}")


def main() -> None:
    p = argparse.ArgumentParser(description="Fetch FINN data into ./data")
    p.add_argument("--only", choices=["prices", "announcements", "fundamentals", "results"])
    p.add_argument("--symbols", nargs="+", help="override the companies from config.py")
    p.add_argument("--days", type=int, default=config.ANNOUNCEMENT_DAYS,
                   help="announcement window in days")
    p.add_argument("--transcripts", type=int, default=config.TRANSCRIPTS_PER_COMPANY,
                   help="transcripts per company (0 to skip downloads)")
    p.add_argument("--summary", action="store_true", help="only print the cached summary")
    args = p.parse_args()

    portfolio = args.symbols or config.PORTFOLIO
    research = args.symbols or config.RESEARCH

    if not args.summary:
        if args.only in (None, "prices"):
            print(f"Prices ({len(portfolio)} companies)...")
            prices.fetch_all_prices(portfolio)
        if args.only in (None, "announcements"):
            print(f"\nNSE announcements, last {args.days} days...")
            announcements.fetch_all_announcements(portfolio, args.days)
        if args.only in (None, "results"):
            print(f"\nResults cards from the latest results filings...")
            results.extract_latest(portfolio)
        if args.only in (None, "fundamentals"):
            print(f"\nscreener.in fundamentals ({len(research)} companies)...")
            fundamentals.fetch_all_fundamentals(research, args.transcripts)

    print_summary(portfolio, hours=24 * args.days if args.summary else 24 * 7)
    print(f"\nData saved in: {config.DATA_DIR}")


if __name__ == "__main__":
    main()
