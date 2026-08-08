"""Global 404 JSON exception handler."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from starlette import status
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.http_errors import shape_http_exception_body
from app.main import _is_routing_not_found


def test_unknown_route_returns_json_404() -> None:
    """Routing 404s are Starlette HTTPException — register that base class."""

    probe = FastAPI()

    def is_routing_not_found(exc: StarletteHTTPException) -> bool:
        detail = exc.detail
        if detail in {"Not Found", "not found"}:
            return True
        return isinstance(detail, str) and detail.strip().lower() == "not found"

    @probe.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        if exc.status_code == status.HTTP_404_NOT_FOUND and is_routing_not_found(exc):
            return JSONResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                content={
                    "error": "Resource Not Found",
                    "code": 404,
                    "path": request.url.path,
                },
                headers=exc.headers,
            )
        return JSONResponse(
            status_code=exc.status_code,
            content=shape_http_exception_body(exc),
            headers=exc.headers,
        )

    @probe.get("/biz-missing")
    async def business_404() -> None:
        raise HTTPException(status_code=404, detail="Payment not found.")

    client = TestClient(probe)
    response = client.get("/definitely-missing-route-for-404-json")
    assert response.status_code == 404
    assert response.headers.get("content-type", "").startswith("application/json")
    assert response.json() == {
        "error": "Resource Not Found",
        "code": 404,
        "path": "/definitely-missing-route-for-404-json",
    }

    biz = client.get("/biz-missing")
    assert biz.status_code == 404
    body = biz.json()
    assert body["success"] is False
    assert body["detail"] == "Payment not found."
    assert body["error"] == {
        "code": "http_404",
        "message": "Payment not found.",
    }


def test_main_app_registers_starlette_http_exception_handler() -> None:
    from app.main import app

    assert StarletteHTTPException in app.exception_handlers
    # Status-code 404 must NOT be registered — it would shadow business 404 bodies.
    assert 404 not in app.exception_handlers


def test_is_routing_not_found_helpers() -> None:
    assert _is_routing_not_found(StarletteHTTPException(status_code=404, detail="Not Found"))
    assert _is_routing_not_found(StarletteHTTPException(status_code=404, detail="not found"))
    assert not _is_routing_not_found(
        StarletteHTTPException(status_code=404, detail="Payment not found.")
    )
