import pytest

from sqsx.helper import backoff_calculator_seconds, base64_to_dict, dict_to_base64


def test_dict_to_base64():
    expected_result = "eyJhcmdzIjogWzEsIDIsIDNdLCAia3dhcmdzIjogeyJhIjogMSwgImIiOiAyLCAiYyI6IDN9fQ=="
    data = {
        "args": [1, 2, 3],
        "kwargs": {"a": 1, "b": 2, "c": 3},
    }

    assert dict_to_base64(data) == expected_result


def test_base64_to_dict():
    expected_result = {
        "args": [1, 2, 3],
        "kwargs": {"a": 1, "b": 2, "c": 3},
    }
    data = "eyJhcmdzIjogWzEsIDIsIDNdLCAia3dhcmdzIjogeyJhIjogMSwgImIiOiAyLCAiYyI6IDN9fQ=="

    assert base64_to_dict(data) == expected_result


@pytest.mark.parametrize(
    "retries,minimum,maximum,expected",
    [(0, 30, 180, 30), (1, 30, 180, 60), (2, 30, 180, 120), (3, 30, 180, 180), (4, 30, 180, 180)],
)
def test_backoff_calculator(retries, minimum, maximum, expected):
    assert backoff_calculator_seconds(retries, minimum, maximum) == expected
