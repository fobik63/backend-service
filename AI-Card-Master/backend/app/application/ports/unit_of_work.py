"""Transaction boundary used by multi-repository application services."""

from __future__ import annotations

from typing import Protocol


class UnitOfWorkPort(Protocol):
    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...
