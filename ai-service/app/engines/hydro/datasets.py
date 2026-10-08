# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service | Owner: forecasting module | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Phase 1 — dataset metadata: what a dataset is, and which domains it covers.

Not a second provenance system
------------------------------
`provenance.py` owns the facts about *where numbers came from* and
`config.DatasetSpec` owns the declared dataset configuration. This module adds
exactly one thing those cannot express: **domain coverage** — the fact that a
given dataset reports water level but no discharge, or rainfall but no weather.

That gap is the one that matters for Phase 1. Without it, a missing domain is
invisible: nothing breaks, the pipeline simply trains on whatever was supplied and
the omission is discovered months later, in a report, as an unexplained gap. With
it, "we have no discharge data" is a row in a table.

The honesty rule
----------------
The only dataset this repository can honestly describe is **synthetic**. The
default `DatasetCatalog` is therefore empty, and an empty catalog says so in
`describe()` rather than being presented as a well-stocked one. `NO_VERIFIED_
DATASETS` is the sentence it reports.
"""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass, field, replace
from typing import Any, Mapping

from .config import DatasetSpec
from .domains import (
    DATA_DOMAINS,
    DOMAIN_FLOOD_EVENT,
    DOMAIN_INFLOW,
    DOMAIN_RAINFALL,
    DOMAIN_WATER_LEVEL,
    NOT_AVAILABLE,
    domain_spec,
)
from .provenance import (
    DATASET_TYPE_REAL,
    DATASET_TYPE_SYNTHETIC,
    DATASET_TYPE_UNKNOWN,
    SYNTHETIC_DATA_DISCLAIMER,
    UNVERIFIED_DATA_DISCLAIMER,
    ProvenanceRecord,
    file_checksum,
    utc_now_iso,
)

#: Version of this schema foundation. Written into every descriptor so that a
#: stored record can be read back with the schema it was written against — the
#: same reasoning as `FORECAST_CONTRACT_VERSION`.
SCHEMA_VERSION = "navya-hydro-schema/v1"

#: Stated by an empty catalog. Reproduced from
#: `docs/architecture/ASSUMPTIONS_AND_LIMITATIONS.md` §1.1 so the two cannot drift.
NO_VERIFIED_DATASETS = (
    "No verified hydrological observation dataset exists in this repository. "
    + NOT_AVAILABLE
)

# --------------------------------------------------------------------------- #
# Domain coverage
# --------------------------------------------------------------------------- #

#: The source provides this domain.
COVERAGE_AVAILABLE = "available"
#: The source affirmatively does not provide it. Distinct from `unknown`: knowing
#: a gauge network has no discharge telemetry is a real, reportable fact.
COVERAGE_ABSENT = "absent"
#: Nobody has said either way.
COVERAGE_UNKNOWN = "unknown"

COVERAGE_STATUSES = (COVERAGE_AVAILABLE, COVERAGE_ABSENT, COVERAGE_UNKNOWN)


@dataclass(frozen=True)
class DomainCoverage:
    """Whether one dataset provides one domain, and on what terms."""

    domain: str
    status: str = COVERAGE_UNKNOWN
    record_count: int | None = None
    units: str | None = None
    notes: str = ""

    def __post_init__(self) -> None:
        domain_spec(self.domain)
        if self.status not in COVERAGE_STATUSES:
            raise ValueError(
                f"coverage status must be one of {COVERAGE_STATUSES}, got {self.status!r}"
            )
        if self.record_count is not None and self.record_count < 0:
            raise ValueError(f"record_count must be >= 0, got {self.record_count!r}")

    @property
    def is_available(self) -> bool:
        return self.status == COVERAGE_AVAILABLE

    @property
    def is_asserted(self) -> bool:
        """True when someone has actually said something about this domain."""
        return self.status in (COVERAGE_AVAILABLE, COVERAGE_ABSENT)

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "status": self.status,
            "record_count": self.record_count,
            "units": self.units,
            "notes": self.notes,
        }


def unknown_coverage() -> tuple[DomainCoverage, ...]:
    """Coverage for every domain, all `unknown`.

    The default a `DatasetDescriptor` starts from. A dataset is not assumed to
    cover anything: the supplier states what it carries.
    """
    return tuple(DomainCoverage(domain=name) for name in DATA_DOMAINS)


# --------------------------------------------------------------------------- #
# Dataset descriptor
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class DatasetDescriptor:
    """Everything known about one dataset, including what it does *not* contain.

    Composition, not inheritance: a descriptor references the existing
    `provenance.ProvenanceRecord` and `config.DatasetSpec` facts instead of
    declaring its own copies of `dataset_type`, the disclaimer or the licence, so
    the three cannot disagree.
    """

    reference: str | None = None
    dataset_type: str = DATASET_TYPE_UNKNOWN
    license: str | None = None
    checksum: str | None = None
    sampling_interval: str | None = None
    station_reference: str | None = None
    source_organisation: str | None = None
    location_kind: str | None = None
    domains: tuple[DomainCoverage, ...] = field(default_factory=unknown_coverage)
    disclaimer: str | None = None
    schema_version: str = SCHEMA_VERSION
    described_at: str = field(default_factory=utc_now_iso)
    notes: str = ""

    def __post_init__(self) -> None:
        if self.dataset_type not in (DATASET_TYPE_REAL, DATASET_TYPE_SYNTHETIC, DATASET_TYPE_UNKNOWN):
            raise ValueError(
                f"dataset_type must be 'real', 'synthetic' or 'unknown', got {self.dataset_type!r}"
            )
        for name in ("reference", "license", "checksum", "sampling_interval", "station_reference",
                     "source_organisation", "location_kind", "disclaimer"):
            object.__setattr__(self, name, _blank_to_none(getattr(self, name)))

        if self.dataset_type in (DATASET_TYPE_SYNTHETIC, DATASET_TYPE_UNKNOWN) and not self.disclaimer:
            # A non-real dataset with no warning is the one failure this whole
            # module exists to make impossible. Both strings are imported from
            # `provenance`, so there is exactly one copy of each sentence.
            object.__setattr__(
                self,
                "disclaimer",
                SYNTHETIC_DATA_DISCLAIMER
                if self.dataset_type == DATASET_TYPE_SYNTHETIC
                else UNVERIFIED_DATA_DISCLAIMER,
            )
        elif self.dataset_type == DATASET_TYPE_REAL:
            object.__setattr__(self, "disclaimer", None)

        names = [coverage.domain for coverage in self.domains]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(f"duplicate domain coverage entries: {duplicates}")

    # --- domain access -----------------------------------------------------

    def coverage_for(self, domain: str) -> DomainCoverage:
        """Coverage of `domain`, or an `unknown` entry when unstated."""
        for coverage in self.domains:
            if coverage.domain == domain:
                return coverage
        return DomainCoverage(domain=domain)

    def available_domains(self) -> tuple[str, ...]:
        return tuple(
            coverage.domain for coverage in self.domains if coverage.status == COVERAGE_AVAILABLE
        )

    def absent_domains(self) -> tuple[str, ...]:
        """Domains the source affirmatively does not carry.

        A real, useful answer. A dataset with rainfall but no discharge *is* a
        dataset with a known shape, and that shape decides which Phase 5 models
        are even constructible.
        """
        return tuple(
            coverage.domain for coverage in self.domains if coverage.status == COVERAGE_ABSENT
        )

    def unknown_domains(self) -> tuple[str, ...]:
        return tuple(
            coverage.domain for coverage in self.domains if coverage.status == COVERAGE_UNKNOWN
        )

    def with_coverage(self, coverage: DomainCoverage) -> "DatasetDescriptor":
        """A copy with one domain's coverage replaced."""
        replaced = [
            coverage if item.domain == coverage.domain else item for item in self.domains
        ]
        if not any(item.domain == coverage.domain for item in replaced):
            replaced.append(coverage)
        return replace(self, domains=tuple(replaced))

    # --- honesty -----------------------------------------------------------

    @property
    def is_synthetic(self) -> bool:
        return self.dataset_type == DATASET_TYPE_SYNTHETIC

    @property
    def may_be_presented_as_observation_data(self) -> bool:
        """True only for `real` data carrying no disclaimer.

        Matches `backend/src/features/forecasting/provenance.ts` →
        `isPresentableAsRealResult`. Nothing here is `real` today, which is why
        this returns `False` for every descriptor the repository can build.
        """
        return self.dataset_type == DATASET_TYPE_REAL and self.disclaimer is None

    def missing_fields(self) -> tuple[str, ...]:
        """Human-supplied facts that are still unknown.

        Deliberately *not* an error. Every one of these is an open question for a
        human, and the correct response to an open question is to report it, not
        to invent an answer.
        """
        checks = {
            "reference": self.reference,
            "license": self.license,
            "checksum": self.checksum,
            "sampling_interval": self.sampling_interval,
            "station_reference": self.station_reference,
            "source_organisation": self.source_organisation,
        }
        return tuple(name for name, value in checks.items() if not value)

    def with_provenance(self, provenance: ProvenanceRecord) -> "DatasetDescriptor":
        """Fill the dataset facts from an existing `ProvenanceRecord`.

        The record is the authority, so a descriptor cannot be built that claims a
        different checksum or licence than the model artifact recorded.
        """
        return replace(
            self,
            reference=provenance.dataset_reference or self.reference,
            dataset_type=provenance.dataset_type,
            license=provenance.dataset_license or self.license,
            checksum=provenance.dataset_checksum or self.checksum,
            sampling_interval=provenance.sampling_interval or self.sampling_interval,
            station_reference=provenance.station_reference or self.station_reference,
            disclaimer=provenance.disclaimer or self.disclaimer,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "reference": self.reference,
            "dataset_type": self.dataset_type,
            "license": self.license,
            "checksum": self.checksum,
            "sampling_interval": self.sampling_interval,
            "station_reference": self.station_reference,
            "source_organisation": self.source_organisation,
            "location_kind": self.location_kind,
            "domains": [coverage.to_dict() for coverage in self.domains],
            "available_domains": list(self.available_domains()),
            "absent_domains": list(self.absent_domains()),
            "unknown_domains": list(self.unknown_domains()),
            "disclaimer": self.disclaimer,
            "may_be_presented_as_observation_data": self.may_be_presented_as_observation_data,
            "missing_fields": list(self.missing_fields()),
            "described_at": self.described_at,
            "notes": self.notes,
        }

    def describe(self) -> str:
        lines = [
            f"DATASET {self.reference or 'UNRECORDED'}",
            f"  dataset_type  : {self.dataset_type}",
            f"  license       : {self.license or 'UNKNOWN'}",
            f"  checksum      : {self.checksum or 'UNKNOWN'}",
            f"  sampling      : {self.sampling_interval or 'UNKNOWN'}",
            f"  station       : {self.station_reference or 'UNKNOWN'}",
            f"  source org    : {self.source_organisation or 'UNKNOWN'}",
            "  domains       : "
            + (
                ", ".join(
                    f"{c.domain}={c.status}"
                    + (f" ({c.record_count} rows)" if c.record_count is not None else "")
                    for c in self.domains
                    if c.status != COVERAGE_UNKNOWN
                )
                or "none declared"
            ),
        ]
        unstated = self.unknown_domains()
        if unstated:
            lines.append(f"  unstated      : {', '.join(unstated)}")
        missing = self.missing_fields()
        if missing:
            lines.append(f"  UNKNOWN FIELDS: {', '.join(missing)}")
        if self.disclaimer:
            lines.append(f"  DISCLAIMER    : {self.disclaimer}")
        return "\n".join(lines)


