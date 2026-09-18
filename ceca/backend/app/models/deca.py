"""The DECA field catalogue.

Which fields a delivery note must carry is a *legal* question whose answer
changes. It lives in data, seeded from ``app/i18n/deca_fields.json``, never in
an ``if`` in the code.
"""

from __future__ import annotations

import enum

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class DecaFieldType(str, enum.Enum):
    STRING = "string"
    TEXT = "text"
    NUMBER = "number"
    DECIMAL = "decimal"
    DATE = "date"
    DATETIME = "datetime"
    BOOLEAN = "boolean"
    ENUM = "enum"


class DecaFieldDefinition(Base, TimestampMixin):
    """One field a delivery note must (or may) carry."""

    __tablename__ = "deca_field_definitions"

    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    label_es: Mapped[str] = mapped_column(String(160), nullable=False)
    label_en: Mapped[str] = mapped_column(String(160), nullable=False)
    help_es: Mapped[str | None] = mapped_column(Text)
    help_en: Mapped[str | None] = mapped_column(Text)
    data_type: Mapped[DecaFieldType] = mapped_column(
        String(16), nullable=False, default=DecaFieldType.STRING
    )
    is_required: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    max_length: Mapped[int | None] = mapped_column(Integer)
    pattern: Mapped[str | None] = mapped_column(String(255))
    #: Allowed values for ENUM fields, as a JSON array in text form.
    choices: Mapped[str | None] = mapped_column(Text)
    #: The article of the regulation that demands this field. Empty = our own addition.
    legal_reference: Mapped[str | None] = mapped_column(String(160))
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    #: Bumped whenever the catalogue changes, stamped onto each document.
    catalog_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
