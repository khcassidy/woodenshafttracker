from core.validate import check_batch_outlier, check_spine_reading, check_weight_reading

SPINE_KWARGS = dict(step_cp=50, hard_min_cp=1000, hard_max_cp=20000, warn_min_cp=3000, warn_max_cp=9000)
WEIGHT_KWARGS = dict(step_cg=1, hard_min_cg=100, hard_max_cg=20000, warn_min_cg=1500, warn_max_cg=3500)


def test_spine_within_all_bands_has_no_issues():
    assert check_spine_reading(5600, **SPINE_KWARGS) == []


def test_spine_off_step_warns_without_blocking():
    issues = check_spine_reading(5630, **SPINE_KWARGS)
    assert len(issues) == 1
    assert issues[0].code == "OFF_STEP"
    assert issues[0].blocking is False


def test_spine_outside_hard_band_blocks():
    issues = check_spine_reading(500, **SPINE_KWARGS)
    assert len(issues) == 1
    assert issues[0].code == "OUT_OF_RANGE"
    assert issues[0].blocking is True


def test_spine_outside_warn_band_but_inside_hard_band_warns():
    issues = check_spine_reading(2000, **SPINE_KWARGS)
    codes = [i.code for i in issues]
    assert "UNUSUAL_VALUE" in codes
    assert all(not i.blocking for i in issues)


def test_weight_within_all_bands_has_no_issues():
    assert check_weight_reading(2323, **WEIGHT_KWARGS) == []


def test_weight_outside_hard_band_blocks():
    issues = check_weight_reading(50, **WEIGHT_KWARGS)
    assert issues[0].code == "OUT_OF_RANGE"
    assert issues[0].blocking is True


def test_batch_outlier_within_tolerance_has_no_issues():
    assert check_batch_outlier(5600, 5600, 1000, "mlb") == []


def test_batch_outlier_beyond_tolerance_warns_nonblocking():
    issues = check_batch_outlier(7000, 5600, 1000, "mlb")
    assert len(issues) == 1
    assert issues[0].code == "BATCH_OUTLIER"
    assert issues[0].blocking is False
