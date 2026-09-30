"""Shared helpers for metadata provider search implementations."""

from __future__ import annotations

from typing import Any


def format_provider_error(name: str, message: str) -> str:
    """Turn provider exceptions into a concise, user-facing message."""
    lowered = message.lower()
    if "429" in message or "rate limit" in lowered or "too many requests" in lowered:
        return f"{name}: rate limited by the provider, try again in a few minutes."
    return f"{name}: {message}"


def titles_match(first: str, second: str) -> bool:
    """Compare titles while ignoring case, punctuation, and whitespace."""
    normalize = lambda value: "".join(char.lower() for char in value if char.isalnum())
    normalized_first = normalize(first)
    normalized_second = normalize(second)
    return bool(normalized_first) and normalized_first == normalized_second


def merge_search_result(
    results: list[dict[str, Any]],
    candidate: dict[str, Any],
    *,
    ignored_fields: frozenset[str] = frozenset({"provider", "provider_id", "title"}),
) -> None:
    """Merge a provider result into an existing title or append it.

    Provider-specific identity fields are never overwritten. Empty values in
    an existing result are filled from later providers when available.
    """
    for existing in results:
        if not titles_match(existing["title"], candidate["title"]):
            continue

        for key, value in candidate.items():
            if key in ignored_fields:
                continue
            if not existing.get(key) and value:
                existing[key] = value
        return

    results.append(candidate)
