"""Offline tests: no network needed. Run with:  python -m unittest -v"""
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from finn import announcements, fundamentals, prices  # noqa: E402
from finn.classify import classify  # noqa: E402


class TestSignals(unittest.TestCase):
    def setUp(self):
        idx = pd.bdate_range("2026-08-03", periods=40)
        self.df = pd.DataFrame({
            "Open": 100.0, "High": 101.0, "Low": 99.0,
            "Close": np.linspace(100, 104, 40), "Volume": 1_000_000.0,
        }, index=idx)

    def test_quiet_market_has_no_alerts(self):
        self.assertEqual(prices.scan_alerts("X", self.df, last_n_days=10), [])

    def test_volume_spike_and_price_move(self):
        df = self.df.copy()
        df.iloc[-1, df.columns.get_loc("Volume")] = 3_000_000
        df.iloc[-1, df.columns.get_loc("Close")] = df["Close"].iloc[-2] * 1.07
        alerts = prices.scan_alerts("X", df, last_n_days=1)
        self.assertEqual(len(alerts), 1)
        self.assertAlmostEqual(alerts[0]["volume_ratio"], 3.0, places=1)
        self.assertEqual(alerts[0]["reasons"][0], "price +7.0%")

    def test_thresholds_are_configurable(self):
        df = self.df.copy()
        df.iloc[-1, df.columns.get_loc("Volume")] = 1_600_000  # 1.6x
        self.assertEqual(prices.scan_alerts("X", df), [])
        self.assertEqual(len(prices.scan_alerts("X", df, rules={"volume_multiple": 1.5})), 1)


class TestClassifier(unittest.TestCase):
    CASES = [
        ("Outcome of Board Meeting", "approved the unaudited financial results for the quarter", "results", "high"),
        ("Financial Result Updates", "", "results", "high"),
        ("Board Meeting Intimation", "to consider financial results for Q2", "results", "medium"),
        ("Change in Directors/ Key Managerial Personnel", "resignation of Chief Financial Officer (CFO)", "management_change", "high"),
        ("Appointment", "appointment of statutory auditor", "unclassified", "low"),
        ("Resignation", "resignation of statutory auditor citing concerns", "management_change", "high"),
        ("Acquisition", "acquisition of 51% stake in XYZ Pvt Ltd", "M&A", "high"),
        ("Credit Rating", "CRISIL has downgraded the long-term rating", "credit_rating", "high"),
        ("Credit Rating", "ICRA has reaffirmed the rating", "credit_rating", "medium"),
        ("Disclosure under SEBI Takeover Regulations", "acquisition of shares by promoter", "insider_trading", "medium"),
        ("Analysts/Institutional Investor Meet/Con. Call Updates", "transcript of earnings call", "earnings_call", "medium"),
        ("Copy of Newspaper Publication", "", "unclassified", "low"),
        ("Trading Window", "closure of trading window", "unclassified", "low"),
        ("Postal Ballot", "", "postal_ballot", "low"),
        ("Something nobody has seen before", "", "unclassified", "low"),
        # Real TCS filings from NSE (Oct 2026)
        ("Analysts/Institutional Investor Meet/Con. Call Updates",
         "Tata Consultancy Services Limited has informed the Exchange about Schedule of meet",
         "investor_meetings", "low"),
        ("Updates", "Tata Consultancy Services Limited has informed the Exchange regarding 'Press Release - "
         "TCS BaNCS for Treasury marks its entry into Sri Lanka with Indian Bank'.", "press_release", "medium"),
    ]

    def test_cases(self):
        for subject, text, cat, tier in self.CASES:
            with self.subTest(subject=subject, text=text):
                r = classify(subject, text)
                self.assertEqual((r["category"], r["tier"]), (cat, tier), r)

    def test_unknown_goes_to_llm(self):
        self.assertTrue(classify("Something nobody has seen before")["needs_llm"])
        self.assertFalse(classify("Financial Result Updates")["needs_llm"])


