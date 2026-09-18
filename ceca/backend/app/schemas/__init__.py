"""Pydantic request and response models.

One module per area. ORM instances are never returned from a router: they are
mapped into the explicit output schemas declared here.
"""

from app.schemas.common import (
    Acknowledgement,
    ErrorDetail,
    LocalizedText,
    PageParams,
    PageResponse,
    Schema,
)

__all__ = [
    "Acknowledgement",
    "ErrorDetail",
    "LocalizedText",
    "PageParams",
    "PageResponse",
    "Schema",
]
