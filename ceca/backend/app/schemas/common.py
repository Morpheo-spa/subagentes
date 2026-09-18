"""Building blocks every other schema module reuses."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

#: Hard ceiling on page size, so a client cannot ask for the whole archive at once.
MAX_PAGE_SIZE = 200
DEFAULT_PAGE_SIZE = 25


class Schema(BaseModel):
    """Base for every request and response model in the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class LocalizedText(Schema):
    """A catalogue label served in both languages, so the client picks."""

    es: str
    en: str


@dataclass(frozen=True, slots=True)
class PageParams:
    """Normalised pagination request. Built by the router dependency."""

    page: int = 1
    page_size: int = DEFAULT_PAGE_SIZE

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        return self.page_size


class PageResponse[ItemT](Schema):
    """The only shape a collection endpoint may return."""

    items: list[ItemT]
    total: int
    page: int
    page_size: int

    @classmethod
    def of(cls, items: list[ItemT], total: int, params: PageParams) -> PageResponse[ItemT]:
        return cls(items=items, total=total, page=params.page, page_size=params.page_size)


class Acknowledgement(Schema):
    """Response of an action that changes state but has nothing to return."""

    ok: bool = True
    code: str | None = None


class ErrorDetail(Schema):
    """Mirror of ``app.errors.error_detail`` for per-item batch results."""

    code: str
    message: str
    params: dict[str, Any] = Field(default_factory=dict)
