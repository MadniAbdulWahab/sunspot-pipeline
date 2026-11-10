"""Static configuration: data sources, file layouts and project paths."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ATTRIBUTION = "Source: WDC-SILSO, Royal Observatory of Belgium, Brussels, https://doi.org/10.24414/qnza-ac80"
LICENCE = "CC BY-NC 4.0 (https://creativecommons.org/licenses/by-nc/4.0/)"
CHANGES_NOTE = (
    "Derived products (monthly means from daily values, 13-month smoothed values, "
    "quality flags) were computed by this pipeline and are not official SILSO values."
)


@dataclass(frozen=True)
class Source:
    """One SILSO input file."""

    key: str
    url: str
    filename: str
    columns: tuple[str, ...]
    date_parts: tuple[str, ...]


DAILY = Source(
    key="daily",
    url="https://www.sidc.be/SILSO/DATA/SN_d_tot_V2.0.csv",
    filename="SN_d_tot_V2.0.csv",
    columns=("year", "month", "day", "decimal_date", "sn", "sn_std", "n_obs", "definitive"),
    date_parts=("year", "month", "day"),
)
MONTHLY = Source(
    key="monthly",
    url="https://www.sidc.be/SILSO/DATA/SN_m_tot_V2.0.csv",
    filename="SN_m_tot_V2.0.csv",
    columns=("year", "month", "decimal_date", "sn", "sn_std", "n_obs", "definitive"),
    date_parts=("year", "month"),
)
SMOOTHED = Source(
    key="smoothed",
    url="https://www.sidc.be/SILSO/DATA/SN_ms_tot_V2.0.csv",
    filename="SN_ms_tot_V2.0.csv",
    columns=("year", "month", "decimal_date", "sn", "sn_std", "n_obs", "definitive"),
    date_parts=("year", "month"),
)
SOURCES: tuple[Source, ...] = (DAILY, MONTHLY, SMOOTHED)

# SILSO files use -1 for "no value".
MISSING_SENTINEL = -1

# Reconciliation: derived values are rounded half-up to the published precision (1 decimal)
# and must then match within half a unit of that last decimal.
PUBLISHED_DECIMALS = 1
RECONCILE_TOLERANCE = 0.05


@dataclass(frozen=True)
class Paths:
    """Where the pipeline reads and writes. Everything hangs off one root folder."""

    root: Path

    @property
    def raw(self) -> Path:
        return self.root / "data" / "raw"

    @property
    def runs(self) -> Path:
        return self.root / "runs"

    @property
    def archive(self) -> Path:
        return self.root / "archive"

    @classmethod
    def default(cls) -> Paths:
        env = os.environ.get("SUNSPOT_HOME")
        root = Path(env) if env else Path(__file__).resolve().parent.parent
        return cls(root=root)
