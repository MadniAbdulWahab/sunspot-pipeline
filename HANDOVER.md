# Handover

Status as of 2026-11-10.

## What was built

- `sunspot_pipeline/`: a Python package that downloads the three WDC-SILSO sunspot files (daily,
  monthly, 13-month smoothed), records URL / fetch time / SHA-256 / HTTP headers in a run record,
  keeps a byte-exact raw snapshot, and skips the run when the inputs (and pipeline version) are
  unchanged. It validates every row (schema, dates, duplicates, gaps, missing values, ranges, decimal
  dates, provisional flags) without dropping anything, derives monthly means from the daily data and
  the 13-month tapered smoothed series, reconciles both against SILSO's published series, and archives
  Parquet + CSV + JSON reports + manifest under `archive/v<version>/<run_id>/`, write-once.
- CLI: `python -m sunspot_pipeline run | list | verify`.
- Streamlit app (`streamlit_app.py`) with four pages: Overview, Data quality, Explorer (Plotly, date
  filter, derived-minus-published plot), Runs & archive (run log, manifests, checksums, downloads, a
  "Run pipeline" button).
- 48 pytest tests, ruff config, GitHub Actions workflow (lint + tests on 3.11 and 3.12, Docker build),
  Dockerfile, README with the design decisions.
- SILSO attribution and the CC BY-NC 4.0 licence are in the README, on every app page, in every
  archive manifest and next to the test fixtures.

## Commands and results

Environment: Windows 11, Python 3.11.8, pandas 3.1.1, numpy 2.4.6, Streamlit 1.67.0, Plotly 7.1.0.

| Command | Result |
|---|---|
| `python -m sunspot_pipeline run` | completed, run `20261110T204328Z-5ecef8eb`, quality `ok`, reconciliation passed, about 8 s |
| `python -m sunspot_pipeline run` (straight after) | `skipped`, "inputs unchanged (matches 20261110T204328Z-5ecef8eb)", nothing new archived |
| `python -m sunspot_pipeline list` | 1 archived run |
| `python -m sunspot_pipeline verify` | all 14 archived files OK against the manifest SHA-256 |
| `pytest -q` | **48 passed** |
| `ruff check .` / `ruff format --check .` | all checks passed / 25 files already formatted |
| Mutation check (break code on purpose, rerun tests) | untapered weights → 4 tests fail; half-even rounding → 3 fail; never-skip ingest → 2 fail; removing the first overwrite guard → 0 fail, because the second guard before the rename still refuses (expected; behaviour unchanged) |
| `streamlit run streamlit_app.py` + headless Chrome screenshots | all four pages render with the live run |
| `docker build -t sunspot-pipeline .` | not run locally: Docker Desktop's engine wasn't running on this machine. The image builds successfully in CI (see below) |
| `git push -u origin main` | pushed to https://github.com/MadniAbdulWahab/sunspot-pipeline |
| GitHub Actions CI | **passing**, [run 42901280637](https://github.com/MadniAbdulWahab/sunspot-pipeline/actions/runs/42901280637): `test (3.11)` success, `test (3.12)` success (lint + pytest in each), `docker` build success |
| Live URL (Streamlit Community Cloud) | **https://sunspot-pipeline.streamlit.app/**. On first start it ran the pipeline itself (run `20261110T211617Z-5ecef8eb`). The input fingerprint `5ecef8eb` is the same as the local run's, and it gives the same quality and reconciliation results |

Input files for that run (SILSO `Last-Modified` 2026-11-01):

| File | Bytes | SHA-256 (first 16) |
|---|---|---|
| SN_d_tot_V2.0.csv | 2,898,450 | 28525cc0adeb4320 |
| SN_m_tot_V2.0.csv | 126,692 | 1cf8a1f6f28ff9ee |
| SN_ms_tot_V2.0.csv | 126,692 | 6556ec0b65f608a2 |

Quality report: daily 76,275 rows (3,247 missing days, 123 provisional, 73,028 usable); monthly 3,334
rows (4 provisional, 1 value with no observations: 1824-02); smoothed 3,334 rows (12 expected edge
blanks, 10 provisional). No schema errors, duplicates, gaps, range errors or decimal-date mismatches.

## Reconciliation results

Rounded half-up to 1 decimal, tolerance 0.05.

| Comparison | Compared | Exact | Rounding ties | Mismatches | Max abs diff | Mean abs diff |
|---|---|---|---|---|---|---|
| Monthly mean from daily vs SILSO monthly (1818-01 to 2026-10) | 2505 | 2505 | 0 | 0 | 0.0 | 0.0 |
| Derived smoothed vs SILSO smoothed (1818-07 to 2026-04) | 2481 | 2453 | 28 | 0 | 0.1 | 0.00113 |
| Smoothing on SILSO's own monthly vs SILSO smoothed (1749-07 to 2026-04) | 3322 | 3288 | 34 | 0 | 0.1 | 0.00102 |

- Not derivable: 1824-02 monthly (no daily observations; SILSO's 18.0 was interpolated), and therefore
  the 13 smoothed months 1823-08 to 1824-08. Everything before 1818 has no daily data.
- All ties are exact .x5 values, e.g. 1958-02: unrounded 284.55, mine 284.6, SILSO 284.5;
  1852-06: 104.85 → 104.9 vs 104.8. Across the 130 exact ties in the formula check SILSO rounded 96 up
  and 34 down.
- With Python's default rounding (half-to-even) the monthly comparison would have shown 15 false
  0.1 differences. Smoothing the unrounded monthly means instead of the rounded ones would have
  shown 171.
- Provisional months compared: 4 monthly, 4 smoothed, all exact.

## Design decisions

The full reasoning is in the README ("Design decisions"). In short:

1. Round half-up like SILSO, tolerance 0.05 (half the published precision).
2. One-unit differences on exact .x5 ties are a separate "rounding tie" result, not a pass or failure.
3. Smooth the rounded monthly means, the same way SILSO smooths its published values.
4. Extra comparison: my smoothing on SILSO's monthly file, to test the formula separately.
5. Flag, never drop. Only a layout change fails a run.
6. Skip when input hashes and pipeline version both match an archived run.
7. Write-once archive through a staging folder and an atomic rename; refuse if the target exists.
8. Run ID = UTC timestamp + input-hash prefix; archive path `archive/v<semver>/<run_id>/`.
9. The app reads archived runs only, and bootstraps one run on a fresh deployment.

## Known limitations

- File-based, single-user; no locking beyond "refuse if the folder exists".
- Archive immutability is enforced by the code and checked by hashes, not by file permissions.
- Streamlit Community Cloud storage is ephemeral, so the deployed archive resets on restart.
- No scheduled runs yet, and no diff between consecutive runs when SILSO revises provisional values.
- SILSO's rounding of exact ties can't be reproduced; those months are reported separately.
- Docker image built in CI only; I haven't run the container locally yet.
