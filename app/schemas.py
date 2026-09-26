"""Request bodies accepted by the JSON API (validated by Pydantic)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class BoxIn(BaseModel):
    """A box in full-resolution image coordinates."""

    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class NewDetectionIn(BoxIn):
    source_image_id: int


class MergeIn(BaseModel):
    detection_ids: list[int] = Field(min_length=2)


class SplitIn(BaseModel):
    mode: Literal["auto", "vertical", "horizontal"] = "auto"


class PinUpdateIn(BaseModel):
    """Editable catalog fields. Omitted fields are left unchanged."""

    title: str | None = Field(default=None, max_length=300)
    description: str | None = Field(default=None, max_length=5000)
    category: str | None = Field(default=None, max_length=100)
    subcategory: str | None = Field(default=None, max_length=100)
    tags: list[str] | None = None
    notes: str | None = Field(default=None, max_length=5000)
    quantity: int | None = Field(default=None, ge=0)
    purchase_price: float | None = Field(default=None, ge=0)
    selling_price: float | None = Field(default=None, ge=0)
    clear_purchase_price: bool = False
    clear_selling_price: bool = False

    @field_validator("tags")
    @classmethod
    def clean_tags(cls, tags: list[str] | None) -> list[str] | None:
        if tags is None:
            return None
        cleaned: list[str] = []
        for tag in tags:
            tag = " ".join(tag.strip().lower().split())
            if tag and tag not in cleaned:
                cleaned.append(tag[:60])
        return cleaned


class ExportIn(BaseModel):
    formats: list[Literal["csv", "json", "html"]] = ["csv", "json", "html"]