def _blank_to_none(value: Any) -> str | None:
    """Normalise an optional string: blank/absent becomes `None`, never `''`."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"expected a string or None, got {type(value).__name__}")
    text = value.strip()
    return text or None


# --------------------------------------------------------------------------- #
# Catalog
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class DatasetCatalog:
    """The datasets this repository knows about, and what each one covers.

    Starts empty. An empty catalog is the correct state today and `describe()`
    says so in as many words, because a registry that silently contains nothing
    reads the same as one that was never checked.
    """

    datasets: tuple[DatasetDescriptor, ...] = ()

    def add(self, descriptor: DatasetDescriptor) -> "DatasetCatalog":
        """A catalog with `descriptor` appended.

        Returns a new catalog: this is a value, not a registry that mutates behind
        a caller's back.
        """
        return DatasetCatalog(datasets=(*self.datasets, descriptor))

    def real_datasets(self) -> tuple[DatasetDescriptor, ...]:
        return tuple(item for item in self.datasets if item.may_be_presented_as_observation_data)

    def non_real_datasets(self) -> tuple[DatasetDescriptor, ...]:
        return tuple(item for item in self.datasets if not item.may_be_presented_as_observation_data)

    def domains_available_anywhere(self) -> tuple[str, ...]:
        return tuple(
            domain
            for domain in DATA_DOMAINS
            if any(domain in item.available_domains() for item in self.datasets)
        )

    def by_reference(self, reference: str) -> DatasetDescriptor | None:
        for item in self.datasets:
            if item.reference == reference:
                return item
        return None

    def audit_rows(self) -> list[dict[str, Any]]:
        """One row per non-presentable dataset. The query an auditor would run."""
        return [
            {
                "reference": item.reference,
                "dataset_type": item.dataset_type,
                "available_domains": list(item.available_domains()),
                "disclaimer": item.disclaimer,
                "missing_fields": list(item.missing_fields()),
            }
            for item in self.non_real_datasets()
        ]

    def describe(self) -> str:
        if not self.datasets:
            return f"DATASET CATALOG (empty)\n  {NO_VERIFIED_DATASETS}"
        lines = [f"DATASET CATALOG ({len(self.datasets)} dataset(s))"]
        lines.extend(item.describe() for item in self.datasets)
        if not self.real_datasets():
            lines.append("")
            lines.append(f"  NONE of these may be presented as real observation data. {NO_VERIFIED_DATASETS}")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "dataset_count": len(self.datasets),
            "real_dataset_count": len(self.real_datasets()),
            "datasets": [item.to_dict() for item in self.datasets],
            "domains_available_anywhere": list(self.domains_available_anywhere()),
        }


#: The catalog as this repository actually stands.
EMPTY_CATALOG = DatasetCatalog()


# --------------------------------------------------------------------------- #
# The one dataset this repository holds
# --------------------------------------------------------------------------- #

#: Path to the committed SYNTHETIC/DEMO sample, resolved relative to this module
#: so it does not depend on the process working directory.
SYNTHETIC_SAMPLE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "synthetic_hydrology_sample.csv"
)

#: Column → (domain, unit) for the committed sample. Declared here, once, from the
#: generator's own documentation. `rainfall_mm` is an *intensity* (mm/h), which
#: is why the descriptor records `measurement_window` as the sampling interval.
#:
#: Note what is absent: there is no station column, no discharge column, no
#: weather column and no event register. The descriptor reports all four as
#: `absent`, which is the honest description of that file.
SYNTHETIC_SAMPLE_COLUMNS: Mapping[str, tuple[str, str | None]] = {
    "timestamp": (None, None),
    "water_level": (DOMAIN_WATER_LEVEL, "m (DEMO assumption — datum is fictional, NOT verified)"),
    "inflow": (DOMAIN_INFLOW, "UNDETERMINED (DEMO — no unit assigned)"),
    "rainfall_mm": (DOMAIN_RAINFALL, "mm/h"),
}


def synthetic_sample_descriptor(
    path: str = SYNTHETIC_SAMPLE_PATH,
    *,
    record_count: int | None = None,
) -> DatasetDescriptor:
    """Describe the committed synthetic sample by reading the file itself.

    The checksum, row count and column set come from the bytes on disk rather
    than from documentation, so the descriptor cannot drift from the artefact.

    **`station_reference` is deliberately left `None`.** The generator produces no
    station column, so the file carries no station identity. `SYNTHETIC-STATION-0001`
    exists only as a demo value in `synthetic.synthetic_dataset_spec`; attaching it
    here would promote a configuration placeholder into a property of the data.

    This is the only dataset descriptor this repository can build, and it is
    synthetic. No second synthetic dataset is generated.
    """
    checksum = file_checksum(path)
    header: list[str] = []
    rows = 0
    if os.path.exists(path):
        with open(path, newline="", encoding="utf-8") as handle:
            reader = csv.reader(handle)
            header = next(reader, [])
            rows = sum(1 for _ in reader)
    else:  # pragma: no cover - the file is committed
        raise FileNotFoundError(f"the committed synthetic sample is missing: {path}")

    unmapped = [column for column in header if column not in SYNTHETIC_SAMPLE_COLUMNS]
    count = record_count if record_count is not None else rows

    coverage: list[DomainCoverage] = []
    for domain in DATA_DOMAINS:
        columns = [column for column, (dom, _) in SYNTHETIC_SAMPLE_COLUMNS.items() if dom == domain]
        if columns:
            units = sorted(
                {
                    SYNTHETIC_SAMPLE_COLUMNS[column][1]
                    for column in columns
                    if SYNTHETIC_SAMPLE_COLUMNS[column][1]
                }
            )
            coverage.append(
                DomainCoverage(
                    domain=domain,
                    status=COVERAGE_AVAILABLE,
                    record_count=count,
                    units="; ".join(units),
                    notes=(
                        "SYNTHETIC/DEMO values from the committed generator. Not an "
                        "observation of any river."
                    ),
                )
            )
        else:
            coverage.append(
                DomainCoverage(
                    domain=domain,
                    status=COVERAGE_ABSENT,
                    notes=(
                        "not present in the committed synthetic sample; "
                        + domain_spec(domain).availability_note
                    ),
                )
            )

    reference = "synthetic://hydrology/committed-sample"
    notes = (
        "Committed SYNTHETIC/DEMO sample used so the pipeline is executable and testable. "
        "Every value is generated by a deterministic simulator and none of it is a "
        "measurement."
    )
    if unmapped:
        notes += f" NOTE: columns not declared in SYNTHETIC_SAMPLE_COLUMNS: {unmapped}."

    return DatasetDescriptor(
        reference=reference,
        dataset_type=DATASET_TYPE_SYNTHETIC,
        license="none — synthetic data has no license because it is not real data",
        checksum=checksum,
        sampling_interval="1h",
        station_reference=None,
        source_organisation=None,
        location_kind=None,
        domains=tuple(coverage),
        disclaimer=SYNTHETIC_DATA_DISCLAIMER,
        notes=notes,
    )


def committed_sample_catalog() -> DatasetCatalog:
    """A catalog containing exactly one entry: the committed synthetic sample."""
    return EMPTY_CATALOG.add(synthetic_sample_descriptor())


def coverage_matrix(catalog: DatasetCatalog | None = None) -> list[dict[str, Any]]:
    """Dataset × domain availability grid.

    Answers "which dataset supplies which domain?" in one table. The default is
    the committed sample, because that is all that exists.
    """
    resolved = catalog if catalog is not None else committed_sample_catalog()
    rows: list[dict[str, Any]] = []
    for domain in DATA_DOMAINS:
        row: dict[str, Any] = {"domain": domain}
        for descriptor in resolved.datasets:
            row[descriptor.reference or "unrecorded"] = descriptor.coverage_for(domain).status
        rows.append(row)
    return rows


def catalog_from_config(
    config: Any, *, reference: str | None = None
) -> DatasetDescriptor:
    """Build a descriptor from a `config.HydroConfig`.

    Reuses the already-declared `config.DatasetSpec` facts rather than reading the
    environment again, so the descriptor and the pipeline's own provenance cannot
    disagree about what dataset was used. Domain coverage is left `unknown`: the
    configuration declares where the file is, not what is in it. Populate it from
    the file, or leave it unknown — do not assume.
    """
    spec: DatasetSpec = config.dataset
    return DatasetDescriptor(
        reference=reference or spec.reference,
        dataset_type=spec.dataset_type,
        license=spec.license,
        checksum=None,
        sampling_interval=spec.sampling_interval,
        station_reference=spec.station_reference,
        source_organisation=None,
        location_kind=None,
        domains=unknown_coverage(),
        notes=(
            "Derived from the running configuration. Domain coverage is unstated: the "
            "configuration names a dataset, it does not describe its contents."
        ),
    )


__all__ = [
    "COVERAGE_ABSENT",
    "COVERAGE_AVAILABLE",
    "COVERAGE_STATUSES",
    "COVERAGE_UNKNOWN",
    "EMPTY_CATALOG",
    "NO_VERIFIED_DATASETS",
    "SCHEMA_VERSION",
    "SYNTHETIC_SAMPLE_COLUMNS",
    "SYNTHETIC_SAMPLE_PATH",
    "DatasetCatalog",
    "DatasetDescriptor",
    "DomainCoverage",
    "catalog_from_config",
    "committed_sample_catalog",
    "coverage_matrix",
    "synthetic_sample_descriptor",
    "unknown_coverage",
]