import numpy as np
import pytest

from app.core.units import current_for_display, stimulus_na_to_af, time_to_ms_factor


def test_time_and_stimulus_conversion():
    assert time_to_ms_factor("[s]") == 1000
    assert time_to_ms_factor("[ms]") == 1
    assert stimulus_na_to_af(2.65, 50) == -53
    with pytest.raises(ValueError):
        stimulus_na_to_af(1, 0)


def test_current_unit_conversion_is_explicit():
    values, unit, method = current_for_display(np.array([1.0]), "[A/F]", 50)
    assert values[0] == 50 and unit == "pA" and "50 pF" in method
    values, unit, method = current_for_display(np.array([1.0]), "unknown", 50)
    assert unit == "unknown" and "no verified conversion" in method
