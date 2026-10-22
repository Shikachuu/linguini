import pytest

from linguini.inventory.units import ALIASES, Unit, format_quantity, from_base, normalize_name, parse_unit, to_base
from linguini.models import Dimension


@pytest.mark.parametrize(
    ("text", "unit"),
    [
        ("kg", Unit.KG),
        ("Kilogramm", Unit.KG),
        ("db", Unit.PCS),
        ("darab", Unit.PCS),
        ("ek", Unit.TBSP),
        ("dl", Unit.DL),
        ("evőkanál", Unit.TBSP),
        ("csésze", Unit.CUP),
        ("pcs.", Unit.PCS),
        ("L", Unit.L),
    ],
)
def test_parse_unit_aliases(text: str, unit: Unit) -> None:
    assert parse_unit(text) is unit


def test_unknown_unit_raises() -> None:
    with pytest.raises(ValueError, match="unknown unit"):
        parse_unit("bucket")


@pytest.mark.parametrize(
    ("quantity", "unit", "dimension", "base"),
    [
        (1, Unit.KG, Dimension.MASS, 1000),
        (25, Unit.DKG, Dimension.MASS, 250),
        (2, Unit.DL, Dimension.VOLUME, 200),
        (3, Unit.TBSP, Dimension.VOLUME, 45),
        (6, Unit.PCS, Dimension.COUNT, 6),
    ],
)
def test_to_base(quantity: float, unit: Unit, dimension: Dimension, base: float) -> None:
    assert to_base(quantity, unit) == (dimension, base)


def test_round_trip_and_format() -> None:
    assert from_base(1500, Unit.KG) == pytest.approx(1.5)
    assert format_quantity(1500, Unit.KG) == "1.5 kg"
    assert format_quantity(6, Unit.PCS) == "6 pcs"
    assert format_quantity(333.3333, Unit.G) == "333.333 g"


def test_normalize_name_folds_accents_case_and_spaces() -> None:
    assert normalize_name("  Tejföl   FÉL zsíros ") == "tejfol fel zsiros"


@pytest.mark.parametrize(("alias", "unit"), sorted(ALIASES.items()))
def test_every_alias_parses(alias: str, unit: Unit) -> None:
    assert parse_unit(alias) is unit


def test_every_unit_has_an_alias() -> None:
    assert set(ALIASES.values()) == set(Unit)


@pytest.mark.parametrize(("text", "unit"), [("bögre", Unit.CUP), ("teáskanál", Unit.TSP), ("dkg.", Unit.DKG)])
def test_accented_and_dotted_aliases(text: str, unit: Unit) -> None:
    assert parse_unit(text) is unit


def test_fractional_factor_round_trips() -> None:
    assert from_base(to_base(3, Unit.TSP)[1], Unit.TSP) == pytest.approx(3)
    assert format_quantity(to_base(1.5, Unit.CUP)[1], Unit.CUP) == "1.5 cup"
