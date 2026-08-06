"""Strict JSON structure health-check for marketplace mobile API responses.

If critical keys disappear (e.g. `stocks`), the parser fails fast with
ParserSchemaError so the circuit breaker can trip without crashing FastAPI.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.domain.stock_parser import (
    OZON_REQUIRED_PRODUCT_KEYS,
    WB_REQUIRED_PRODUCT_KEYS,
    WB_REQUIRED_SIZE_KEYS,
    ParserErrorKind,
    ParserMarketplace,
)
from app.infrastructure.stock_parser.exceptions import ParserSchemaError


def _as_mapping(value: object, *, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ParserSchemaError(
            f"Expected object at {path}, got {type(value).__name__}",
            marketplace=ParserMarketplace.WILDBERRIES,
            missing_keys=(path,),
            kind=ParserErrorKind.SCHEMA_DRIFT,
        )
    return value  # type: ignore[return-value]


def require_keys(
    payload: Mapping[str, Any],
    *,
    required: frozenset[str] | set[str] | Sequence[str],
    marketplace: ParserMarketplace,
    path: str = "$",
) -> None:
    """Raise ParserSchemaError when any required key is missing."""

    missing = tuple(sorted(key for key in required if key not in payload))
    if missing:
        raise ParserSchemaError(
            f"Marketplace JSON schema drift at {path}: missing keys {missing}",
            marketplace=marketplace,
            missing_keys=missing,
            kind=ParserErrorKind.SCHEMA_DRIFT,
        )


def dig(payload: Mapping[str, Any], *keys: str, marketplace: ParserMarketplace) -> Any:
    """Traverse nested dicts; convert KeyError into ParserSchemaError."""

    current: Any = payload
    walked: list[str] = []
    for key in keys:
        walked.append(key)
        if not isinstance(current, Mapping):
            raise ParserSchemaError(
                f"Expected object before key '{key}' (path={'.'.join(walked)})",
                marketplace=marketplace,
                missing_keys=(key,),
                kind=ParserErrorKind.KEY_ERROR,
            )
        try:
            current = current[key]
        except KeyError as exc:
            raise ParserSchemaError(
                f"Missing key '{key}' at path {'.'.join(walked)}",
                marketplace=marketplace,
                missing_keys=(key,),
                kind=ParserErrorKind.KEY_ERROR,
            ) from exc
    return current


def assert_wildberries_card_payload(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    """Validate WB mobile card.detail product shape (incl. sizes[].stocks)."""

    marketplace = ParserMarketplace.WILDBERRIES
    products = dig(payload, "data", "products", marketplace=marketplace)
    if not isinstance(products, list) or not products:
        raise ParserSchemaError(
            "WB mobile response has empty data.products",
            marketplace=marketplace,
            missing_keys=("data.products",),
            kind=ParserErrorKind.SCHEMA_DRIFT,
        )
    product = _as_mapping(products[0], path="data.products[0]")
    # Override marketplace on type errors from helper — already WB.
    if not isinstance(products[0], Mapping):
        raise ParserSchemaError(
            "WB product entry is not an object",
            marketplace=marketplace,
            missing_keys=("data.products[0]",),
        )
    require_keys(
        product,
        required=WB_REQUIRED_PRODUCT_KEYS,
        marketplace=marketplace,
        path="data.products[0]",
    )
    sizes = product["sizes"]
    if not isinstance(sizes, list) or not sizes:
        raise ParserSchemaError(
            "WB product has no sizes[] (stocks live under sizes)",
            marketplace=marketplace,
            missing_keys=("sizes",),
            kind=ParserErrorKind.SCHEMA_DRIFT,
        )
    for index, size in enumerate(sizes):
        if not isinstance(size, Mapping):
            raise ParserSchemaError(
                f"WB sizes[{index}] is not an object",
                marketplace=marketplace,
                missing_keys=(f"sizes[{index}]",),
            )
        require_keys(
            size,
            required=WB_REQUIRED_SIZE_KEYS,
            marketplace=marketplace,
            path=f"data.products[0].sizes[{index}]",
        )
        stocks = size["stocks"]
        if not isinstance(stocks, list):
            raise ParserSchemaError(
                f"WB sizes[{index}].stocks must be a list",
                marketplace=marketplace,
                missing_keys=(f"sizes[{index}].stocks",),
                kind=ParserErrorKind.SCHEMA_DRIFT,
            )
    return product


def assert_ozon_product_payload(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    """Validate Ozon mobile composer / product JSON for critical stock keys."""

    marketplace = ParserMarketplace.OZON
    # Prefer explicit product widget; fall back to flattened envelope used in tests.
    if "product" in payload and isinstance(payload["product"], Mapping):
        product = payload["product"]
    elif all(key in payload for key in OZON_REQUIRED_PRODUCT_KEYS):
        product = payload
    else:
        # Composer pages nest widgets under widgetStates / page.
        product = _extract_ozon_product_widget(payload)

    require_keys(
        product,
        required=OZON_REQUIRED_PRODUCT_KEYS,
        marketplace=marketplace,
        path="product",
    )
    stocks = product["stocks"]
    if not isinstance(stocks, (list, Mapping, int)):
        raise ParserSchemaError(
            "Ozon product.stocks must be list|object|int",
            marketplace=marketplace,
            missing_keys=("stocks",),
            kind=ParserErrorKind.SCHEMA_DRIFT,
        )
    return product


def _extract_ozon_product_widget(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    """Best-effort walk of Ozon composer JSON for a product-like object."""

    marketplace = ParserMarketplace.OZON
    candidates: list[Mapping[str, Any]] = []

    def _walk(node: Any) -> None:
        if isinstance(node, Mapping):
            if OZON_REQUIRED_PRODUCT_KEYS.issubset(node.keys()):
                candidates.append(node)
            for value in node.values():
                _walk(value)
        elif isinstance(node, list):
            for item in node:
                _walk(item)

    _walk(payload)
    if not candidates:
        raise ParserSchemaError(
            "Ozon mobile JSON has no product object with required keys "
            f"{tuple(sorted(OZON_REQUIRED_PRODUCT_KEYS))}",
            marketplace=marketplace,
            missing_keys=tuple(sorted(OZON_REQUIRED_PRODUCT_KEYS)),
            kind=ParserErrorKind.SCHEMA_DRIFT,
        )
    return candidates[0]
