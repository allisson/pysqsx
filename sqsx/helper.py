import base64
import json

# Constants
MAX_MESSAGE_SIZE = 256 * 1024  # 256KB (SQS limit)
SQS_MAX_VISIBILITY_TIMEOUT = 43200  # 12 hours in seconds


def dict_to_base64(data: dict) -> str:
    """
    Convert a dictionary to a base64-encoded string.

    Args:
        data: Dictionary to encode

    Returns:
        Base64-encoded string

    Raises:
        ValueError: If the encoded message exceeds MAX_MESSAGE_SIZE
    """
    json_str = json.dumps(data)
    json_bytes = json_str.encode()

    if len(json_bytes) > MAX_MESSAGE_SIZE:
        raise ValueError(f"Message too large: {len(json_bytes)} bytes (max: {MAX_MESSAGE_SIZE})")

    return base64.urlsafe_b64encode(json_bytes).decode()


def base64_to_dict(data: str) -> dict:
    """
    Convert a base64-encoded string back to a dictionary.

    Args:
        data: Base64-encoded string

    Returns:
        Decoded dictionary

    Raises:
        ValueError: If the message is too large or invalid format
        UnicodeDecodeError: If the decoded data is not valid UTF-8
    """
    # Check base64 encoded size (account for base64 expansion)
    if len(data) > MAX_MESSAGE_SIZE * 4 / 3:
        raise ValueError(f"Encoded message too large: {len(data)} bytes")

    decoded = base64.urlsafe_b64decode(data)

    # Check decoded size
    if len(decoded) > MAX_MESSAGE_SIZE:
        raise ValueError(f"Decoded message too large: {len(decoded)} bytes (max: {MAX_MESSAGE_SIZE})")

    return json.loads(decoded.decode())


def backoff_calculator_seconds(retries: int, minimum: int, maximum: int) -> int:
    """
    Calculate exponential backoff timeout in seconds.

    Args:
        retries: Number of retry attempts (0-indexed)
        minimum: Minimum backoff in seconds
        maximum: Maximum backoff in seconds

    Returns:
        Calculated timeout in seconds, capped at SQS_MAX_VISIBILITY_TIMEOUT
    """
    maximum = min(maximum, SQS_MAX_VISIBILITY_TIMEOUT)
    return min(minimum * 2**retries, maximum)
