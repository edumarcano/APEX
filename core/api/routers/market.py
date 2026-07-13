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
    Return cache-first EOD market snapshots for configured symbols.

    A single TIME_SERIES_DAILY call per symbol supplies price, change metrics,
    and sparkline data. Network IO is isolated behind a file-backed aggregator
    so HUD polling does not block on third-party rate limits.
    """
    try:
        payload = market_client.fetch_market_data()
        return MarketResponse.model_validate(payload)
    except Exception:
        _LOGGER.exception("Market snapshot endpoint failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Market snapshot unavailable.",
        )
