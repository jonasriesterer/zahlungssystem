"""Hilfsfunktionen für die Worker."""


from typing import Any, Mapping


def _as_mapping(value: Any) -> Mapping[str, Any]:
    """Return a plain mapping from dict-like SDK values."""

    if hasattr(value, "to_dict"):
        value = value.to_dict()
    if isinstance(value, Mapping):
        return value
    return {}


def _as_bool(value: Any, default: bool = False) -> bool:
    """Normalize boolean-like Camunda variables."""

    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y", "on"}:
            return True
        if normalized in {"false", "0", "no", "n", "off", ""}:
            return False
    return default
