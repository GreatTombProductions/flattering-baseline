#!/usr/bin/env python3
"""Local checks for baseline.py. No network."""

import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import baseline  # noqa: E402


def _rows():
    """Invented days. Not a store."""
    promo = []
    for start, end in ((9, 11), (16, 18), (23, 25)):
        cursor = date(2026, 10, start)
        while cursor <= date(2026, 10, end):
            promo.append(cursor)
            cursor = date.fromordinal(cursor.toordinal() + 1)
    promo_set = set(promo)
    prior = baseline.prior_dates(promo_set)
    year = {baseline.year_ago(day) for day in promo_set}
    prior_year = {baseline.year_ago(day) for day in prior}
    weekdays = baseline.weekday_dates(promo_set)
    rows = []
    for day in promo_set:
        rows.append((day, "main", 856_000))
        rows.append((day, "other", 856_000))
    for day in prior:
        rows.append((day, "main", 800_000))
    for day in year:
        rows.append((day, "main", 856_000))
    for day in prior_year:
        rows.append((day, "main", 1_000_000))
    for day in weekdays:
        rows.append((day, "main", 700_000))
    return rows, promo_set


class RenderTests(unittest.TestCase):
    def test_illustrative_spread(self):
        rows, promo = _rows()
        text = baseline.render(rows, promo, {"main"})
        self.assertIn("prior period\t+7.0%\t8560.00\t8000.00\t9/9\t9/9\t", text)
        self.assertIn("year earlier\t0.0%\t8560.00\t8560.00\t9/9\t9/9\t", text)
        self.assertIn("other stores\t0.0%\t8560.00\t8560.00\t9/9\t9/9\t", text)
        self.assertIn("weekdays\t+22.3%\t8560.00\t7000.00\t9/9\t12/12\t", text)
        self.assertIn("note\tprior period against those same dates a year earlier\t-20.0%\t9/9\t9/9", text)
        self.assertIn("No seasonality control.", text)
        self.assertIn("No chain control.", text)
        self.assertIn("Assumes the other stores are comparable.", text)
        self.assertIn("Isolates a weekend-versus-weekday shift.", text)

    def test_year_ago_feb29(self):
        self.assertEqual(baseline.year_ago(date(2024, 2, 29)), date(2023, 2, 28))

    def test_missing_date_is_not_zero(self):
        _rows_unused, promo = _rows()
        prior = baseline.prior_dates(promo)
        kept = sorted(prior)[0]
        rows = [(day, "main", 100_00) for day in promo]
        rows.append((kept, "main", 50_00))
        text = baseline.render(rows, promo, {"main"})
        line = next(part for part in text.splitlines() if part.startswith("prior period\t"))
        fields = line.split("\t")
        self.assertEqual(fields[1], "+100.0%")
        self.assertEqual(fields[5], f"1/{len(prior)}")

    def test_zero_baseline(self):
        promo = {date(2026, 10, 9)}
        prior = next(iter(baseline.prior_dates(promo)))
        rows = [(date(2026, 10, 9), "main", 100_00), (prior, "main", 0)]
        text = baseline.render(rows, promo, {"main"})
        self.assertIn("prior period\tbaseline is not positive", text)

    def test_weekday_not_separate_when_promo_is_midweek(self):
        promo = {date(2026, 10, 7)}  # Wednesday
        rows = [(date(2026, 10, 7), "main", 100_00)]
        text = baseline.render(rows, promo, {"main"})
        self.assertIn("weekdays\tnot separate\t", text)

    def test_other_stores_absent(self):
        promo = {date(2026, 10, 9)}
        rows = [(date(2026, 10, 9), "main", 100_00)]
        text = baseline.render(rows, promo, {"main"})
        self.assertIn("other stores\tnot in this file\t", text)

    def test_two_stores_require_a_name(self):
        rows = [(date(2026, 10, 9), "main", 1), (date(2026, 10, 9), "other", 1)]
        with self.assertRaises(baseline.DataError):
            baseline._stores_of(rows, None)

    def test_unknown_store(self):
        rows = [(date(2026, 10, 9), "main", 100_00)]
        with self.assertRaises(baseline.DataError):
            baseline.render(rows, {date(2026, 10, 9)}, {"missing"})

    def test_range_order(self):
        with self.assertRaises(baseline.DataError):
            baseline.parse_range("2026-10-11:2026-10-09")


class CommandTests(unittest.TestCase):
    def test_cli_on_written_csv(self):
        rows, promo = _rows()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sales.csv"
            lines = ["date,store,customer,amount"]
            for day, store, cents in sorted(rows):
                lines.append(f"{day.isoformat()},{store},walk-in,{cents / 100:.2f}")
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            ranges = ["--promo", "2026-10-09:2026-10-11", "--promo", "2026-10-16:2026-10-18", "--promo", "2026-10-23:2026-10-25"]
            done = subprocess.run(
                [sys.executable, str(ROOT / "baseline.py"), str(path), *ranges, "--stores", "main"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertIn("prior period\t+7.0%", done.stdout)
            self.assertNotIn("@", done.stdout)

    def test_cli_refuses_two_stores(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sales.csv"
            path.write_text(
                "date,store,amount\n2026-10-09,main,10\n2026-10-09,other,10\n",
                encoding="utf-8",
            )
            done = subprocess.run(
                [sys.executable, str(ROOT / "baseline.py"), str(path), "--promo", "2026-10-09:2026-10-11"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(done.returncode, 2)
            self.assertIn("--stores", done.stderr)

    def test_bad_amount(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sales.csv"
            path.write_text("date,amount\n2026-10-09,nope\n", encoding="utf-8")
            done = subprocess.run(
                [sys.executable, str(ROOT / "baseline.py"), str(path), "--promo", "2026-10-09:2026-10-09"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(done.returncode, 2)
            self.assertIn("line 2", done.stderr)


if __name__ == "__main__":
    unittest.main()
