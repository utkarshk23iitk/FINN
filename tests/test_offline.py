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
        # Real RELIANCE filing (Nov 2026): a transcript that names the results it discusses
        ("Analysts/Institutional Investor Meet/Con. Call Updates",
         "Transcript of the discussion on the Unaudited Financial Results (Consolidated and Standalone) "
         "of the Company for the quarter and half year ended September 30, 2026", "earnings_call", "medium"),
    ]

    def test_cases(self):
        for subject, text, cat, tier in self.CASES:
            with self.subTest(subject=subject, text=text):
                r = classify(subject, text)
                self.assertEqual((r["category"], r["tier"]), (cat, tier), r)

    def test_headline_drops_nse_boilerplate(self):
        from finn.export import clean_headline
        self.assertEqual(clean_headline("Amalgamation/Merger",
                         "ITC Limited has informed the Exchange about Amalgamation/Merger"), "Amalgamation/Merger")
        self.assertEqual(clean_headline("Outcome of Board Meeting",
                         "ITC Limited has submitted to the Exchange, the financial results for the period ended "
                         "September 30, 2026."), "Financial results for the period ended September 30, 2026")
        self.assertEqual(clean_headline("Copy of Newspaper Publication", ""), "Copy of Newspaper Publication")

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


class TestTranscriptPick(unittest.TestCase):
    def test_duplicate_label_does_not_use_a_slot(self):
        # Real screener.in list for TCS (Oct 2026): "Jul 2026" appears twice,
        # the second link being the Jul 2025 call. Jan 2026 must still be picked.
        calls = [{"period": p, "transcript": u} for p, u in [
            ("Oct 2026", "a.pdf"), ("Jul 2026", "b.pdf"), ("Jul 2026", "tcs-q1-2025-26.pdf"),
            ("Apr 2026", "c.pdf"), ("Jan 2026", "d.pdf"), ("Oct 2025", None)]]
        picked = fundamentals.pick_transcripts(calls)
        self.assertEqual([c["period"] for c in picked][:4], ["Oct 2026", "Jul 2026", "Apr 2026", "Jan 2026"])
        self.assertEqual(picked[1]["transcript"], "b.pdf")

class TestResearch(unittest.TestCase):
    def test_call_month_maps_to_the_quarter_it_covers(self):
        from finn.research import call_quarter
        self.assertEqual(call_quarter("Oct 2026"), ("Q2 FY27", "2026-09"))
        self.assertEqual(call_quarter("Jan 2026"), ("Q3 FY26", "2025-12"))
        self.assertEqual(call_quarter("May 2026"), ("Q4 FY26", "2026-03"))
        self.assertEqual(call_quarter("Aug 2026"), ("Q1 FY27", "2026-06"))

    def test_fiscal_totals_use_april_to_march(self):
        from finn.research import fiscal_totals
        periods = ["Jun 2025", "Sep 2025", "Dec 2025", "Mar 2026", "Jun 2026", "Sep 2026"]
        t = fiscal_totals(periods, [1160, 1146, 1449, 1460, 1370, 1400])  # IRCTC sales, ₹ cr
        self.assertEqual(t, {"FY26": 5215, "H1 FY27": 2770})

    def test_numbers_decide_numeric_promises(self):
        from finn.research import settle
        base = {"verdict": "delivered", "direction": "at_least", "unit": "%"}
        # Real IRCTC case: "15% sustainable growth this year", FY26 sales +11.5%.
        # Flash-Lite said delivered; the numbers say missed.
        p = settle({**base, "target_low": 15, "actual": 11.5})
        self.assertEqual((p["verdict"], p["model_verdict"]), ("missed", "delivered"))
        self.assertEqual(settle({**base, "target_low": 15, "actual": 14.2})["verdict"], "partly")
        # Real KAYNES case: "cross about INR4,000 crores minimum for FY26", actual 3,626.
        k = settle({**base, "unit": "₹ crore", "target_low": 4000, "actual": 3626.4, "verdict": "missed"})
        self.assertEqual(k["verdict"], "partly")
        band = {**base, "direction": "within", "target_low": 18, "target_high": 20}
        self.assertEqual(settle({**band, "actual": 19.1})["verdict"], "delivered")
        self.assertEqual(settle({**band, "actual": 16.0})["verdict"], "missed")
        # Real ASIANPAINT case: "mid-single-digit value growth", one edge given, actual 4.9%.
        self.assertEqual(settle({**base, "direction": "within", "target_low": 4, "actual": 4.9})["verdict"], "delivered")
        # Timing calls stay with the model.
        self.assertEqual(settle({**base, "verdict": "pending", "target_low": 15, "actual": 2})["verdict"], "pending")

    def test_quote_must_be_in_the_transcript(self):
        from finn.research import _squash, quote_found
        # Real TCS transcript text: PDF breaks lines and uses ligatures.
        source = _squash("Our disciplined approach to margin manage-\nment remains un changed. "
                         "As growth improves, we expect to beneﬁt from enhanced scale")
        self.assertTrue(quote_found("we expect to benefit from enhanced scale", source))
        self.assertFalse(quote_found("we expect margins to expand by 100 bps", source))

    def test_trim_keeps_management_numbers_and_drops_moderator(self):
        from finn.research import trim
        text = ("\nModerator: Ladies and gentlemen, welcome to the call, we expect it to run 60 minutes.\n"
                "Samir Seksaria: Our operating margins remained stable sequentially at 24%. Thank you.\n")
        out = trim(text)
        self.assertIn("Samir Seksaria: Our operating margins remained stable sequentially at 24%.", out)
        self.assertNotIn("Ladies", out)

