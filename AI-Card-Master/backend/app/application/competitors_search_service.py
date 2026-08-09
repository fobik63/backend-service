"""Application service: keyword → TOP-N WB competitor cards from search.wb.ru."""

from __future__ import annotations

from app.application.ports.competitors_search import CompetitorKeywordDiscoveryPort
from app.domain.competitors_search import (
    CompetitorsSearchRequest,
    CompetitorsSearchResult,
    hits_to_search_result,
)
from app.infrastructure.stock_parser.exceptions import (
    ParserHttpError,
    ParserSchemaError,
    ParserTransportError,
)


class CompetitorsSearchError(Exception):
    """Base competitors-search failure."""


class CompetitorsSearchValidationError(CompetitorsSearchError):
    """Invalid query or empty search result."""


class CompetitorsSearchUpstreamError(CompetitorsSearchError):
    """Wildberries search API unavailable / transport failure."""


class CompetitorsSearchService:
    """Fetch TOP-N competitor cards (article, price, rating, feedbacks) by keyword."""

    def __init__(self, discovery: CompetitorKeywordDiscoveryPort) -> None:
        self._discovery = discovery

    async def search(
        self,
        request: CompetitorsSearchRequest,
    ) -> CompetitorsSearchResult:
        """Call WB search API and return ranked competitor cards."""

        try:
            hits = await self._discovery.discover_by_query(
                query=request.query,
                limit=request.limit,
            )
        except ParserSchemaError as exc:
            raise CompetitorsSearchValidationError(str(exc)) from exc
        except (ParserHttpError, ParserTransportError) as exc:
            raise CompetitorsSearchUpstreamError(
                "Wildberries search API is temporarily unavailable."
            ) from exc

        return hits_to_search_result(query=request.query, hits=hits)

    async def aclose(self) -> None:
        await self._discovery.aclose()
