"""Tests for Early Bird diagnostics."""

from datetime import timedelta
from unittest.mock import MagicMock

from custom_components.early_bird.diagnostics import async_get_config_entry_diagnostics
from custom_components.early_bird.parcels import normalize_parcel

from .payloads import EXTERNAL_LINK, LOCKER_TIMELINE


async def test_diagnostics_redacts_and_counts(hass):
    """Diagnostics get pasted into public issues — nothing identifying may survive."""
    entry = MagicMock()
    entry.options = {"parcels": [{"tracking_code": "EXAMPLE123456"}]}
    entry.runtime_data.coordinator.current_tier_minutes = 15
    entry.runtime_data.coordinator.update_interval = timedelta(minutes=15)
    entry.runtime_data.coordinator.data = [
        {
            "barcode": "EXAMPLE123456",
            "sender": "Example Shop",
            "receiver": "Jane Doe",
            "status": "out_for_delivery",
            "raw": {
                "trackingNumber": "EXAMPLE123456",
                "recipient": "Jane Doe",
                "deliveryAddress": {"city": "Rotterdam", "street": "Coolsingel 1"},
            },
        }
    ]
    entry.runtime_data.coordinator.delivered = []
    entry.runtime_data.coordinator.delivered_codes = set()

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["counts"] == {
        "incoming_active": 1,
        "delivered": 0,
        "skipped_from_fetch": 0,
    }
    assert result["polling"] == {
        "tier_minutes": 15,
        "update_interval_seconds": 900.0,
        "suspended": False,
    }
    # tracking codes and payload PII are redacted, at every nesting level
    assert result["entry_options"]["parcels"][0]["tracking_code"] == "**REDACTED**"
    assert result["incoming"][0]["barcode"] == "**REDACTED**"
    assert result["incoming"][0]["receiver"] == "**REDACTED**"
    assert result["incoming"][0]["raw"]["recipient"] == "**REDACTED**"
    assert result["incoming"][0]["raw"]["deliveryAddress"] == "**REDACTED**"
    # non-identifying fields survive, or the diagnostics would be useless
    assert result["incoming"][0]["status"] == "out_for_delivery"


async def test_diagnostics_reports_suspended_polling(hass):
    """update_interval None (Section 2.1's full stop) must be visible, not just absent."""
    entry = MagicMock()
    entry.options = {"parcels": []}
    entry.runtime_data.coordinator.current_tier_minutes = None
    entry.runtime_data.coordinator.update_interval = None
    entry.runtime_data.coordinator.data = []
    entry.runtime_data.coordinator.delivered = []

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["polling"] == {
        "tier_minutes": None,
        "update_interval_seconds": None,
        "suspended": True,
    }


async def test_diagnostics_redacts_wording_request_id_and_action(hass):
    """Terminal and route names live in the wording, so every text goes."""
    entry = MagicMock()
    entry.options = {"parcels": []}
    entry.runtime_data.coordinator.current_tier_minutes = 45
    entry.runtime_data.coordinator.update_interval = timedelta(minutes=45)
    locker = normalize_parcel(
        {**LOCKER_TIMELINE, "trackingNumber": "00373402216999999999"},
        include_history=True,
    )
    link = normalize_parcel({**EXTERNAL_LINK, "trackingNumber": "00373402216888888888"})
    entry.runtime_data.coordinator.data = [locker]
    entry.runtime_data.coordinator.delivered = [link]
    entry.runtime_data.coordinator.delivered_codes = set()

    result = await async_get_config_entry_diagnostics(hass, entry)
    dumped = str(result)

    for leaked in (
        "Stockholm",
        "Norsborg",
        "Route 000",
        "req-REDACTED",
        "partner.example",
        "00373402216",
    ):
        assert leaked not in dumped
    assert result["incoming"][0]["status"] == "delivered"
    assert result["incoming"][0]["history"][0]["raw_status"] == "**REDACTED**"
    assert result["incoming"][0]["history"][0]["timestamp"]
    assert result["delivered"][0]["raw"]["action"] == "**REDACTED**"
