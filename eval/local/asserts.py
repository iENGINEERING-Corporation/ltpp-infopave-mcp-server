"""A tiny assertion language for gold-question checks, so they can live in JSON.

Each assertion is {"path": "data.matches.0.new_bridge_id", "op": "==", "value": 17762}. Paths walk
dicts by key and lists by index. Ops: == != >= <= > < in contains exists len>=
"""

from typing import Any

_MISSING = object()


def get_path(obj: Any, path: str) -> Any:
    for part in path.split("."):
        if isinstance(obj, list):
            try:
                obj = obj[int(part)]
            except (ValueError, IndexError):
                return _MISSING
        elif isinstance(obj, dict) and part in obj:
            obj = obj[part]
        else:
            return _MISSING
    return obj


def check(envelope: dict[str, Any], assertion: dict[str, Any]) -> tuple[bool, str]:
    """Return (passed, message)."""
    path, op, expected = assertion["path"], assertion["op"], assertion.get("value")
    actual = get_path(envelope, path)
    label = f"{path} {op} {expected!r}"
    if op == "exists":
        return actual is not _MISSING, label
    if actual is _MISSING:
        return False, f"{label} (path not found)"
    try:
        if op == "==":
            ok = actual == expected
        elif op == "!=":
            ok = actual != expected
        elif op == ">=":
            ok = actual >= expected
        elif op == "<=":
            ok = actual <= expected
        elif op == ">":
            ok = actual > expected
        elif op == "<":
            ok = actual < expected
        elif op == "in":
            ok = actual in expected
        elif op == "len>=":
            ok = len(actual) >= expected
        elif op == "contains":  # substring of a string, or of any string in a list
            ok = expected in actual if isinstance(actual, str) else any(expected in str(x) for x in actual)
        else:
            return False, f"{label} (unknown op)"
    except TypeError:
        return False, f"{label} (cannot compare {actual!r})"
    return ok, label if ok else f"{label} (got {actual!r})"
