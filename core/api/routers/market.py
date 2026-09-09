"""Market data snapshot route."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, status

from clients import market_client
from core.api.models import MarketResponse

_LOGGER = logging.getLogger(__name__)

router = APIRouter(tags=["market"])


@router.get("/api/v1/market", response_model=MarketResponse)
def get_market_snapshot() -> MarketResponse:
    """
    Return cache-backed EOD market display data for configured symbols.

    Provider refreshes are owned by telemetry collection. This route never
    sends a request to Alpha Vantage and is safe for UI reads.
    """
    try:
        payload = market_client.read_market_data()
        return MarketResponse.model_validate(payload)
    except Exception:
        _LOGGER.exception("Market snapshot endpoint failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Market snapshot unavailable.",
        )
