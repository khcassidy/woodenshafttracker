import pytest

from core.labels import parse_label, required_seq_width, shaft_label


def test_shaft_label_pads_to_width():
    assert shaft_label(19, 1, 2) == "19-01"
    assert shaft_label(19, 12, 2) == "19-12"


def test_shaft_label_rejects_seq_too_wide_for_width():
    with pytest.raises(ValueError):
        shaft_label(19, 100, 2)


def test_shaft_label_honours_wider_seq_width():
    assert shaft_label(19, 100, 3) == "19-100"


def test_parse_label_round_trips():
    assert parse_label("19-01") == (19, 1)
    assert parse_label("19-100") == (19, 100)


def test_parse_label_rejects_bad_shape():
    with pytest.raises(ValueError):
        parse_label("19_01")


@pytest.mark.parametrize(
    "count,width",
    [(1, 2), (50, 2), (99, 2), (100, 3), (999, 3), (1000, 4)],
)
def test_required_seq_width(count, width):
    assert required_seq_width(count) == width


def test_label_sort_by_seq_not_text():
    # 'BATCH#-SHAFT#' text-sorts wrong once a batch passes 99 shafts:
    # '19-100' < '19-20' as strings. Callers must sort by seq, not label.
    labels_by_text = sorted(["19-9", "19-20", "19-100"])
    assert labels_by_text == ["19-100", "19-20", "19-9"]
