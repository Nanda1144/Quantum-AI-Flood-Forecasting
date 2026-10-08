# Q-FLARE - Quantum-AI Flood Forecasting & Disaster-Response Platform
# Module: ai-service | Owner: forecasting module | License: Apache-2.0
#
# PLEDGE: This source file belongs to the Q-FLARE platform (Nanda Construction). It is honest by construction, per the platform README: no
# fabricated data, no invented metrics, every surrogate or fallback is clearly
# labelled, and no quantum speedup is ever claimed.

"""Phase 2 — unit validation and normalisation, and nothing else.

The rule
--------
**Convert only where the factor is exact, dimensional, and documented. Otherwise
say `UNDETERMINED` and leave the number alone.**

An unrecognised unit is not an obstacle to be routed around. `mm`, `m`, `m3/s`
and `degC` are not suggestions; a column of unknown numbers relabelled `mm` is a
dataset that now looks measured in a unit nobody chose. So every unit this
module will not convert is returned as `UNDETERMINED_UNIT` with
`converted=False`, and the caller is told.

What this module refuses
------------------------
* **Ambiguous symbols.** `C` and `F` are in `domains.KNOWN_UNITS` because a
  source may legitimately declare them, but bare `C` is coulomb as readily as
  Celsius and bare `F` is foot, farad or Fahrenheit. They are *recognised*
  (so no quality warning) and **not convertible** (so no guess). `degC`/`degF`
  are unambiguous and are converted.
* **Rate → amount.** `mm/h` is a *length per time*; `mm` is a *length*. There is
  no factor between them, because converting an intensity into a depth needs a
  measurement window, and that is aggregation (Phase 2 §13 / Phase 3), not unit
  conversion. Attempting it is an error with an explanation, not a silent
  arithmetic pass.
* **Anything outside the table.** Not a whitelist *warning* — an actual refusal
  to transform.

Exactness of the factors
------------------------
Every factor here is a definition, not an approximation:

===========  ===============  ==================================
Symbol       Factor / offset  Basis
===========  ===============  ==================================
`ft`         × 0.3048        international foot, exact
`in`         × 0.0254        international inch, exact
`mm` `cm`    × 1e-3 × 1e-2   SI prefixes, exact
`degF`       × 5/9 − 17.777… exact affine relation to `degC`
`K`          − 273.15        exact offset on the Celsius scale
`cumecs`,
`cusecs`     × 1             defined as one cubic metre per second
===========  ===============  ==================================

No empirical rating curve, no catchment-specific factor and no datum shift is
applied anywhere in this module, because none has been supplied. In particular a
unit conversion **does not move a vertical datum**: converting a stage from
metres to feet does not make it comparable with another gauge, and the report
says so.

Floating point
--------------
The *factors* are exact; the arithmetic is IEEE-754 double precision, so
`convert_value(3.0, "ft", "cm")` returns `91.44000000000001` rather than `91.44`.
The result is deliberately **not** rounded. Rounding would be a second, silent
transformation applied on top of the declared one, and it would round in the
direction the implementation happened to accumulate error. Determinism is not
affected — the same inputs always produce the same bits — so callers compare with
a tolerance rather than expecting a tidy decimal.

Pure standard library. The recognised-unit vocabulary is imported from
`domains`, so the warning and the conversion table cannot disagree about what
counts as a unit.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from .domains import unit_is_known
from .preprocess_config import (
    UNIT_PRESERVE_UNDETERMINED,
    UNIT_REQUIRE_KNOWN,
    UNDETERMINED_UNIT,
)

# --------------------------------------------------------------------------- #
# Dimensions
# --------------------------------------------------------------------------- #

#: No dimension — a pure ratio.
DIM_RATIO = "ratio"
#: A length. Stage, and also rainfall depth.
DIM_LENGTH = "length"
#: A length per unit time. Rainfall *intensity*.
DIM_LENGTH_PER_TIME = "length_per_time"
#: A volume per unit time. Discharge, inflow.
DIM_VOLUME_FLOW = "volume_flow"
#: A thermodynamic temperature, on an affine scale.
DIM_TEMPERATURE = "temperature"

DIMENSIONS = (
    DIM_RATIO,
    DIM_LENGTH,
    DIM_LENGTH_PER_TIME,
    DIM_VOLUME_FLOW,
    DIM_TEMPERATURE,
)

#: The hub each dimension is converted through. Using one intermediate
#: representation means an `ft` → `cm` conversion is defined by the same two
#: steps as an `in` → `m` one, instead of needing a factor for every ordered
#: pair.
_HUB = {
    DIM_RATIO: "%",
    DIM_LENGTH: "m",
    DIM_LENGTH_PER_TIME: "m/s",
    DIM_VOLUME_FLOW: "m3/s",
    DIM_TEMPERATURE: "degC",
}

#: (dimension, factor_to_hub, offset_to_hub).
#:
#: `value_in_hub = value * factor + offset`.
#:
#: The hub units themselves have `factor=1, offset=0` so that `degC` (the
#: temperature hub) needs no special case in the arithmetic.
#:
#: Keys are **case-folded**, because `_normalise_symbol` case-folds every lookup:
#: `M3/S` and `m3/s` are the same symbol. Displayed unit strings always come from
#: the source's own declaration via `UnitConversion.original_unit`, never from
#: these keys, so folding here cannot rewrite what a dataset said.
_UNIT_DEFINITIONS: Mapping[str, tuple[str, float, float]] = {
    # -- ratio ------------------------------------------------------------
    "%": (DIM_RATIO, 1.0, 0.0),
    "percent": (DIM_RATIO, 1.0, 0.0),
    # -- length -----------------------------------------------------------
    "m": (DIM_LENGTH, 1.0, 0.0),
    "cm": (DIM_LENGTH, 0.01, 0.0),
    "mm": (DIM_LENGTH, 0.001, 0.0),
    "ft": (DIM_LENGTH, 0.3048, 0.0),
    "in": (DIM_LENGTH, 0.0254, 0.0),
    # -- length per time --------------------------------------------------
    # Converted through metres per second, so mm/h = 1e-3 m / 3600 s.
    "m/s": (DIM_LENGTH_PER_TIME, 1.0, 0.0),
    "mm/h": (DIM_LENGTH_PER_TIME, 0.001 / 3600.0, 0.0),
    "cm/h": (DIM_LENGTH_PER_TIME, 0.01 / 3600.0, 0.0),
    "in/h": (DIM_LENGTH_PER_TIME, 0.0254 / 3600.0, 0.0),
    # -- volume per time --------------------------------------------------
    "m3/s": (DIM_VOLUME_FLOW, 1.0, 0.0),
    "m^3/s": (DIM_VOLUME_FLOW, 1.0, 0.0),
    "m3s-1": (DIM_VOLUME_FLOW, 1.0, 0.0),
    "cumecs": (DIM_VOLUME_FLOW, 1.0, 0.0),
    "cusecs": (DIM_VOLUME_FLOW, 1.0, 0.0),
    # -- temperature ------------------------------------------------------
    "degc": (DIM_TEMPERATURE, 1.0, 0.0),
    "degf": (DIM_TEMPERATURE, 5.0 / 9.0, -32.0 * 5.0 / 9.0),
    "k": (DIM_TEMPERATURE, 1.0, -273.15),
}

#: Symbols that appear in `domains.KNOWN_UNITS` and are therefore *recognised*
#: (they raise no quality warning), but which this module refuses to convert
#: because the bare symbol is ambiguous.
#:
#: `C` is coulomb as readily as Celsius; `F` is foot, farad or Fahrenheit. A
#: source that means degrees Celsius must say `degC`, and a source that means
#: feet must say `ft`. One unambiguous character is worth requiring here, because
#: the alternative is silently picking one of three meanings.
AMBIGUOUS_UNITS: Mapping[str, str] = {
    "c": "coulomb or Celsius — declare 'degC' for degrees Celsius",
    "f": "farad, foot or Fahrenheit — declare 'degF', 'ft' or the symbol you mean",
    "mb": "millibar or megabyte is ambiguous in context — declare 'hPa' for millibar",
}

#: Units that `domains.KNOWN_UNITS` recognises, that are **not** ambiguous, and
#: that this module still declines to convert because no exact factor to a hub
#: unit exists. Distinct from `AMBIGUOUS_UNITS`: `pascal` is one thing, and the
#: answer is "there is nothing here to convert it to", not "I cannot tell which
#: physical quantity you meant".
UNCONVERTIBLE_UNITS: Mapping[str, str] = {
    "pa": "pascal is recognised but has no exact conversion to any other unit defined here",
}

#: Units present in `domains.KNOWN_UNITS` that this module has no definition for.
#: Being known-but-unconvertible is a normal state, not a defect.
_UNCONVERTIBLE_KNOWN: frozenset[str] = frozenset(UNCONVERTIBLE_UNITS)

#: How a case-folded lookup key is spelled for display. Used only by
#: `convertible_units()` and `describe_unit`; a record's `original_unit` always
#: comes from the source, never from here.
_DISPLAY_SPELLING: Mapping[str, str] = {
    "degc": "degC",
    "degf": "degF",
    "k": "K",
}


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #


class UnitError(ValueError):
    """Raised when a unit conversion is demanded and cannot be performed.

    Separate from `preprocess_config.PreprocessConfigError` (a configuration is
    self-contradictory) and from `domains.SchemaError` (a record cannot be built):
    this is a *conversion* that cannot be honoured, and the message always says
    why.
    """


# --------------------------------------------------------------------------- #
# Lookup
# --------------------------------------------------------------------------- #


def is_convertible(unit: str) -> bool:
    """True when `unit` has an exact definition in this module.

    Not the same as `domains.unit_is_known`. A unit can be perfectly legitimate
    and still not convertible — `degC` is convertible, `C` is recognised but not
    convertible, and a unit nobody has seen is neither.
    """
    return _normalise_symbol(unit) in _UNIT_DEFINITIONS


def dimension_of(unit: str) -> str | None:
    """The dimension of `unit`, or `None` when it has no definition here."""
    entry = _UNIT_DEFINITIONS.get(_normalise_symbol(unit))
    return entry[0] if entry else None


def hub_unit_for(dimension: str) -> str | None:
    """The intermediate unit a dimension is converted through.

    Exposed so the report can name the reference point a conversion was measured
    against: `ft → cm` is two steps, and `ft → cm → m` is the path.
    """
    return _HUB.get(dimension)


def describe_unit(unit: str) -> dict[str, Any]:
    """Everything this module can say about one unit string.

    Used by the report so a reader can tell the three different states apart:
    recognised-and-convertible, recognised-but-ambiguous, and unrecognised.
    """
    text = (unit or "").strip()
    symbol = _normalise_symbol(text)
    entry = _UNIT_DEFINITIONS.get(symbol)
    recognised = unit_is_known(text)
    ambiguous = symbol in AMBIGUOUS_UNITS
    if entry is not None:
        status = "convertible"
        note = ""
    elif ambiguous:
        status = "ambiguous"
        note = AMBIGUOUS_UNITS[symbol]
    elif symbol in _UNCONVERTIBLE_KNOWN:
        status = "recognised_not_convertible"
        note = UNCONVERTIBLE_UNITS[symbol]
    else:
        status = "unrecognised"
        note = (
            "not in domains.KNOWN_UNITS; a legitimate unit that this repository has not "
            "seen. Recorded as declared, NOT converted."
        )
    return {
        "unit": text,
        "status": status,
        "dimension": entry[0] if entry else None,
        "hub_unit": _HUB.get(entry[0]) if entry else None,
        "recognised": recognised,
        "ambiguous": ambiguous,
        "note": note,
    }


def convertible_units() -> tuple[str, ...]:
    """Every unit this module can convert, in stable sorted order.

    Displayed with conventional capitalisation (`degC`, `K`) rather than the
    case-folded keys used internally for lookup.
    """
    return tuple(sorted(_DISPLAY_SPELLING.get(symbol, symbol) for symbol in _UNIT_DEFINITIONS))


def _normalise_symbol(unit: str) -> str:
    """Strip and case-fold a unit symbol for table lookup only.

    Lookup is case-insensitive so that `M3/S` and `m3/s` are the same symbol;
    the *declared* string is always what gets reported back, because the source's
    spelling is the fact and this module is not permitted to rewrite it silently.
    """
    if not isinstance(unit, str):
        return ""
    return unit.strip().lower()


# --------------------------------------------------------------------------- #
# Conversion result
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class UnitConversion:
    """The outcome of normalising one measurement's unit.

    `original_unit` is always populated, including when `normalized_unit` is
    `UNDETERMINED_UNIT`. A conversion record that loses the source unit is a
    conversion record that cannot be audited, and an audit is the only reason to
    perform one.
    """

    original_unit: str
    normalized_unit: str
    original_value: float
    value: float
    dimension: str | None = None
    factor: float | None = None
    offset: float | None = None
    converted: bool = False
    note: str = ""

    @property
    def was_convertible(self) -> bool:
        """True when the unit *could* have been converted.

        False here with `converted=True` is impossible; false in both means the
        unit is undetermined, which is a different situation from "declined to
        convert a convertible unit".
        """
        return self.factor is not None

    @property
    def is_undetermined(self) -> bool:
        return self.normalized_unit == UNDETERMINED_UNIT

    @property
    def value_changed(self) -> bool:
        return self.original_value != self.value

    def to_dict(self) -> dict[str, Any]:
        return {
            "original_unit": self.original_unit,
            "normalized_unit": self.normalized_unit,
            "original_value": self.original_value,
            "value": self.value,
            "dimension": self.dimension,
            "factor": self.factor,
            "offset": self.offset,
            "converted": self.converted,
            "note": self.note,
        }


def convert_value(value: float, source_unit: str, target_unit: str) -> tuple[float, float, float]:
    """Return `(converted_value, factor, offset)` for an exact unit conversion.

    `factor`/`offset` describe `target = (source * factor + offset - hub_offset) / hub_factor`
    collapsed to a single affine pair, so the record is readable without
    reconstructing the two-step path.

    Raises `UnitError` for an unknown, ambiguous or dimensionally incompatible
    unit. It never returns a best-effort number.
    """
    source_symbol = _normalise_symbol(source_unit)
    target_symbol = _normalise_symbol(target_unit)
    source_entry = _UNIT_DEFINITIONS.get(source_symbol)
    target_entry = _UNIT_DEFINITIONS.get(target_symbol)

    if source_entry is None:
        raise UnitError(_no_conversion_reason(source_unit))
    if target_entry is None:
        raise UnitError(
            f"target unit {target_unit!r} has no exact conversion defined here "
            f"({describe_unit(target_unit)['note']})"
        )
    if source_entry[0] != target_entry[0]:
        raise UnitError(
            f"cannot convert {source_unit!r} ({source_entry[0]}) to {target_unit!r} "
            f"({target_entry[0]}): the dimensions differ"
            + _dimension_hint(source_entry[0], target_entry[0])
        )

    source_dimension, source_factor, source_offset = source_entry
    target_dimension, target_factor, target_offset = target_entry

    hub_value = float(value) * source_factor + source_offset
    result = (hub_value - target_offset) / target_factor
    if not math.isfinite(result):  # pragma: no cover - inputs are validated upstream
        raise UnitError(
            f"converting {value!r} {source_unit} to {target_unit} produced a non-finite value"
        )
    # Collapsed affine pair, so `factor`/`offset` on the record are directly usable.
    factor = source_factor / target_factor
    offset = (source_offset - target_offset) / target_factor
    del source_dimension, target_dimension
    return result, factor, offset


def _no_conversion_reason(unit: str) -> str:
    described = describe_unit(unit)
    if described["ambiguous"]:
        return (
            f"unit {unit!r} is ambiguous: {described['note']}. A conversion here would be a "
            "guess between different physical quantities, so this module refuses it."
        )
    return (
        f"unit {unit!r} has no exact conversion defined here: {described['note']}. No factor "
        "between it and any hub unit is established in this repository, so none is applied."
    )


def _dimension_hint(source_dimension: str, target_dimension: str) -> str:
    if source_dimension == DIM_LENGTH_PER_TIME and target_dimension == DIM_LENGTH:
        return (
            ". Converting an intensity to a depth requires a measurement window: it is "
            "aggregation over time, not a unit conversion, and no window has been declared for "
            "this source"
        )
    return ""


# --------------------------------------------------------------------------- #
# Normalisation
# --------------------------------------------------------------------------- #


def normalize_unit(
    value: float,
    unit: str,
    *,
    target_unit: str | None = None,
    quantity: str | None = None,
    policy: str = UNIT_PRESERVE_UNDETERMINED,
) -> UnitConversion:
    """Normalise one measurement's unit, or explain why it cannot be normalised.

    Behaviour by policy:

    * **no `target_unit` declared** — nothing is converted. The unit is reported
      as itself (if it has a definition) or as `UNDETERMINED_UNIT`. A pipeline
      that has not been told what unit it works in must not pick one.
    * **`target_unit` equal to `unit`** — identity, `converted=False`. A
      same-unit pass is not a transformation and must not be counted as one.
    * **`target_unit` set and convertible** — converted, with `factor`/`offset`.
    * **`target_unit` set and not convertible, `preserve_undetermined`** — value
      untouched, unit reported as declared (or `UNDETERMINED_UNIT`), `converted`
      `False`, and a note. This is the default because the committed synthetic
      sample's `inflow` column is deliberately unit-less.
    * **`target_unit` set and not convertible, `require_known`** — `UnitError`.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise UnitError(f"value must be a real number, got {type(value).__name__}")
    number = float(value)
    if not math.isfinite(number):
        raise UnitError(
            f"value must be finite, got {value!r}; NaN and infinity are not measurements"
        )
    if policy not in (UNIT_PRESERVE_UNDETERMINED, UNIT_REQUIRE_KNOWN):
        raise UnitError(f"unknown unit policy {policy!r}")

    declared = (unit or "").strip()
    desired = (target_unit or "").strip()
    description = describe_unit(declared)

    # --- no target unit: report, never guess ------------------------------
    if not desired:
        if description["status"] == "convertible":
            normalized = declared
            note = (
                "no target unit declared for this quantity; the source unit is kept as-is and "
                "not converted"
            )
        else:
            normalized = UNDETERMINED_UNIT
            note = (
                f"no target unit declared and the source unit is not convertible "
                f"({description['note']})"
            )
        return UnitConversion(
            original_unit=declared or UNDETERMINED_UNIT,
            normalized_unit=normalized,
            original_value=number,
            value=number,
            dimension=description["dimension"],
            converted=False,
            note=note + _datum_note(quantity, None),
        )

    # --- identity ----------------------------------------------------------
    if _normalise_symbol(declared) == _normalise_symbol(desired):
        return UnitConversion(
            original_unit=declared or UNDETERMINED_UNIT,
            normalized_unit=declared or desired,
            original_value=number,
            value=number,
            dimension=description["dimension"],
            factor=1.0,
            offset=0.0,
            converted=False,
            note="source unit already matches the declared target unit; no transformation applied"
            + _datum_note(quantity, declared),
        )

    # --- convert, or explain why not ---------------------------------------
    try:
        converted, factor, offset = convert_value(number, declared, desired)
    except UnitError as exc:
        if policy == UNIT_REQUIRE_KNOWN:
            raise UnitError(
                f"{exc} (unit_policy='require_known'; set unit_policy="
                f"'{UNIT_PRESERVE_UNDETERMINED}' to carry the declared unit through instead)"
            ) from exc
        return UnitConversion(
            original_unit=declared or UNDETERMINED_UNIT,
            normalized_unit=declared if description["status"] == "convertible" else UNDETERMINED_UNIT,
            original_value=number,
            value=number,
            dimension=description["dimension"],
            converted=False,
            note=str(exc) + _datum_note(quantity, declared),
        )

    return UnitConversion(
        original_unit=declared or UNDETERMINED_UNIT,
        normalized_unit=desired,
        original_value=number,
        value=converted,
        dimension=description["dimension"],
        factor=factor,
        offset=offset,
        converted=True,
        note=f"converted {declared!r} to {desired!r} using an exact documented factor"
        + _datum_note(quantity, declared),
    )


