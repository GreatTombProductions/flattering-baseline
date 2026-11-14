# The Flattering Baseline

The same promo weekends can be up against the weeks before and flat against last year. This is a one-page note of that, plus a command you run on a register export you already have.

Nothing here logs into a vendor or keeps your file.

## Run it

```bash
python3 baseline.py illustrative.csv \
  --promo 2026-10-09:2026-10-11 \
  --promo 2026-10-16:2026-10-18 \
  --promo 2026-10-23:2026-10-25 \
  --stores main
```

`illustrative.csv` is an invented file at `example/illustrative.csv`. It is not a store. Name your own file, and name the stores that ran the promo.

You get four lifts — prior period, the same calendar dates a year earlier, other stores in the file, and the Monday–Thursday side of the promo weeks — plus what each comparison cannot rule out. A missing date is not treated as zero.

The checks that ship with the command talk only to files on your own machine:

```bash
python3 tests/test_baseline.py
```
