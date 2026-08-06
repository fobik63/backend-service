"""Typed failures for the isolated stock-parser micro-module."""

from __future__ import annotations

from app.domain.stock_parser import ParserErrorKind, ParserMarketplace


class StockParserError(Exception):
    """Base parser failure counted by the circuit breaker."""

    def __init__(
        self,
        message: str,
        *,
        marketplace: ParserMarketplace,
        kind: ParserErrorKind,
    ) -> None:
        super().__init__(message)
        self.marketplace = marketplace
        self.kind = kind


class ParserHttpError(StockParserError):
    """Non-2xx response from a mobile JSON endpoint."""

    def __init__(
        self,
        message: str,
        *,
        marketplace: ParserMarketplace,
        status_code: int,
        kind: ParserErrorKind,
    ) -> None:
        super().__init__(message, marketplace=marketplace, kind=kind)
        self.status_code = status_code


class ParserSchemaError(StockParserError):
    """Marketplace changed JSON keys (schema drift / KeyError)."""

    def __init__(
        self,
        message: str,
        *,
        marketplace: ParserMarketplace,
        missing_keys: tuple[str, ...] = (),
        kind: ParserErrorKind = ParserErrorKind.SCHEMA_DRIFT,
    ) -> None:
        super().__init__(message, marketplace=marketplace, kind=kind)
        self.missing_keys = missing_keys


class ParserTransportError(StockParserError):
    """Network / proxy / timeout failure talking to mobile endpoints."""

    def __init__(
        self,
        message: str,
        *,
        marketplace: ParserMarketplace,
    ) -> None:
        super().__init__(
            message,
            marketplace=marketplace,
            kind=ParserErrorKind.TRANSPORT,
        )


class ParserStoppedError(StockParserError):
    """Raised when health is already broken/disabled — refuse further scrapes."""

    def __init__(
        self,
        message: str,
        *,
        marketplace: ParserMarketplace,
    ) -> None:
        super().__init__(
            message,
            marketplace=marketplace,
            kind=ParserErrorKind.UNKNOWN,
        )
