"""Serialization responsibilities; routes are registered by the application factory."""
import json


def safe_json_list(value):
    try:
        parsed = json.loads(value or "[]")
    except (TypeError, ValueError):
        return []

    return parsed if isinstance(parsed, list) else []



def safe_json_str_list(value):
    return [
        item
        for item in safe_json_list(value)
        if isinstance(item, str) and item.strip()
    ]



def safe_json_dict_list(value):
    return [
        item
        for item in safe_json_list(value)
        if isinstance(item, dict)
    ]



def safe_json_dict(value):
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}

    return parsed if isinstance(parsed, dict) else {}
