import pytest

from sqsx.helper import backoff_calculator_seconds, base64_to_dict, dict_to_base64, MAX_MESSAGE_SIZE


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


# New tests for message size validation


def test_dict_to_base64_raises_on_large_message():
    """Test that dict_to_base64 raises ValueError for messages exceeding MAX_MESSAGE_SIZE."""
    # Create a dictionary that will exceed MAX_MESSAGE_SIZE when encoded
    large_data = {"data": "x" * (MAX_MESSAGE_SIZE + 1)}

    with pytest.raises(ValueError) as exc_info:
        dict_to_base64(large_data)

    assert "Message too large" in str(exc_info.value)
    assert str(MAX_MESSAGE_SIZE) in str(exc_info.value)


def test_base64_to_dict_raises_on_large_encoded_message():
    """Test that base64_to_dict raises ValueError for encoded messages that are too large."""
    # Create a base64 string that's too large (even if the decoded size would be acceptable)

    large_data = "x" * int(MAX_MESSAGE_SIZE * 4 / 3 + 100)

    with pytest.raises(ValueError) as exc_info:
        base64_to_dict(large_data)

    assert "Encoded message too large" in str(exc_info.value)


def test_base64_to_dict_raises_on_large_decoded_message():
    """Test that base64_to_dict raises ValueError for decoded messages exceeding MAX_MESSAGE_SIZE."""
    import base64
    import json

    # Create a message that's within encoded size limit but exceeds decoded limit
    large_string = "x" * (MAX_MESSAGE_SIZE + 100)
    large_json = json.dumps({"data": large_string})
    encoded = base64.urlsafe_b64encode(large_json.encode()).decode()

    with pytest.raises(ValueError) as exc_info:
        base64_to_dict(encoded)

    assert "message too large" in str(exc_info.value).lower()


def test_base64_to_dict_raises_on_invalid_json():
    """Test that base64_to_dict raises appropriate error for invalid JSON."""
    import base64
    import json

    invalid_json = base64.urlsafe_b64encode(b"not valid json").decode()

    with pytest.raises(json.JSONDecodeError):
        base64_to_dict(invalid_json)


def test_base64_to_dict_raises_on_invalid_base64():
    """Test that base64_to_dict raises appropriate error for invalid base64."""
    import binascii

    with pytest.raises(binascii.Error):
        base64_to_dict("not valid base64!!!")


# Edge case tests for backoff calculator


@pytest.mark.parametrize(
    "retries,minimum,maximum,expected",
    [
        (100, 30, 180, 180),  # Very large retry count should cap at maximum
        (50, 1, 43200, 43200),  # Should cap at SQS_MAX_VISIBILITY_TIMEOUT
        (0, 100, 50, 50),  # When minimum > maximum, still caps at maximum (after SQS limit applied)
        (10, 1, 43200, 1024),  # 1 * 2^10 = 1024
        (20, 1, 50000, 43200),  # Should cap at 43200 (SQS limit) even if maximum is higher
    ],
)
def test_backoff_calculator_edge_cases(retries, minimum, maximum, expected):
    """Test backoff calculator with edge cases."""
    result = backoff_calculator_seconds(retries, minimum, maximum)
    assert result == expected
    assert result <= 43200  # Never exceed SQS limit


def test_backoff_calculator_respects_sqs_limit():
    """Test that backoff calculator never exceeds SQS maximum visibility timeout."""
    # Try with a very large maximum
    result = backoff_calculator_seconds(100, 1, 100000)
    assert result == 43200  # SQS_MAX_VISIBILITY_TIMEOUT
