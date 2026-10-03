"""Shared response models for paginated library endpoints."""

# Pylint associates the upload-route similarity with this shared schema module;
# the routes intentionally retain separate media/game validation paths.
# pylint: disable=duplicate-code

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    """A page of results plus the authoritative total matching the query."""

    items: list[T]
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(gt=0)
    status_counts: dict[str, int] = Field(default_factory=dict)
