"""Domain contracts for CoinGuard: input math, HTTP errors, hold results.

AI-coins are whole units. All spend/credit amounts must be strict ``int``
values in ``(0, max_operation_coins]``. HTTP statuses are part of the
public API contract (402 / 400 / 409 / 429).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Final, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# PostgreSQL ``INTEGER`` upper bound — overflow past this is a DB error.
PG_INT32_MAX: Final[int] = 2_147_483_647
DEFAULT_MAX_OPERATION_COINS: Final[int] = 1_000_000
DEFAULT_SPEND_PER_MINUTE: Final[int] = 30
DEFAULT_RATE_WINDOW_SECONDS: Final[int] = 60

CoinOperationKind = Literal["spend", "credit", "hold"]


class StrictCoinModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class CoinGuardErrorBody(StrictCoinModel):
    """Stable JSON error payload for CoinGuard HTTP handlers."""

    code: str
    message: str
    status_code: int = Field(..., ge=400, le=429)
    required_coins: int | None = Field(default=None, ge=0)
    balance: int | None = Field(default=None, ge=0)
    missing_coins: int | None = Field(default=None, ge=0)
    max_operation_coins: int | None = Field(default=None, ge=1)
    retry_after_seconds: int | None = Field(default=None, ge=1)
    hold_id: UUID | None = None


class HoldResult(StrictCoinModel):
    """Outcome of ``validate_and_hold`` (including idempotent replay)."""

    hold_id: UUID
    account_id: UUID
    amount_held: int = Field(..., ge=0)
    remaining_amount: int = Field(..., ge=0)
    captured_amount: int = Field(..., ge=0)
    new_balance: int = Field(..., ge=0)
    status: str
    already_processed: bool = False
    idempotency_key: str | None = None


class SpendResult(StrictCoinModel):
    """Outcome of ``commit_spend`` / ``rollback_spend``."""

    hold_id: UUID
    account_id: UUID
    step_amount: int = Field(..., ge=0)
    remaining_amount: int = Field(..., ge=0)
    captured_amount: int = Field(..., ge=0)
    refunded_amount: int = Field(default=0, ge=0)
    new_balance: int = Field(..., ge=0)
    status: str
    already_processed: bool = False
    generated_kept: bool = True


class BatchSpendResult(StrictCoinModel):
    """Partial batch after stepwise capture; leftover coins are refunded."""

    hold_id: UUID
    account_id: UUID
    units_requested: int = Field(..., ge=0)
    units_committed: int = Field(..., ge=0)
    coins_captured: int = Field(..., ge=0)
    coins_refunded: int = Field(..., ge=0)
    new_balance: int = Field(..., ge=0)
    status: str
    stopped_reason: str | None = None


class CoinGuardError(Exception):
    """Base CoinGuard failure with a Russian operator-facing message."""

    status_code: int = 400
    code: str = "coin_guard_error"

    def __init__(self, message: str, **fields: Any) -> None:
        self.message = message
        self.fields = fields
        super().__init__(message)

    def to_error_body(self) -> CoinGuardErrorBody:
        return CoinGuardErrorBody(
            code=self.code,
            message=self.message,
            status_code=self.status_code,
            required_coins=_optional_int(self.fields.get("required_coins")),
            balance=_optional_int(self.fields.get("balance")),
            missing_coins=_optional_int(self.fields.get("missing_coins")),
            max_operation_coins=_optional_int(self.fields.get("max_operation_coins")),
            retry_after_seconds=_optional_int(self.fields.get("retry_after_seconds")),
            hold_id=self.fields.get("hold_id")
            if isinstance(self.fields.get("hold_id"), UUID)
            else None,
        )

    def to_http_detail(self) -> dict[str, Any]:
        return self.to_error_body().model_dump(mode="json", exclude_none=True)


class CoinAmountInvalidError(CoinGuardError):
    status_code = 400
    code = "invalid_coin_amount"


class CoinNotIntegerError(CoinAmountInvalidError):
    code = "coin_amount_not_integer"


class CoinOverflowError(CoinAmountInvalidError):
    code = "coin_amount_overflow"


class CoinIdempotencyKeyError(CoinAmountInvalidError):
    code = "invalid_idempotency_key"


class CoinAccountNotFoundError(CoinAmountInvalidError):
    code = "account_not_found"


class ZeroBalanceError(CoinGuardError):
    status_code = 402
    code = "zero_balance"


class InsufficientBalanceError(CoinGuardError):
    status_code = 402
    code = "insufficient_coins"


class AccountBlockedError(CoinGuardError):
    status_code = 409
    code = "account_blocked"


class AccountFrozenError(CoinGuardError):
    status_code = 409
    code = "account_frozen"


class CoinIdempotencyConflictError(CoinGuardError):
    status_code = 409
    code = "idempotency_conflict"


class CoinHoldConflictError(CoinGuardError):
    status_code = 409
    code = "coin_hold_conflict"


class CoinRateLimitError(CoinGuardError):
    status_code = 429
    code = "coin_spend_rate_limited"


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_idempotency_uuid(value: object) -> str:
    """Require a UUID (object or canonical string). Empty / malformed → 400."""

    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            raise CoinIdempotencyKeyError(
                "Ключ идемпотентности обязателен и должен быть UUID."
            )
        try:
            return str(UUID(cleaned))
        except ValueError as exc:
            raise CoinIdempotencyKeyError(
                "Ключ идемпотентности должен быть корректным UUID."
            ) from exc
    raise CoinIdempotencyKeyError(
        "Ключ идемпотентности должен быть корректным UUID."
    )


def parse_positive_coin_amount(
    value: object,
    *,
    max_operation_coins: int = DEFAULT_MAX_OPERATION_COINS,
    kind: CoinOperationKind = "spend",
) -> int:
    """Reject negatives, zero, floats, strings, bools, and overflow."""

    operation_label = {
        "spend": "списания",
        "credit": "пополнения",
        "hold": "заморозки",
    }[kind]

    if isinstance(value, bool) or value is True or value is False:
        raise CoinNotIntegerError(
            "Сумма операции должна быть целым числом; логические значения недопустимы."
        )
    if isinstance(value, float) or isinstance(value, Decimal):
        raise CoinNotIntegerError(
            "Коины — целые числа. Дробные значения (float/Decimal) недопустимы."
        )
    if isinstance(value, str):
        raise CoinNotIntegerError(
            "Сумма операции должна быть целым числом, а не строкой."
        )
    if isinstance(value, bytes):
        raise CoinNotIntegerError(
            "Сумма операции должна быть целым числом, а не строкой/байтами."
        )
    if not isinstance(value, int):
        raise CoinNotIntegerError(
            "Сумма операции должна быть целым числом (int)."
        )

    if value < 0:
        raise CoinAmountInvalidError(
            f"Отрицательные суммы {operation_label} запрещены."
        )
    if value == 0:
        raise CoinAmountInvalidError(
            f"Сумма {operation_label} должна быть больше нуля."
        )

    cap = min(int(max_operation_coins), PG_INT32_MAX)
    if value > cap:
        raise CoinOverflowError(
            "Сумма операции превышает максимально допустимый лимит за одну операцию.",
            max_operation_coins=cap,
        )
    return int(value)


def safe_multiply_coins(unit: int, quantity: int, *, max_operation_coins: int) -> int:
    """``unit * quantity`` with overflow protection (batch freeze)."""

    if quantity < 1:
        raise CoinAmountInvalidError("Количество единиц в пакете должно быть >= 1.")
    cap = min(int(max_operation_coins), PG_INT32_MAX)
    if unit > cap or quantity > cap:
        raise CoinOverflowError(
            "Пакетная операция превышает максимально допустимый лимит.",
            max_operation_coins=cap,
        )
    if unit > PG_INT32_MAX // quantity:
        raise CoinOverflowError(
            "Произведение стоимости и количества приводит к переполнению целого.",
            max_operation_coins=cap,
        )
    total = unit * quantity
    if total > cap:
        raise CoinOverflowError(
            "Сумма пакетной заморозки превышает максимально допустимый лимит.",
            max_operation_coins=cap,
        )
    return total
