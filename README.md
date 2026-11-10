# Sunspot number pipeline

A small, end-to-end science data pipeline built around the WDC-SILSO sunspot number series from the
Royal Observatory of Belgium. It downloads the raw files, validates every row, recomputes the monthly
means and the 13-month smoothed series from the daily data, checks my numbers against SILSO's
published ones, and archives every run in a versioned, write-once folder. A Streamlit app sits on top
for browsing the data, the quality report and the archive.

I built it in a day as a portfolio piece. The point isn't the sunspots themselves but the plumbing
around them: provenance, validation, reproducibility and being able to say exactly how my numbers
compare with the reference.

## Data and attribution

Source: WDC-SILSO, Royal Observatory of Belgium, Brussels, https://doi.org/10.24414/qnza-ac80

SILSO data is licensed under [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/).
The monthly means derived from daily values, the derived smoothed series and the quality flags are
computed by this pipeline and are not official SILSO products. The app shows this attribution on
every page and it's written into every archive manifest.

Inputs (all semicolon-separated, `-1` = missing, last column `1` = definitive / `0` = provisional):

| File | Columns | Range |
|---|---|---|
| [SN_d_tot_V2.0.csv](https://www.sidc.be/SILSO/DATA/SN_d_tot_V2.0.csv) | year; month; day; decimal date; SN; std dev; n obs; definitive | 1818-01-01 onwards |
| [SN_m_tot_V2.0.csv](https://www.sidc.be/SILSO/DATA/SN_m_tot_V2.0.csv) | year; month; decimal date; SN; std dev; n obs; definitive | 1749-01 onwards |
| [SN_ms_tot_V2.0.csv](https://www.sidc.be/SILSO/DATA/SN_ms_tot_V2.0.csv) | same as monthly; first and last 6 months are `-1` | 1749-01 onwards |

The format details come from SILSO's own description pages (`/SILSO/infosndtot`, `infosnmtot`,
`infosnmstot`), and the code only accepts files that match them.

## Running it

Windows / PowerShell, Python 3.11+:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt

python -m sunspot_pipeline run          # download, validate, process, reconcile, archive
python -m sunspot_pipeline run          # again: inputs unchanged -> logged as "skipped"
python -m sunspot_pipeline list         # archived runs
python -m sunspot_pipeline verify       # re-hash the latest archived run against its manifest

streamlit run streamlit_app.py          # http://localhost:8501

pytest                                  # tests
ruff check . ; ruff format --check .    # lint
```

Other options: `run --force` archives a new run even when the inputs haven't changed, and
`run --from-dir <folder>` reads the three CSVs from a local folder instead of downloading them.
The `SUNSPOT_HOME` environment variable moves all output somewhere else (the Docker image uses `/data`).

If the app starts and finds no archived run (a fresh clone, or a new Streamlit Cloud container), it
runs the pipeline once by itself before showing anything.

### Docker

```powershell
docker build -t sunspot-pipeline .
docker run -p 8501:8501 -v sunspot-data:/data sunspot-pipeline
```

## What happens in a run

```
fetch 3 files ──► SHA-256 ──► same inputs + same pipeline version already archived? ──► yes: log "skipped", stop
                                     │ no
                                     ▼
                      raw snapshot  data/raw/<run_id>/   (bytes exactly as downloaded)
                                     ▼
                      validate  ──► per-row flags + quality report  (layout change = run fails, nothing archived)
                                     ▼
                      process   ──► monthly means from daily, 13-month smoothed
                                     ▼
                      reconcile ──► derived vs published, per month and summarised
                                     ▼
                      archive   ──► archive/v<version>/<run_id>/  (Parquet + CSV + JSON + manifest)
```

Every invocation, whether completed, skipped or failed, also writes a record to `runs/<run_id>.json`.
The run ID is the UTC start time plus the first 8 hex digits of a hash over the three input hashes,
e.g. `20261110T204328Z-5ecef8eb`.

### Code layout

```
sunspot_pipeline/
  config.py      sources, file layouts, tolerance, paths, attribution text
  ingest.py      fetch (HTTP or local folder), hashing, raw snapshot, "already done?" lookup
  validate.py    parsing, row flags, quality report
  process.py     monthly means, tapered 13-month smoothing, half-up rounding
  reconcile.py   derived vs published comparison
  archive.py     write-once archive, listing, checksum verification
  pipeline.py    the orchestration above
  __main__.py    CLI
app/             Streamlit pages (Overview, Data quality, Explorer, Runs & archive)
streamlit_app.py entry point
tests/           pytest, with small real extracts of the SILSO files in tests/fixtures
```

## Validation

Nothing gets dropped. Every input row ends up in the archived `*_flagged` tables with boolean flag
columns plus a readable `quality_flags` string:

| Flag | Severity | Meaning |
|---|---|---|
| `schema` | error | wrong number of fields, non-numeric value, or non-integer where an integer is expected |
| `invalid_date` | error | year/month/day isn't a real date |
| `duplicate` | error | more than one row for the same date (all copies flagged) |
| `out_of_range` | error | SN negative (other than `-1`) or above 1000, negative std/n_obs, definitive not 0/1, year outside 1700..next year |
| `missing` | info / warning | value is `-1`. For daily data this is expected (sparse early observations); for the smoothed file the first and last 6 months are expected, anything else is a warning |
| `decimal_date` | warning | the decimal date column doesn't fall inside the row's own day/month |
| `after_gap` | warning | first row after a run of missing calendar days/months |
| `no_obs` | info | a value is present but n_obs is 0 (February 1824, which SILSO says Wolf interpolated) |
| `provisional` | info | definitive = 0 |

There are also file-level checks: rows out of date order, a definitive row appearing after
provisional ones, and the monthly and smoothed files covering different months. Rows with any of the
error flags, or `missing`, are excluded from the derived values. The only thing that stops a run is the
file layout itself changing (the most common field count isn't the expected one). That run is
recorded as failed, the raw snapshot is kept for inspection, and nothing is archived.

## Processing

**Monthly means** are the arithmetic mean of the usable daily values in each calendar month. I keep
the number of days actually used next to each value and flag partial months and months with no data.

**13-month smoothing** follows SILSO's definition: a "tapered boxcar" centred on the month, weight 1
for the inner 11 months and 0.5 for the months at -6 and +6, divided by 12. The first and last 6
months have no value. If any month in the window is missing, the smoothed value is missing too. I
don't renormalise over fewer months, because that would quietly give a different statistic.

## Reconciliation results

From the live run `20261110T204328Z-5ecef8eb` (SILSO files last modified 2026-11-01):

| Comparison | Months compared | Exact | Within 0.05 | Rounding ties | Mismatches | Max abs diff |
|---|---|---|---|---|---|---|
| Monthly mean from daily vs SILSO monthly | 2505 (1818-01 to 2026-10) | 2505 | 2505 | 0 | 0 | 0.0 |
| My smoothed series vs SILSO smoothed | 2481 (1818-07 to 2026-04) | 2453 | 2453 | 28 | 0 | 0.1 |
| Smoothing formula applied to SILSO's monthly file | 3322 (1749-07 to 2026-04) | 3288 | 3288 | 34 | 0 | 0.1 |

- February 1824 can't be derived because there are no daily observations that month. SILSO's
  value (18.0, n_obs = 0) was interpolated by Wolf. Because a smoothed value needs all 13 months,
  that one gap also blanks 13 smoothed months (1823-08 to 1824-08).
- Monthly means before 1818 can't be derived because there is no daily file for those years.
- Every one of the 28 (and 34) smoothed differences is an exact half-way case. For example, for
  1958-02 the unrounded smoothed value is exactly 284.55; rounding half-up gives 284.6, SILSO
  publishes 284.5. Of the 130 exact ties in the formula check, SILSO rounded 96 up and 34 down, so
  their rounding is most likely subject to floating-point noise. I tried several summation orders and
  rounding methods and none of them reproduces SILSO's choice on all ties, so I report these
  separately instead of chasing them.

## Design decisions

These are the choices I'd expect to be asked about, and why I made them.

1. **Round half-up before comparing, tolerance 0.05.** SILSO publishes one decimal. Python and numpy
   round half-to-even, which made 15 monthly means look wrong by 0.1 (129.25 → 129.2 instead of 129.3).
   Rounding the way SILSO does and then asking for agreement within half the last published digit
   means any failure is a real discrepancy, not a rounding artefact.
2. **Rounding ties are a separate category, not a pass and not a failure.** A 0.1 difference only
   counts as a "rounding tie" when the unrounded derived value is exactly on a .x5 boundary. Anything
   else at 0.1 is still a mismatch (there's a test for that). This keeps the tolerance strict but
   doesn't paint the dashboard red for something I can explain.
3. **Smooth the rounded monthly means, like SILSO does.** Smoothing my rounded monthly values leaves
   only the 28 ties. Smoothing the unrounded means gives 171 months off by 0.1, which tells me SILSO
   smooths its published 1-decimal monthly values.
4. **Check the smoothing formula on its own.** The third comparison applies my smoothing to SILSO's
   own monthly file. That separates "is the formula right?" from "are my monthly means right?" and
   also covers 1749–1817, where there's no daily data.
5. **Flag, never drop.** Validation adds columns, it doesn't filter. Derived values skip flagged rows,
   but the archived tables keep every input row, so anyone can see what was left out and why.
   Only a layout change is fatal.
6. **Skip key = input hashes + pipeline version.** If the files haven't changed and the code version
   hasn't either, a rerun would only produce a duplicate. Bumping `__version__` (which I do whenever
   the processing logic changes) forces a fresh run into a new `archive/v<version>/` folder. I hash
   the content rather than trusting ETag/Last-Modified. Those headers are recorded in the manifest, but
   they're the server's claim, not the data.
7. **Write-once archive via staging + rename.** Outputs are written to a hidden `.staging-<run_id>`
   folder, hashed, and only then renamed into place. If the target exists, the run fails with
   `ArchiveExistsError` instead of overwriting anything. A crash halfway leaves no folder that looks
   complete.
8. **Run ID = UTC timestamp + input hash prefix.** It sorts by time, it's unique across machines
   without a central counter, and you can tell at a glance which runs share the same inputs.
9. **Parquet and CSV.** Parquet keeps types and is what the app reads. CSV is there so anyone can
   open the data without Python.
10. **The app only reads the archive.** It never recalculates anything itself; it shows exactly what
    a run produced. On a fresh deployment it runs the pipeline once, so nothing data-related needs to
    be committed to git.
11. **Fixtures are real.** The test data is verbatim line extracts of the SILSO files (1823–1825 for
    Feb 1824 and a half-up case, 2024–2026 for provisional values). Tests that need broken input make
    the change visibly in the test code (duplicate a line, delete one, overwrite one field).
12. **Flat package, no install step.** `sunspot_pipeline/` sits at the repo root so Streamlit Cloud,
    Docker and pytest can all import it without `pip install -e .`.

## Tests and CI

`pytest` runs 48 tests:

- validation: real files come out clean; injected duplicates, gaps, out-of-range values, malformed rows,
  out-of-order rows and wrong decimal dates are flagged and kept; layout changes and empty files are fatal
- smoothing: weights, edge behaviour, spike response, NaN propagation, half-up rounding, and
  reproducing SILSO's smoothed values from SILSO's monthly extract
- monthly means from the daily extract match SILSO's monthly file exactly (Feb 1824 correctly missing)
- ingest: URL/time/SHA-256 recorded, raw snapshot byte-identical, unchanged input skipped,
  changed input re-run, failed validation and download errors handled
- archive: no overwrite (original files byte-identical after the refused write), versions side by side,
  no partial run after a mid-write failure, tamper detection
- app: each of the four pages renders without errors on a fixture run (Streamlit's `AppTest`)

GitHub Actions runs ruff (lint + format check) and pytest on Python 3.11 and 3.12, then builds the
Docker image.

## Known limitations

- It's a single-user, file-based design. Two pipeline runs started in the same second with the same
  inputs would collide on the run ID (the second fails safely, it doesn't overwrite).
- The archive is "write-once" by convention and checksums, not by filesystem permissions. `verify`
  will detect changes but nothing stops them.
- The app on Streamlit Community Cloud has an ephemeral disk, so its archive starts over whenever the
  container restarts. A real deployment would put `SUNSPOT_HOME` on persistent storage or object storage.
- No scheduler. Runs happen from the CLI or the app's "Run pipeline" button. A cron job or a scheduled
  GitHub Action calling `python -m sunspot_pipeline run` would be the next step.
- Provisional values get revised by SILSO. Each revision changes the input hash and produces a new run,
  but I don't yet diff consecutive runs to show what changed.
- I can't reproduce SILSO's choice on exact rounding ties; they're reported, not resolved.

## Licence

Code: MIT (see `LICENSE`). Data: CC BY-NC 4.0, WDC-SILSO, Royal Observatory of Belgium.
