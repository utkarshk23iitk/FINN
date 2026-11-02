"""Write web/data/feed.json from the data/ cache. Run after fetch_all.py.

    python export_web.py
"""
from pathlib import Path

from finn.export import write_feed

OUT = Path(__file__).resolve().parent / "web" / "data" / "feed.json"

if __name__ == "__main__":
    feed = write_feed(OUT)
    print(f"{len(feed['announcements'])} announcements, {len(feed['companies'])} companies, "
          f"as of {feed['as_of']} -> {OUT}")
