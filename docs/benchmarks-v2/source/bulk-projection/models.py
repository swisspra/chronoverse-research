"""Validated public inputs; UTC timestamps are canonical ledger values."""
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Plane = Literal["fact", "report", "belief", "theory", "forecast", "scenario"]
PLANES = ["fact", "report", "belief", "theory", "forecast", "scenario"]
DEFAULT_VALID = "2026-09-12T00:00:00Z"
DEFAULT_KNOWN = "2026-09-12T23:59:59Z"


def timestamp(value: str) -> str:
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt = dt.astimezone(timezone.utc)
        return dt.isoformat(timespec="microseconds").replace("+00:00", "Z")
    except (ValueError, AttributeError, OverflowError) as exc:
        raise ValueError("Expected an ISO 8601 date or datetime") from exc


def now() -> str:
    return timestamp(datetime.now(timezone.utc).isoformat())


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, validate_default=True)


class EvidenceInput(InputModel):
    title: str = Field(min_length=1, max_length=300)
    url: str | None = Field(default=None, max_length=2000)
    text: str = Field(min_length=1, max_length=100_000)
    recorded_at: str | None = None
    synthetic: bool = False

    @field_validator("recorded_at")
    @classmethod
    def validate_time(cls, value):
        return timestamp(value) if value is not None else value

    @field_validator("url")
    @classmethod
    def validate_url(cls, value):
        if value is not None and not value.startswith(("https://", "http://")):
            raise ValueError("Evidence URL must use http:// or https://")
        return value


class AssertionInput(InputModel):
    id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")
    subject: str = Field(min_length=1, max_length=300)
    predicate: str = Field(min_length=1, max_length=200)
    object: str = Field(min_length=1, max_length=1000)
    world: str = Field(default="main", min_length=1, max_length=100)
    plane: Plane = "fact"
    perspective: str = Field(default="general", min_length=1, max_length=100)
    valid_from: str
    valid_to: str | None = None
    recorded_at: str | None = None
    summary: str = Field(default="", max_length=5000)
    evidence: list[EvidenceInput] = Field(min_length=1, max_length=20)

    @field_validator("world", "perspective")
    @classmethod
    def reserve_all(cls, value):
        if value == "all":
            raise ValueError("'all' is reserved for query filters")
        return value

    @field_validator("valid_from", "valid_to", "recorded_at")
    @classmethod
    def validate_time(cls, value):
        return timestamp(value) if value is not None else value

    @model_validator(mode="after")
    def check_interval(self):
        if self.valid_to is not None and self.valid_to <= self.valid_from:
            raise ValueError("valid_to must be later than valid_from (half-open interval)")
        return self


class EventInput(InputModel):
    id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")
    type: Literal["supersede", "correct", "retract"]
    effective_at: str
    recorded_at: str | None = None
    reason: str = Field(min_length=1, max_length=5000)
    source: str = Field(min_length=1, max_length=2000)
    replacement_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")

    @field_validator("effective_at", "recorded_at")
    @classmethod
    def validate_time(cls, value):
        return timestamp(value) if value is not None else value

    @model_validator(mode="after")
    def check_replacement(self):
        if self.type in ("supersede", "correct") and not self.replacement_id:
            raise ValueError("supersede/correct requires replacement_id")
        if self.type == "retract" and self.replacement_id:
            raise ValueError("retract does not accept replacement_id")
        return self


class QueryRequest(InputModel):
    query: str = Field(default="", max_length=2000)
    valid_at: str = DEFAULT_VALID
    known_at: str = DEFAULT_KNOWN
    world: str = Field(default="main", min_length=1, max_length=100)
    plane: Literal["all", "fact", "report", "belief", "theory", "forecast", "scenario"] = "all"
    perspective: str = Field(default="all", min_length=1, max_length=100)
    limit: int = Field(default=20, ge=1, le=100, strict=True)
    include_retired: bool = False

    @field_validator("valid_at", "known_at")
    @classmethod
    def validate_time(cls, value):
        return timestamp(value)
