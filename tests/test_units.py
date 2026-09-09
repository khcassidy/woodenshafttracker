import pytest

from core.units import (
    UnitError,
    format_avg_spine_mlb,
    format_grains,
    format_spine_cp,
    format_weight_cg,
    grains_to_weight_cg,
    mean_minor,
    parse_spine_lb,
    parse_weight,
    parse_weight_g,
)


def test_parse_spine_lb_whole_number():
    assert parse_spine_lb("56") == 5600


def test_parse_spine_lb_half_pound():
    assert parse_spine_lb("56.5") == 5650


def test_parse_spine_lb_quarter_pound():
    assert parse_spine_lb("54.25") == 5425


def test_parse_weight_g_two_dp():
    assert parse_weight_g("23.23") == 2323


def test_parse_accepts_comma_decimal_separator():
    assert parse_spine_lb("23,23") == 2323


def test_parse_accepts_leading_dot():
    assert parse_spine_lb(".5") == 50


def test_parse_rejects_more_than_two_decimal_places():
    with pytest.raises(UnitError) as exc:
        parse_spine_lb("23.235")
    assert exc.value.code == "TOO_MANY_DP"


def test_parse_rejects_non_numeric():
    with pytest.raises(UnitError) as exc:
        parse_spine_lb("abc")
    assert exc.value.code == "NOT_A_NUMBER"


def test_parse_rejects_empty():
    with pytest.raises(UnitError) as exc:
        parse_spine_lb("   ")
    assert exc.value.code == "EMPTY"


@pytest.mark.parametrize("raw", ["0", "-5", "-0.01"])
def test_parse_rejects_non_positive(raw):
    with pytest.raises(UnitError) as exc:
        parse_spine_lb(raw)
    assert exc.value.code == "NOT_POSITIVE"


def test_grains_to_weight_cg_matches_known_conversion():
    # 350 gr, verified against 1 g = 15.4324 gr exactly.
    assert grains_to_weight_cg("350") == 2268


def test_grains_round_trip_is_lossy_but_close():
    cg = grains_to_weight_cg("350")
    back = format_grains(cg)
    assert back == "350.01"


def test_parse_weight_dispatches_on_unit():
    assert parse_weight("23.23", "g") == 2323
    assert parse_weight("350", "gr") == 2268


def test_parse_weight_rejects_unknown_unit():
    with pytest.raises(UnitError) as exc:
        parse_weight("1", "oz")
    assert exc.value.code == "BAD_UNIT"


def test_format_spine_cp_round_trips_display():
    assert format_spine_cp(5650) == "56.50"


def test_format_weight_cg_round_trips_display():
    assert format_weight_cg(2323) == "23.23"


def test_format_avg_spine_mlb_shows_three_decimal_places():
    assert format_avg_spine_mlb(54375) == "54.375"


def test_mean_minor_exact_division():
    assert mean_minor([54000, 55000, 56000]) == 55000


def test_mean_minor_rounds_half_up_not_toward_even():
    # (10 + 11) / 2 = 10.5 -- banker's rounding (Python's own round())
    # would give 10; ROUND_HALF_UP, the discipline every other conversion
    # in this module uses, gives 11.
    assert mean_minor([10, 11]) == 11


def test_mean_minor_single_value_is_itself():
    assert mean_minor([54375]) == 54375