def _datum_note(quantity: str | None, unit: str) -> str:
    """Warn that a unit change does not make stages comparable.

    A vertical datum is a reference surface, not a unit. Converting metres to
    feet relabels the number and moves nothing on the ground, so two gauges in
    different units remain incomparable exactly as before. No datum has been
    supplied for any gauge in this repository.
    """
    if quantity != "water_level":
        return ""
    return (
        f" NOTE: this is a unit change, not a datum change. The vertical datum of the "
        f"unit {unit or 'UNDETERMINED'} is not established in this repository, so this stage "
        "remains comparable only with readings from the same gauge under the same datum."
    )


# --------------------------------------------------------------------------- #
# Batch statistics
# --------------------------------------------------------------------------- #


@dataclass
class UnitConversionReport:
    """Aggregate of every unit decision taken in one run.

    The counters answer the brief's "what units were converted?" as a table
    rather than a sentence, and `undetermined_units` names the quantities still
    in an unknown unit so a dataset owner can be asked about them specifically.
    """

    considered: int = 0
    converted: int = 0
    already_normalized: int = 0
    undetermined: int = 0
    #: (original_unit, normalized_unit) → count.
    pairs: dict[tuple[str, str], int] = field(default_factory=dict)
    #: quantity → the units it was seen in, for a unit-less quantity.
    quantities: dict[str, list[str]] = field(default_factory=dict)
    #: Free-text notes, deduplicated and stably ordered.
    notes: list[str] = field(default_factory=list)

    def record(self, quantity: str | None, conversion: UnitConversion) -> None:
        self.considered += 1
        key = (conversion.original_unit, conversion.normalized_unit)
        self.pairs[key] = self.pairs.get(key, 0) + 1
        if conversion.converted:
            self.converted += 1
        elif conversion.is_undetermined:
            self.undetermined += 1
        else:
            self.already_normalized += 1
        if conversion.note and conversion.note not in self.notes:
            self.notes.append(conversion.note)
        if quantity is not None:
            units = self.quantities.setdefault(quantity, [])
            if conversion.normalized_unit not in units:
                units.append(conversion.normalized_unit)

    @property
    def undetermined_quantities(self) -> tuple[str, ...]:
        """Quantities that ended up in a unit nobody could establish."""
        return tuple(
            sorted(
                quantity
                for quantity, units in self.quantities.items()
                if UNDETERMINED_UNIT in units
            )
        )

    @property
    def conversions(self) -> list[dict[str, Any]]:
        """The unit pairs actually applied, most-used first, ties broken by name.

        Sorted rather than insertion-ordered so two runs over the same data in
        different input orders produce byte-identical reports.
        """
        return [
            {
                "original_unit": original,
                "normalized_unit": normalized,
                "count": count,
            }
            for (original, normalized), count in sorted(
                self.pairs.items(), key=lambda item: (-item[1], item[0][0], item[0][1])
            )
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "considered": self.considered,
            "converted": self.converted,
            "already_normalized": self.already_normalized,
            "undetermined": self.undetermined,
            "conversions": self.conversions,
            "quantities": {key: list(value) for key, value in sorted(self.quantities.items())},
            "undetermined_quantities": list(self.undetermined_quantities),
            "notes": list(self.notes),
        }

    def describe(self) -> str:
        lines = [
            f"UNITS considered={self.considered} converted={self.converted} "
            f"unchanged={self.already_normalized} undetermined={self.undetermined}"
        ]
        for entry in self.conversions:
            lines.append(
                f"    {entry['count']:>6} x {entry['original_unit']} -> {entry['normalized_unit']}"
            )
        if self.undetermined_quantities:
            lines.append(
                f"    UNDETERMINED UNIT for: {', '.join(self.undetermined_quantities)}"
            )
        return "\n".join(lines)


def unit_report_for(
    values: Iterable[tuple[str | None, UnitConversion]],
) -> UnitConversionReport:
    """Fold `(quantity, conversion)` pairs into a report."""
    report = UnitConversionReport()
    for quantity, conversion in values:
        report.record(quantity, conversion)
    return report


__all__ = [
    "AMBIGUOUS_UNITS",
    "DIMENSIONS",
    "DIM_LENGTH",
    "DIM_LENGTH_PER_TIME",
    "DIM_RATIO",
    "DIM_TEMPERATURE",
    "DIM_VOLUME_FLOW",
    "UnitConversion",
    "UnitConversionReport",
    "UnitError",
    "convert_value",
    "convertible_units",
    "describe_unit",
    "dimension_of",
    "hub_unit_for",
    "is_convertible",
    "normalize_unit",
    "unit_report_for",
]