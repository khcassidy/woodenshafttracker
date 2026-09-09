from core.derive import ab_consistent, derive_spine, in_spec


def test_derive_spine_two_readings_equals_sum_times_five():
    # 56.00 + 55.00 lb -> sum_cp = 11100 -> avg_spine_mlb = 11100 * 5 = 55500
    d = derive_spine([5600, 5500])
    assert d.spine_count == 2
    assert d.spine_sum_cp == 11100
    assert d.avg_spine_mlb == 55500
    assert d.avg_spine_mlb == d.spine_sum_cp * 5
    assert d.spine_min_cp == 5500
    assert d.spine_max_cp == 5600
    assert d.spine_spread_cp == 100


def test_derive_spine_quarter_pound_readings():
    # 54.25 + 54.50 lb -> sum_cp = 10875 -> avg_spine_mlb = 54375 (54.375 lb)
    d = derive_spine([5425, 5450])
    assert d.avg_spine_mlb == 54375
    assert d.avg_spine_mlb == d.spine_sum_cp * 5


def test_derive_spine_two_reading_identity_holds_over_a_range():
    # The database asserts avg_spine_mlb == spine_sum_cp * 5 at count == 2.
    # Confirm the general formula matches that identity, not just at one point.
    for a in range(5000, 5100, 7):
        for b in range(5000, 5100, 11):
            d = derive_spine([a, b])
            assert d.avg_spine_mlb == d.spine_sum_cp * 5


def test_derive_spine_three_readings_uses_general_formula():
    # 56.00, 55.00, 55.25 lb -> sum_cp = 16625, count = 3
    d = derive_spine([5600, 5500, 5525])
    assert d.spine_count == 3
    assert d.spine_sum_cp == 16625
    assert d.avg_spine_mlb == 55417


def test_derive_spine_single_reading():
    d = derive_spine([5600])
    assert d.spine_count == 1
    assert d.avg_spine_mlb == 56000
    assert d.spine_spread_cp == 0


def test_derive_spine_empty_returns_none():
    assert derive_spine([]) is None


def test_derive_spine_rounds_half_up_not_half_to_even():
    # sum_cp=9 over 4 readings -> exact average 22.5 mlb. Python's round()
    # would give 22 (half-to-even); the required rule is half-up, so 23.
    d = derive_spine([3, 2, 2, 2])
    assert d.spine_sum_cp == 9
    assert d.avg_spine_mlb == 23


def test_in_spec_boundaries():
    spec_min, spec_max = 54000, 60000
    assert in_spec(54000, spec_min, spec_max) is True
    assert in_spec(60000, spec_min, spec_max) is True
    assert in_spec(53999, spec_min, spec_max) is False
    assert in_spec(60001, spec_min, spec_max) is False


def test_ab_consistent_matches_workbook_shaft_20_50():
    # Shaft 20-50 has an A/B spread of 2.0 lb against a 1.0 lb tolerance.
    assert ab_consistent(spine_spread_cp=200, ab_tol_cp=100) is False
    assert ab_consistent(spine_spread_cp=100, ab_tol_cp=100) is True
