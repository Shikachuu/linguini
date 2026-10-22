"""Units of measure and name normalization for inventory items."""

from __future__ import annotations

import re
import unicodedata
from enum import StrEnum

from linguini.models import Dimension


class Unit(StrEnum):
    """Units the inventory understands; each maps to a dimension and a factor to its base unit."""

    G = "g"
    DKG = "dkg"
    KG = "kg"
    ML = "ml"
    DL = "dl"
    L = "l"
    TSP = "tsp"
    TBSP = "tbsp"
    CUP = "cup"
    PCS = "pcs"


UNIT_INFO: dict[Unit, tuple[Dimension, float]] = {
    Unit.G: (Dimension.MASS, 1),
    Unit.DKG: (Dimension.MASS, 10),
    Unit.KG: (Dimension.MASS, 1000),
    Unit.ML: (Dimension.VOLUME, 1),
    Unit.DL: (Dimension.VOLUME, 100),
    Unit.L: (Dimension.VOLUME, 1000),
    Unit.TSP: (Dimension.VOLUME, 5),
    Unit.TBSP: (Dimension.VOLUME, 15),
    Unit.CUP: (Dimension.VOLUME, 240),
    Unit.PCS: (Dimension.COUNT, 1),
}

BASE_UNIT: dict[Dimension, Unit] = {Dimension.MASS: Unit.G, Dimension.VOLUME: Unit.ML, Dimension.COUNT: Unit.PCS}

ALIASES: dict[str, Unit] = {
    "g": Unit.G,
    "gram": Unit.G,
    "grams": Unit.G,
    "gramm": Unit.G,
    "dkg": Unit.DKG,
    "dag": Unit.DKG,
    "deka": Unit.DKG,
    "dekagramm": Unit.DKG,
    "kg": Unit.KG,
    "kilo": Unit.KG,
    "kilogram": Unit.KG,
    "kilogramm": Unit.KG,
    "ml": Unit.ML,
    "milliliter": Unit.ML,
    "dl": Unit.DL,
    "deci": Unit.DL,
    "deciliter": Unit.DL,
    "l": Unit.L,
    "liter": Unit.L,
    "litre": Unit.L,
    "tsp": Unit.TSP,
    "teaspoon": Unit.TSP,
    "tk": Unit.TSP,
    "teaskanal": Unit.TSP,
    "tbsp": Unit.TBSP,
    "tablespoon": Unit.TBSP,
    "ek": Unit.TBSP,
    "evokanal": Unit.TBSP,
    "cup": Unit.CUP,
    "cups": Unit.CUP,
    "csesze": Unit.CUP,
    "bogre": Unit.CUP,
    "pcs": Unit.PCS,
    "pc": Unit.PCS,
    "piece": Unit.PCS,
    "pieces": Unit.PCS,
    "db": Unit.PCS,
    "darab": Unit.PCS,
}

_SPACES = re.compile(r"\s+")


def strip_accents(text: str) -> str:
    """Remove diacritics so ``tejföl`` and ``tejfol`` compare equal.

    Returns:
        The text with combining marks dropped.
    """
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize_name(name: str) -> str:
    """Canonical lookup key for an item name.

    Returns:
        Lowercase, accent-free, single-spaced name.
    """
    return _SPACES.sub(" ", strip_accents(name).casefold()).strip()


def parse_unit(text: str) -> Unit:
    """Map a unit string, including Hungarian and English aliases, to a ``Unit``.

    Returns:
        The matching unit.

    Raises:
        ValueError: when the unit is unknown.
    """
    key = normalize_name(text).rstrip(".")
    try:
        return ALIASES[key]
    except KeyError as exc:
        msg = f"unknown unit {text!r}; use one of {', '.join(u.value for u in Unit)}"
        raise ValueError(msg) from exc


def to_base(quantity: float, unit: Unit) -> tuple[Dimension, float]:
    """Convert a quantity to its dimension's base unit.

    Returns:
        ``(dimension, quantity_in_base_unit)``.
    """
    dimension, factor = UNIT_INFO[unit]
    return dimension, quantity * factor


def from_base(quantity_base: float, unit: Unit) -> float:
    """Convert a base quantity to ``unit``.

    Returns:
        The quantity expressed in ``unit``, rounded to 3 decimals.
    """
    return round(quantity_base / UNIT_INFO[unit][1], 3)


def dimension_of(unit: Unit) -> Dimension:
    """Return the dimension a unit measures.

    Returns:
        The unit's dimension.
    """
    return UNIT_INFO[unit][0]


def format_quantity(quantity_base: float, unit: Unit) -> str:
    """Human-readable quantity such as ``1.5 kg`` or ``6 pcs``.

    Returns:
        The formatted string.
    """
    value = from_base(quantity_base, unit)
    text = f"{value:.3f}".rstrip("0").rstrip(".")
    return f"{text} {unit.value}"
