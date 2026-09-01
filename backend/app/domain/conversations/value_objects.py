"""Small pure-Python values shared by conversation entities."""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.domain.conversations.errors import InvalidDomainValueError


def new_domain_id() -> UUID:
    """Return an unpredictable UUID suitable for a new domain entity."""

    return uuid4()


def require_uuid(value: UUID, *, field_name: str) -> UUID:
    """Validate an entity identifier without coercing unrelated values."""

    if not isinstance(value, UUID):
        raise InvalidDomainValueError(f"{field_name} must be a UUID")
    return value


def utc_now() -> datetime:
    """Return the current timezone-aware UTC time."""

    return datetime.now(UTC)


def as_utc(value: datetime, *, field_name: str) -> datetime:
    """Normalize an aware timestamp to UTC and reject naive timestamps."""

    if not isinstance(value, datetime):
        raise InvalidDomainValueError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise InvalidDomainValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def resolve_utc(value: datetime | None, *, field_name: str) -> datetime:
    """Use an injected aware timestamp or generate the current UTC time."""

    return utc_now() if value is None else as_utc(value, field_name=field_name)


def positive_sequence(value: int, *, field_name: str) -> int:
    """Require a positive, non-boolean sequence number."""

    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise InvalidDomainValueError(f"{field_name} must be a positive integer")
    return value


def optional_text(
    value: str | None,
    *,
    field_name: str,
    max_length: int,
) -> str | None:
    """Normalize optional bounded metadata without accepting blank values."""

    if value is None:
        return None
    if not isinstance(value, str):
        raise InvalidDomainValueError(f"{field_name} must be text")
    normalized = value.strip()
    if not normalized:
        raise InvalidDomainValueError(f"{field_name} must not be blank")
    if len(normalized) > max_length:
        raise InvalidDomainValueError(
            f"{field_name} must not exceed {max_length} characters"
        )
    return normalized


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """Safe normalized token counts associated with a completed turn."""

    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None

    def __post_init__(self) -> None:
        for field_name, value in (
            ("prompt_tokens", self.prompt_tokens),
            ("completion_tokens", self.completion_tokens),
            ("total_tokens", self.total_tokens),
        ):
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 0
            ):
                raise InvalidDomainValueError(
                    f"{field_name} must be a non-negative integer"
                )

