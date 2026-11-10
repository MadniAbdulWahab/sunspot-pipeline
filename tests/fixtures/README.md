# Test fixtures

These are unmodified line extracts of the WDC-SILSO files, downloaded on 2026-11-10:

- `silso_1823_1825/`: all rows for 1823-1825 from `SN_d_tot_V2.0.csv`, `SN_m_tot_V2.0.csv` and `SN_ms_tot_V2.0.csv`.
  This period includes February 1824 (no daily observations at all) and April 1824 (daily mean exactly 32.25).
- `silso_recent/`: all rows for 2024-2026 from the same three files, ending in provisional values.

Where a test needs a broken file, the test changes a copy of these lines in memory. The files here are never edited.

Source: WDC-SILSO, Royal Observatory of Belgium, Brussels, https://doi.org/10.24414/qnza-ac80.
Licence: CC BY-NC 4.0 (https://creativecommons.org/licenses/by-nc/4.0/).
