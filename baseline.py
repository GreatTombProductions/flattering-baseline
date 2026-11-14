#!/usr/bin/env python3
"""Four baselines for one promo window, from a register export you already have.

Nothing is uploaded. The four numbers are the result. None of them is the lift.
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

DATE_KEYS = ("date", "day", "business date")
STORE_KEYS = ("store", "store id", "location")
AMOUNT_KEYS = ("amount", "total", "total amount", "paid", "sales", "customer paid")

CANNOT = {
    "prior period": (
        "No seasonality control. A soft stretch before the promo makes an ordinary week look like a lift."
    ),
    "year earlier": (
        "No chain control. The whole street may have moved, and these calendar dates can fall on different weekdays."
    ),
    "other stores": (
        "Assumes the other stores are comparable. They can differ in size, hours, or neighborhood."
    ),
    "weekdays": (
        "Isolates a weekend-versus-weekday shift. Weekends differ from weekdays for reasons that have nothing to do with the promo."
    ),
}


class DataError(Exception):
    pass


def _norm(label: str) -> str:
    return label.strip().lower().replace("_", " ").replace("-", " ")


def year_ago(day: date) -> date:
    try:
        return day.replace(year=day.year - 1)
    except ValueError:
        return day.replace(year=day.year - 1, day=28)


def parse_range(text: str) -> list[date]:
    try:
        start_s, end_s = text.split(":")
        start, end = date.fromisoformat(start_s), date.fromisoformat(end_s)
    except ValueError as exc:
        raise DataError(f"promo range must be YYYY-MM-DD:YYYY-MM-DD, not {text!r}") from exc
    if end < start:
        raise DataError(f"promo range ends before it starts: {text}")
    if (end - start).days > 366:
        raise DataError(f"promo range longer than a year is refused: {text}")
    days = []
    cursor = start
    while cursor <= end:
        days.append(cursor)
        cursor += timedelta(days=1)
    return days


def prior_dates(promo: set[date]) -> set[date]:
    weeks = sorted({day - timedelta(days=day.weekday()) for day in promo})
    weekdays = {day.weekday() for day in promo}
    first = weeks[0]
    found = set()
    for back in range(1, len(weeks) + 1):
        monday = first - timedelta(weeks=back)
        for weekday in weekdays:
            found.add(monday + timedelta(days=weekday))
    return found


def weekday_dates(promo: set[date]) -> set[date]:
    weeks = {day - timedelta(days=day.weekday()) for day in promo}
    found = set()
    for monday in weeks:
        for offset in range(4):
            found.add(monday + timedelta(days=offset))
    return found


def _pick(header: list[str], keys: tuple[str, ...]) -> int | None:
    normed = [_norm(cell) for cell in header]
    for key in keys:
        if key in normed:
            return normed.index(key)
    return None


def _cents(text: str) -> int:
    cleaned = text.strip().replace("$", "").replace(",", "")
    if cleaned == "":
        raise ValueError("blank")
    amount = Decimal(cleaned)
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def load_csv(path: str) -> list[tuple[date, str, int]]:
    try:
        handle = open(path, newline="", encoding="utf-8-sig")
    except OSError as exc:
        raise DataError(f"cannot read {path}: {exc.strerror}") from exc
    rows: list[tuple[date, str, int]] = []
    with handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration as exc:
            raise DataError(f"{path} is empty") from exc
        date_at = _pick(header, DATE_KEYS)
        amount_at = _pick(header, AMOUNT_KEYS)
        store_at = _pick(header, STORE_KEYS)
        if date_at is None or amount_at is None:
            raise DataError(f"{path} needs a header with a date and an amount")
        for number, cells in enumerate(reader, start=2):
            if not cells or all(not cell.strip() for cell in cells):
                continue
            try:
                day = date.fromisoformat(cells[date_at].strip()[:10])
                cents = _cents(cells[amount_at])
            except (ValueError, IndexError, ArithmeticError) as exc:
                raise DataError(f"{path} line {number}: need a YYYY-MM-DD date and a numeric amount") from exc
            store = cells[store_at].strip() if store_at is not None and store_at < len(cells) else ""
            rows.append((day, store, cents))
    if not rows:
        raise DataError(f"{path} has a header and no rows")
    return rows


def _covered(rows: list[tuple[date, str, int]], days: set[date], stores: set[str] | None) -> tuple[int, int]:
    total = 0
    present: set[date] = set()
    for day, store, cents in rows:
        if day not in days:
            continue
        if stores is not None and store not in stores:
            continue
        total += cents
        present.add(day)
    return total, len(present)


def _lift(promo_cents: int, promo_days: int, base_cents: int, base_days: int) -> str:
    if promo_days == 0 or base_days == 0:
        return "not in this file"
    if base_cents <= 0:
        return "baseline is not positive"
    promo_per = Decimal(promo_cents) / Decimal(promo_days)
    base_per = Decimal(base_cents) / Decimal(base_days)
    pct = ((promo_per - base_per) / base_per * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    if pct > 0:
        return f"+{pct}%"
    return f"{pct}%"


def _per_day(cents: int, days: int) -> str:
    if days == 0:
        return ""
    amount = (Decimal(cents) / Decimal(days) / Decimal(100)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{amount:.2f}"


def render(rows: list[tuple[date, str, int]], promo: set[date], stores: set[str]) -> str:
    known = {store for _, store, _ in rows}
    missing = sorted(store for store in stores if store not in known)
    if missing:
        raise DataError("store not in the file: " + ", ".join(missing))
    promo_cents, promo_days = _covered(rows, promo, stores)
    if promo_days == 0:
        raise DataError("no rows on the promo dates for the named stores")
    prior = prior_dates(promo)
    year = {year_ago(day) for day in promo}
    others = {store for store in known if store not in stores}
    weekdays = weekday_dates(promo)
    lines = [
        "# per day uses dates that appear in the file. A missing date is not zero.",
        "# a closed day counts only if you include it with amount 0.",
        "comparison\tlift\tpromo_per_day\tbaseline_per_day\tpromo_coverage\tbaseline_coverage\tcannot_rule_out",
    ]

    def add(name: str, base_days_set: set[date], base_stores: set[str] | None, lift: str | None = None) -> tuple[int, int]:
        base_cents, base_n = _covered(rows, base_days_set, base_stores)
        shown = lift if lift is not None else _lift(promo_cents, promo_days, base_cents, base_n)
        lines.append(
            "\t".join(
                [
                    name,
                    shown,
                    _per_day(promo_cents, promo_days),
                    _per_day(base_cents, base_n),
                    f"{promo_days}/{len(promo)}",
                    f"{base_n}/{len(base_days_set)}",
                    CANNOT[name],
                ]
            )
        )
        return base_cents, base_n

    add("prior period", prior, stores)
    add("year earlier", year, stores)
    if not others:
        add("other stores", promo, others, lift="not in this file")
    else:
        add("other stores", promo, others)
    if any(day.weekday() < 4 for day in promo):
        add("weekdays", weekdays, stores, lift="not separate")
    else:
        add("weekdays", weekdays, stores)

    prior_cents, prior_n = _covered(rows, prior, stores)
    prior_year = {year_ago(day) for day in prior}
    year_cents, year_n = _covered(rows, prior_year, stores)
    moved = _lift(prior_cents, prior_n, year_cents, year_n)
    if moved not in {"not in this file", "baseline is not positive"}:
        lines.append(
            "note\tprior period against those same dates a year earlier\t"
            f"{moved}\t{prior_n}/{len(prior)}\t{year_n}/{len(prior_year)}"
        )
    return "\n".join(lines) + "\n"


def _stores_of(rows: list[tuple[date, str, int]], named: str | None) -> set[str]:
    present = {store for _, store, _ in rows}
    if named is None:
        if len(present) > 1:
            raise DataError("name the stores that ran the promo with --stores")
        return present
    chosen = {part.strip() for part in named.split(",")}
    if "" in chosen:
        raise DataError("--stores has an empty name")
    return chosen


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Four baselines for one promo window.")
    parser.add_argument("csv")
    parser.add_argument("--promo", action="append", required=True, help="YYYY-MM-DD:YYYY-MM-DD, repeatable")
    parser.add_argument("--stores", help="comma-separated stores that ran the promo")
    args = parser.parse_args(argv)
    try:
        promo: set[date] = set()
        for text in args.promo:
            promo.update(parse_range(text))
        if len(promo) > 400:
            raise DataError("more than 400 promo dates is refused")
        rows = load_csv(args.csv)
        text = render(rows, promo, _stores_of(rows, args.stores))
    except DataError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