class TestResultsCard(unittest.TestCase):
    # Real ITC consolidated statement, Q2 FY27 (filed 2 Nov 2026). The filing
    # lists this quarter, then last year, then last quarter.
    def ext(self, pat_last_year=5186.55):
        q = lambda d, rev, oi, exp, fin, dep, pbt, tax, pat: dict(
            end_date=d, months=3, revenue=rev, other_income=oi, total_expenses=exp,
            finance_costs=fin, depreciation=dep, pbt=pbt, tax=tax, pat=pat)
        return {"basis": "consolidated", "unit": "crore", "lender": False, "periods": [
            q("2026-09-30", 30578.40, 507.36, 25462.44, 38.27, 490.60, 5694.62, 1465.29, 4229.33),
            q("2025-09-30", 21255.86, 584.40, 15016.02, 20.05, 434.80, 6978.68, 1792.13, pat_last_year),
            q("2026-06-30", 29523.30, 655.71, 24809.95, 39.78, 427.73, 5860.85, 1352.06, 4508.79),
            {"end_date": "2026-09-30", "months": 6, "revenue": 60101.7, "pbt": 11555.47, "pat": 8738.12},
        ]}

    def test_columns_mapped_by_date_and_ebitda_computed(self):
        from finn.results import build_card
        c = build_card(self.ext())
        self.assertTrue(c["ok"], c["issues"])
        self.assertEqual((c["qoq_end"], c["yoy_end"]), ("2026-06-30", "2025-09-30"))
        rows = {r["metric"]: r for r in c["rows"]}
        # EBITDA = revenue - (total expenses - finance costs - depreciation)
        self.assertAlmostEqual(rows["ebitda"]["value"], 30578.40 - (25462.44 - 38.27 - 490.60), places=1)
        self.assertEqual(rows["revenue"]["qoq"], 3.6)
        self.assertEqual(rows["pat"]["yoy"], -18.5)

    def test_misread_digit_is_caught(self):
        # OCR printed "51B6.55"; a model once returned 5156.55. PBT - tax says 5186.55.
        from finn.results import build_card
        c = build_card(self.ext(pat_last_year=5156.55))
        self.assertFalse(c["ok"])
        self.assertIn("PBT − tax ≠ PAT for last year", c["issues"])

    def test_missing_comparison_is_not_ok(self):
        from finn.results import build_card
        e = self.ext()
        e["periods"] = [p for p in e["periods"] if p["end_date"] != "2026-06-30"]
        c = build_card(e)
        self.assertFalse(c["ok"])
        self.assertIn("no last-quarter column", c["missing"])
        self.assertEqual(c["issues"], [])  # missing is not the same as wrong

    def test_pat_printed_before_associates(self):
        # Real RELIANCE layout (Q2 FY27): "Profit After Tax 29,250", then
        # associates 300, then the final 29,550. The final line is PAT.
        from finn.results import build_card
        q = lambda d, pbt, tax, assoc: dict(end_date=d, months=3, revenue=100000.0, pbt=pbt, tax=tax,
                                            pat=pbt - tax, associates_after_tax=assoc)
        c = build_card({"basis": "consolidated", "unit": "crore", "lender": True, "periods": [
            q("2026-09-30", 38613.0, 9363.0, 300.0), q("2026-06-30", 30630.0, 7629.0, 195.0),
            q("2025-09-30", 29124.0, 6978.0, -54.0)]})
        self.assertEqual(c["issues"], [])
        self.assertEqual(c["rows"][3]["value"], 29550.0)


    def test_unit_is_read_from_the_statement(self):
        from finn.results import build_card, detect_unit
        self.assertEqual(detect_unit("(₹ in million, except per share data)"), "million")  # Maruti
        self.assertEqual(detect_unit("(' in Crores)"), "crore")  # ITC, OCR'd rupee sign
        self.assertEqual(detect_unit("(Rs. in Lakhs)"), "lakh")
        c = build_card({**self.ext(), "unit": "crore"}, unit="million")  # the printed unit wins
        self.assertAlmostEqual(c["rows"][0]["value"], 3057.8, places=1)

    def test_associates_added_after_tax(self):
        from finn.results import build_card
        e = self.ext()
        for p in e["periods"][:3]:
            p["associates_after_tax"] = 100.0
            p["pat"] = round(p["pbt"] - p["tax"] + 100.0, 2)
        self.assertTrue(build_card(e)["ok"])

    def test_lender_pre_provision_profit(self):
        from finn.results import build_card
        q = lambda d, rev, pbt, tax, imp: dict(end_date=d, months=3, revenue=rev, pbt=pbt, tax=tax,
                                               pat=round(pbt - tax, 2), impairment=imp)
        c = build_card({"basis": "consolidated", "unit": "crore", "lender": True, "periods": [
            q("2026-09-30", 24575.8, 8500.0, 2133.4, 2100.0),
            q("2026-06-30", 23160.0, 8100.0, 2020.0, 2000.0),
            q("2025-09-30", 20000.0, 6600.0, 1650.0, 1500.0)]})
        self.assertTrue(c["ok"], c["issues"])
        self.assertEqual(c["rows"][1]["value"], 10600.0)  # PBT + impairment


if __name__ == "__main__":
    unittest.main()