class TestAnnouncements(unittest.TestCase):
    RAW = {
        "symbol": "TCS", "desc": "Financial Result Updates",
        "attchmntText": "TCS has informed the Exchange about financial results for the quarter",
        "attchmntFile": "https://nsearchives.nseindia.com/corporate/TCS_1.pdf",
        "sm_name": "Tata Consultancy Services Limited",
        "an_dt": "09-Oct-2026 16:05:11", "sort_date": "2026-10-09 16:05:11", "seq_id": "123",
    }

    def test_normalise(self):
        rec = announcements.normalise(self.RAW, "TCS")
        self.assertEqual(rec["time"], "2026-10-09T16:05:11")
        # Real NSE quirk: missing space in sort_date
        odd = announcements.normalise({**self.RAW, "sort_date": "2026-10-1911:30:07", "an_dt": None}, "TCS")
        self.assertEqual(odd["time"], "2026-10-19T11:30:07")
        self.assertEqual(rec["category"], "results")
        self.assertEqual(rec["company"], "Tata Consultancy Services Limited")

    def test_cache_merge_and_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = config.DATA_DIR
            config.DATA_DIR = Path(tmp)
            try:
                rec = announcements.normalise(self.RAW, "TCS")
                low = announcements.normalise({**self.RAW, "seq_id": "124", "desc": "Trading Window",
                                               "attchmntText": "closure of trading window"}, "TCS")
                announcements.save_merged("TCS", [rec, low])
                merged = announcements.save_merged("TCS", [rec])  # re-fetch: no duplicates
                self.assertEqual(len(merged), 2)
                d = announcements.digest(["TCS"], since=datetime(2026, 10, 1), until=datetime(2026, 10, 31))
                self.assertEqual([a["category"] for a in d], ["results", "unclassified"])
            finally:
                config.DATA_DIR = old


SCREENER_FIXTURE = """
<html><body>
<section id="quarters" class="card card-large">
 <table class="data-table responsive-text-nowrap">
  <thead><tr><th class="text"></th><th>Sep 2025</th><th>Dec 2025</th><th>Mar 2026</th><th>Jun 2026</th><th>Sep 2026</th></tr></thead>
  <tbody>
   <tr><td class="text"><button>Sales&nbsp;<span>+</span></button></td><td>1,000</td><td>1,050</td><td>1,100</td><td>1,150</td><td>1,200</td></tr>
   <tr><td class="text">Operating Profit</td><td>200</td><td>210</td><td>220</td><td>230</td><td>240</td></tr>
   <tr><td class="text">OPM %</td><td>20%</td><td>20%</td><td>20%</td><td>20%</td><td>20%</td></tr>
   <tr><td class="text">Profit before tax</td><td>150</td><td>155</td><td>160</td><td>165</td><td>180</td></tr>
   <tr><td class="text"><button>Net Profit&nbsp;<span>+</span></button></td><td>110</td><td>115</td><td>120</td><td>125</td><td>-20</td></tr>
   <tr><td class="text">Raw PDF</td><td></td><td></td><td></td><td></td><td></td></tr>
  </tbody>
 </table>
</section>
<section id="documents">
 <div class="documents annual-reports flex-column"><h3>Annual reports</h3>
  <ul class="list-links"><li><a href="https://example.com/ar2026.pdf">Financial Year 2026<div class="ink-600 smaller">from bse</div></a></li></ul>
 </div>
 <div class="documents concalls flex-column"><h3>Concalls</h3>
  <ul class="list-links">
   <li><div class="ink-600">Oct 2026</div><a class="concall-link" href="https://example.com/t1.pdf">Transcript</a><a class="concall-link" href="https://example.com/p1.pdf">PPT</a></li>
   <li><div class="ink-600">Jul 2026</div><a class="concall-link" href="https://example.com/p2.pdf">PPT</a></li>
  </ul>
 </div>
</section>
</body></html>
"""


class TestScreenerParsing(unittest.TestCase):
    def test_quarters(self):
        q = fundamentals.parse_quarters(SCREENER_FIXTURE)
        self.assertEqual(q["periods"][-1], "Sep 2026")
        self.assertEqual(q["rows"]["Sales"][0], 1000.0)
        self.assertEqual(q["rows"]["OPM %"][-1], 20.0)
        self.assertNotIn("Raw PDF", q["rows"])

    def test_headline_qoq_yoy(self):
        h = fundamentals.headline_numbers(fundamentals.parse_quarters(SCREENER_FIXTURE))
        self.assertEqual((h["period"], h["vs_qoq"], h["vs_yoy"]), ("Sep 2026", "Jun 2026", "Sep 2025"))
        self.assertEqual(h["metrics"]["Revenue"], {"value": 1200.0, "qoq_pct": 4.3, "yoy_pct": 20.0})
        self.assertEqual(h["metrics"]["PAT"]["qoq_pct"], -116.0)  # loss quarter handled

    def test_documents(self):
        d = fundamentals.parse_documents(SCREENER_FIXTURE)
        self.assertEqual(d["annual_reports"][0]["title"], "Financial Year 2026")
        self.assertEqual(d["concalls"][0], {"period": "Oct 2026", "transcript": "https://example.com/t1.pdf",
                                            "ppt": "https://example.com/p1.pdf", "recording": None})
        self.assertIsNone(d["concalls"][1]["transcript"])


if __name__ == "__main__":
    unittest.main()
