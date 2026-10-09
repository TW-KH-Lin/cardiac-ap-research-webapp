import pytest

from app.fitting.mapping import GRANDITS_TO_CANONICAL, to_tor_changes


def test_full_nine_parameter_validation_mapping():
    values = {name: index + 1.0 for index, name in enumerate(GRANDITS_TO_CANONICAL)}
    changes = to_tor_changes(values)
    assert len(changes) == 9
    assert changes["g_NaCa"].native_value == 7
    assert changes["g_NaK"].native_value == 8


def test_missing_or_unknown_parameter_fails_loudly():
    with pytest.raises(ValueError, match="9/9"):
        to_tor_changes({"GNa": 1.0})
    with pytest.raises(ValueError, match="exactly nine"):
        to_tor_changes([1.0] * 7)
