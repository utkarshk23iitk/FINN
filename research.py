"""Promised vs delivered for any NSE ticker on screener.in.

    python research.py TITAN            # fetch transcripts, analyse, cache
    python research.py TITAN --refresh  # re-run the analysis step
    python export_web.py                # then publish it to the web app
"""
import argparse

from finn import research

if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("symbols", nargs="+")
    p.add_argument("--refresh", action="store_true", help="re-run the review (per-call extracts stay cached)")
    args = p.parse_args()
    for sym in args.symbols:
        r = research.review(sym.upper().removesuffix(".NS"), refresh=args.refresh)
        c = r["counts"]
        print(f"{r['symbol']}: {c['delivered']} delivered, {c['partly']} partly, {c['missed']} missed, "
              f"{c['pending']} pending, {c['dropped']} dropped\n  {r['headline']}")
