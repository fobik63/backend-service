"""Shared enum types for ORM and API schemas."""

from enum import StrEnum


class SubscriptionStatus(StrEnum):
    """User subscription plans.

    Free remains the unpaid baseline. Paid commercial tiers match the
    public tariff grid (Старт / Про / Полугодовой / Годовая).
    """

    FREE = "Free"
    START = "Start"
    PRO = "Pro"
    HALF_YEAR = "HalfYear"
    YEAR = "Year"

    @classmethod
    def paid_values(cls) -> frozenset[str]:
        """Return subscription values that unlock paid generation engines."""

        return frozenset(
            {
                cls.START.value,
                cls.PRO.value,
                cls.HALF_YEAR.value,
                cls.YEAR.value,
            }
        )

    def is_paid(self) -> bool:
        """Whether this status is a paid commercial tariff."""

        return self.value in self.paid_values()


class PaymentStatus(StrEnum):
    """Lifecycle of a YooKassa payment record."""

    PENDING = "pending"
    WAITING_FOR_CAPTURE = "waiting_for_capture"
    SUCCEEDED = "succeeded"
    CANCELED = "canceled"
    FAILED = "failed"


class TariffCode(StrEnum):
    """Stable machine codes for the commercial tariff grid."""

    START = "start"
    PRO = "pro"
    HALF_YEAR = "half_year"
    YEAR = "year"
