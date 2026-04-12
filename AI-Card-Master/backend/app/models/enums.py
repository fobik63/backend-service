"""Shared enum types for ORM and API schemas."""

from enum import StrEnum


class SubscriptionStatus(StrEnum):
    """User subscription plans."""

    FREE = "Free"
    PRO = "Pro"
