import base64
import json


def dict_to_base64(data: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(data).encode()).decode()


def base64_to_dict(data: str) -> dict:
    return json.loads(base64.urlsafe_b64decode(data).decode())


def backoff_calculator_seconds(retries: int, minimum: int, maximum: int) -> int:
    maximum = min(maximum, 43200)
    return min(minimum * 2**retries, maximum)
