"""Early Bird public tracking API client."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

from .const import TRACKING_API_URL

_LOGGER = logging.getLogger(__name__)

_TIMELINE = "timeline"
_EXTERNAL_LINK = "external_link"


class EarlyBirdApiError(Exception):
    """Raised when an Early Bird API call returns an unexpected response."""

    def __init__(
        self,
        detail: str,
        *,
        status_code: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        """Store the status code and the ``Retry-After`` header, if any."""
        super().__init__(f"Early Bird API request failed: {detail}")
        self.detail = detail
        self.status_code = status_code
        self.retry_after = retry_after


class EarlyBirdApiClient:
    """Client for the keyless Early Bird tracking route.

    The endpoint is keyed on the tracking code alone and answers on the HTTP
    status plus a JSON ``code`` field, so the body is branched on, not the
    status alone.
    """

    def __init__(self, session: aiohttp.ClientSession) -> None:
        """Initialise the client with an aiohttp session."""
        self._session = session

    async def async_get_parcel(self, tracking_code: str) -> dict[str, Any] | None:
        """Fetch one parcel's tracking details.

        Returns the reply dict for a timeline or an external-link hand-over,
        or ``None`` when the number is unknown, expired or refused as invalid.
        Anything else raises :class:`EarlyBirdApiError`; network errors
        propagate as ``aiohttp.ClientError``.
        """
        async with self._session.post(
            TRACKING_API_URL,
            json={"trackingNumber": tracking_code, "locale": "en"},
            headers={"Accept": "application/json"},
        ) as response:
            status = response.status
            if status == 429:
                retry_after_header = response.headers.get("Retry-After")
                try:
                    retry_after = (
                        float(retry_after_header) if retry_after_header else None
                    )
                except ValueError:
                    retry_after = None  # an HTTP-date, not seconds
                raise EarlyBirdApiError(
                    "HTTP 429", status_code=429, retry_after=retry_after
                )
            if response.headers.get("x-vercel-mitigated"):
                raise EarlyBirdApiError(
                    "blocked by a browser challenge", status_code=status
                )
            try:
                # content_type=None: a challenge page must fail as a transport
                # error below, not as aiohttp's content-type refusal.
                payload = await response.json(content_type=None)
            except ValueError as err:
                raise EarlyBirdApiError(
                    f"non-JSON body (HTTP {status})", status_code=status
                ) from err

        if not isinstance(payload, dict):
            raise EarlyBirdApiError(
                "unexpected body (not a JSON object)", status_code=status
            )

        code = payload.get("code")
        if status == 404 and code == "tracking_not_found":
            return None
        if status == 400 and code == "invalid_tracking_number":
            _LOGGER.debug("Early Bird refused a tracking number as invalid")
            return None
        if status != 200:
            raise EarlyBirdApiError(f"HTTP {status}", status_code=status)

        if payload.get("type") not in (_TIMELINE, _EXTERNAL_LINK):
            raise EarlyBirdApiError("unexpected reply type", status_code=status)
        return payload
