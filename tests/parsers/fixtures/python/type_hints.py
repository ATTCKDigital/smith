from typing import Optional


def find(needle: str, haystack: list[str]) -> Optional[int]:
    """Return the first index, or None."""
    try:
        return haystack.index(needle)
    except ValueError:
        return None


def group(values: dict[str, list[int]]) -> dict[str, int]:
    return {k: sum(v) for k, v in values.items()}


def with_default(x: int = 42, *args: str, **kwargs: int) -> None:
    pass
