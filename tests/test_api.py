"""Tests for the Early Bird API client."""

import json
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from custom_components.early_bird.api import EarlyBirdApiClient, EarlyBirdApiError

from .payloads import EXTERNAL_LINK, LEGACY_DELIVERED

CODE = "00373402216999999999"


def _session_returning(
    status: int, body: object = None, headers: dict | None = None
) -> MagicMock:
    response = MagicMock()
    response.status = status
    response.headers = headers or {}
    if isinstance(body, str):
        response.json = AsyncMock(side_effect=json.JSONDecodeError("x", body, 0))
    else:
        response.json = AsyncMock(return_value=body)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=response)
    ctx.__aexit__ = AsyncMock(return_value=False)
    session = MagicMock()
    session.post = MagicMock(return_value=ctx)
    return session


async def test_get_parcel_posts_the_code_with_the_locale_key():
    session = _session_returning(200, LEGACY_DELIVERED)
    parcel = await EarlyBirdApiClient(session).async_get_parcel(CODE)

    assert parcel["type"] == "timeline"
    args, kwargs = session.post.call_args
    assert args[0] == "https://earlybird.se/api/tracking"
    assert kwargs["json"] == {"trackingNumber": CODE, "locale": "en"}
    assert kwargs["headers"]["Accept"] == "application/json"


async def test_get_parcel_returns_external_link_reply():
    client = EarlyBirdApiClient(_session_returning(200, EXTERNAL_LINK))
    assert (await client.async_get_parcel(CODE))["type"] == "external_link"


async def test_get_parcel_returns_none_when_not_found():
    client = EarlyBirdApiClient(
        _session_returning(404, {"code": "tracking_not_found", "message": "x"})
    )
    assert await client.async_get_parcel(CODE) is None


async def test_get_parcel_returns_none_when_invalid():
    client = EarlyBirdApiClient(
        _session_returning(400, {"code": "invalid_tracking_number"})
    )
    assert await client.async_get_parcel("x") is None


async def test_get_parcel_raises_on_unrelated_404():
    client = EarlyBirdApiClient(_session_returning(404, {"code": "other"}))
    with pytest.raises(EarlyBirdApiError) as err:
        await client.async_get_parcel(CODE)
    assert err.value.status_code == 404


async def test_get_parcel_raises_on_server_error():
    client = EarlyBirdApiClient(_session_returning(500, {}))
    with pytest.raises(EarlyBirdApiError) as err:
        await client.async_get_parcel(CODE)
    assert err.value.status_code == 500


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        ({"Retry-After": "30"}, 30.0),
        ({}, None),
        ({"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}, None),
    ],
)
async def test_get_parcel_429_carries_retry_after(headers, expected):
    client = EarlyBirdApiClient(_session_returning(429, None, headers))
    with pytest.raises(EarlyBirdApiError) as err:
        await client.async_get_parcel(CODE)
    assert err.value.status_code == 429
    assert err.value.retry_after == expected


async def test_html_challenge_body_is_a_transport_failure():
    client = EarlyBirdApiClient(_session_returning(200, "<html>challenge</html>"))
    with pytest.raises(EarlyBirdApiError) as err:
        await client.async_get_parcel(CODE)
    assert "non-JSON" in str(err.value)


async def test_html_403_is_a_transport_failure():
    client = EarlyBirdApiClient(_session_returning(403, "<html>denied</html>"))
    with pytest.raises(EarlyBirdApiError) as err:
        await client.async_get_parcel(CODE)
    assert err.value.status_code == 403


async def test_vercel_challenge_header_raises():
    client = EarlyBirdApiClient(
        _session_returning(403, {}, {"x-vercel-mitigated": "challenge"})
    )
    with pytest.raises(EarlyBirdApiError) as err:
        await client.async_get_parcel(CODE)
    assert "challenge" in str(err.value)


async def test_get_parcel_raises_on_non_object_body():
    client = EarlyBirdApiClient(_session_returning(200, ["not", "a", "dict"]))
    with pytest.raises(EarlyBirdApiError):
        await client.async_get_parcel(CODE)


async def test_get_parcel_raises_on_unknown_reply_type():
    client = EarlyBirdApiClient(_session_returning(200, {"type": "mystery"}))
    with pytest.raises(EarlyBirdApiError):
        await client.async_get_parcel(CODE)


async def test_get_parcel_propagates_network_error():
    """ClientError is left alone — DataUpdateCoordinator already wraps it."""
    session = MagicMock()
    session.post = MagicMock(side_effect=aiohttp.ClientError("boom"))
    with pytest.raises(aiohttp.ClientError):
        await EarlyBirdApiClient(session).async_get_parcel(CODE)
