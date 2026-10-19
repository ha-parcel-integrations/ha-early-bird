"""Tests for the pure parcel-mapping helpers.

These need no Home Assistant instance — the whole point of keeping
``parcels.py`` free of I/O is that the carrier-specific mapping can be tested
as plain functions.
"""
import logging
from datetime import datetime, timedelta, timezone

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.early_bird import parcels as parcels_module
from custom_components.early_bird.const import (
    CAPABILITIES,
    CONF_DELIVERED_FILTER_AMOUNT,
    CONF_DELIVERED_FILTER_TYPE,
    DOMAIN,
    KNOWN_CAPABILITIES,
    PENDING_CAPABILITIES,
    ParcelStatus,
)
from custom_components.early_bird.parcels import (
    apply_delivered_filter,
    build_history,
    format_dimensions,
    map_event_status,
    normalize_parcel,
    parse_iso,
    parse_occurred,
    sort_parcels_by_ts,
    to_iso_timestamp,
)

from .payloads import (
    ACTIVE_CODE,
    EXTERNAL_LINK,
    LEGACY_DELIVERED,
    LOCKER_TIMELINE,
    active_sample,
    delivered_sample,
    event,
    pickup_sample,
    timeline,
)

T = "2026-09-01T10:00:00Z"


@pytest.fixture(autouse=True)
def _reset_one_shot_warnings():
    parcels_module._unmapped_statuses_logged.clear()
    parcels_module._external_link_logged = False


def _status(*texts: str) -> ParcelStatus:
    """Status of a timeline whose events are given newest first."""
    events = [event(text, f"2026-09-0{9 - i}T10:00:00Z") for i, text in enumerate(texts)]
    return normalize_parcel(timeline(*events))["status"]


# ---------------------------------------------------------------------------
# status map
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Your delivery is booked with Early Bird.", ParcelStatus.REGISTERED),
        ("Din leverans är bokad med Early Bird.", ParcelStatus.REGISTERED),
        ("Leveransen till dig är bokad av e-handlaren. Mer text.", ParcelStatus.REGISTERED),
        ("Early Bird has received your package.", ParcelStatus.IN_TRANSIT),
        ("Early Bird har tagit emot ditt paket.", ParcelStatus.IN_TRANSIT),
        ("Your package has arrived at the terminal in Malmö.", ParcelStatus.IN_TRANSIT),
        ("Ditt paket har kommit till terminalen i Malmö.", ParcelStatus.IN_TRANSIT),
        ("Paketet har ankommit till sorteringsterminal Sundsvall", ParcelStatus.IN_TRANSIT),
        ("Your package is on its way. You will receive a notification.", ParcelStatus.IN_TRANSIT),
        ("Paketet är på väg. Du får ett meddelande.", ParcelStatus.IN_TRANSIT),
        ("We failed to deliver your package as planned. x", ParcelStatus.PROBLEM),
        ("Vi misslyckades med att leverera ditt paket som planerat.", ParcelStatus.PROBLEM),
        ("We were unable to access the entrance and therefore failed.", ParcelStatus.PROBLEM),
        ("Vi kunde inte komma in i porten och kunde därför inte leverera.", ParcelStatus.PROBLEM),
        ("Since we were unable to deliver the parcel to your home, we will reroute it.", ParcelStatus.IN_TRANSIT),
        ("Eftersom vi inte kunde leverera paketet hem till dig så bokar vi om.", ParcelStatus.IN_TRANSIT),
        ("Your package is now ready for collection from the parcel locker. App.", ParcelStatus.AT_PICKUP_POINT),
        ("Ditt paket finns nu redo att hämtas från paketskåpet.", ParcelStatus.AT_PICKUP_POINT),
        ("The package has been collected from the parcel locker.", ParcelStatus.DELIVERED),
        ("Paketet har hämtats ur paketskåpet.", ParcelStatus.DELIVERED),
        ("The package has been delivered to your door.", ParcelStatus.DELIVERED),
        ("The package has been delivered to your mailbox.", ParcelStatus.DELIVERED),
        ("The package has been delivered in a bag on your mailbox.", ParcelStatus.DELIVERED),
        ("Ditt paket har nu levererats av Early Bird. Mer.", ParcelStatus.DELIVERED),
        ("  YOUR   package is ON its way.  You will receive a NOTIFICATION  ", ParcelStatus.IN_TRANSIT),
    ],
)
def test_known_wording_maps(text, expected):
    assert _status(text) == expected


def test_new_attempt_inherits_the_newest_earlier_status_without_warning(caplog):
    caplog.set_level(logging.WARNING)
    assert (
        _status(
            "We have scheduled a new attempt to deliver your package.",
            "We were unable to access the entrance and therefore failed to deliver.",
        )
        == ParcelStatus.PROBLEM
    )
    assert (
        _status(
            "Vi har bokat in ett nytt försök att leverera ditt paket.",
            "Early Bird har tagit emot ditt paket.",
        )
        == ParcelStatus.IN_TRANSIT
    )
    assert "Unrecognised" not in caplog.text


def test_new_attempt_alone_is_unknown_without_warning(caplog):
    caplog.set_level(logging.WARNING)
    assert _status("We have scheduled a new attempt to deliver your package.") == (
        ParcelStatus.UNKNOWN
    )
    assert "Unrecognised" not in caplog.text


def test_unknown_newest_wording_falls_back_to_history_and_warns_once(caplog):
    caplog.set_level(logging.WARNING)
    texts = ("Your package is out for delivery today.", "Early Bird has received your package.")
    assert _status(*texts) == ParcelStatus.IN_TRANSIT
    assert _status(*texts) == ParcelStatus.IN_TRANSIT
    assert caplog.text.count("out for delivery today") == 1
    assert "issues/new?template=unrecognised_status.yml" in caplog.text


def test_unknown_wording_only_is_unknown_and_warns(caplog):
    caplog.set_level(logging.WARNING)
    assert _status("The package is being returned to the sender.") == ParcelStatus.UNKNOWN
    assert "being returned to the sender" in caplog.text


def test_band_ordering_trap_failed_attempt_then_locker_ready():
    """Failure wording earlier in the timeline must not outrank the newest event."""
    assert normalize_parcel(pickup_sample())["status"] == ParcelStatus.AT_PICKUP_POINT
    assert normalize_parcel(delivered_sample())["status"] == ParcelStatus.DELIVERED


def test_map_event_status_distinguishes_no_mapping():
    """History keeps ``null`` for both inherit and unrecognised wording."""
    assert map_event_status(None) is None
    assert map_event_status("We have scheduled a new attempt") is None
    assert map_event_status("Something new") is None
    assert map_event_status("Paketet är på väg. Du får ett meddelande.") == ParcelStatus.IN_TRANSIT


def test_empty_warning_text_is_not_logged(caplog):
    caplog.set_level(logging.WARNING)
    assert _status("") == ParcelStatus.UNKNOWN
    assert "Unrecognised" not in caplog.text


# ---------------------------------------------------------------------------
# timestamp helpers
# ---------------------------------------------------------------------------


def test_parse_occurred_handles_utc_offset_and_local():
    assert parse_occurred("2026-09-11T13:01:43.811Z").isoformat() == (
        "2026-09-11T13:01:43.811000+00:00"
    )
    assert parse_occurred("2026-09-11T15:01:43+02:00").isoformat() == (
        "2026-09-11T13:01:43+00:00"
    )
    # No offset: Stockholm wall clock (CET in November, CEST in August).
    assert parse_occurred("2024-11-15T01:40:24").isoformat() == "2024-11-15T00:40:24+00:00"
    assert parse_occurred("2026-08-15T12:00:00").isoformat() == "2026-08-15T10:00:00+00:00"
    assert parse_occurred("garbage") is None
    assert parse_occurred(None) is None
    assert parse_occurred("") is None


def test_parse_iso_handles_z_naive_and_garbage():
    assert parse_iso("2026-04-29T13:12:42Z").tzinfo is not None
    assert parse_iso("2026-04-29T13:12:42").tzinfo == timezone.utc
    assert parse_iso("not-a-date") is None
    assert parse_iso(None) is None


def test_to_iso_timestamp_converts_epoch_milliseconds():
    assert to_iso_timestamp(1784203767167) == "2026-07-16T12:09:27.167000+00:00"
    assert to_iso_timestamp("2026-04-29T13:12:42Z") == "2026-04-29T13:12:42Z"
    assert to_iso_timestamp(None) is None
    assert to_iso_timestamp(10**20) is None


def test_format_dimensions_needs_all_three_axes():
    assert format_dimensions(30, 20, 10) == {
        "length": 30,
        "width": 20,
        "height": 10,
        "text": "30 x 20 x 10 cm",
    }
    assert format_dimensions(30, None, 10) is None


# ---------------------------------------------------------------------------
# build_history
# ---------------------------------------------------------------------------


def test_build_history_orders_oldest_to_newest():
    history = build_history(LOCKER_TIMELINE["events"])
    assert len(history) == 14
    assert history[0]["raw_status"] == "Your delivery is booked with Early Bird."
    assert history[0]["status"] == ParcelStatus.REGISTERED
    assert history[0]["timestamp"] == "2026-09-03T06:57:49.024000+00:00"
    assert history[-1]["status"] == ParcelStatus.DELIVERED
    inherit = next(h for h in history if "scheduled a new attempt" in h["raw_status"])
    assert inherit["status"] is None


def test_build_history_caps_to_max_events():
    events = [event("Paketet är på väg. Du får ett meddelande.", f"2026-09-{day:02d}T10:00:00Z") for day in range(25, 0, -1)]
    history = build_history(events, max_events=20)
    assert len(history) == 20
    assert history[-1]["timestamp"].startswith("2026-09-25")


def test_build_history_handles_missing_and_malformed():
    assert build_history(None) == []
    assert build_history([{"text": "Paketet är på väg. Du får ett meddelande."}]) == []
    assert build_history(["not-a-dict"]) == []
    assert build_history([event("Paketet är på väg. Du får ett meddelande.", "nonsense")]) == []


# ---------------------------------------------------------------------------
# normalize_parcel — the canonical contract
# ---------------------------------------------------------------------------

CANONICAL_KEYS = [
    "carrier",
    "barcode",
    "sender",
    "receiver",
    "status",
    "raw_status",
    "delivered",
    "delivered_at",
    "planned_from",
    "planned_to",
    "pickup",
    "pickup_point",
    "url",
    "weight",
    "dimensions",
    "history",
    "raw",
]


def test_normalize_publishes_exactly_the_canonical_keys():
    """The aggregator and cross-carrier dashboards depend on this key set."""
    assert list(normalize_parcel(delivered_sample())) == CANONICAL_KEYS


def test_capabilities_are_known_values():
    """A typo here would silently misreport this carrier on the docs site."""
    assert CAPABILITIES <= KNOWN_CAPABILITIES
    assert PENDING_CAPABILITIES <= KNOWN_CAPABILITIES


def test_a_capability_is_never_both_populated_and_pending():
    """The docs site would have to pick one; "awaiting data" must not hide a confirmed field."""
    assert not CAPABILITIES & PENDING_CAPABILITIES


def test_capabilities_match_what_normalize_parcel_actually_returns():
    """Every declared CAPABILITIES entry must come true somewhere in a sample.

    Copy this test into a real carrier's own test_parcels.py verbatim — it
    stays correct for whatever subset of CAPABILITIES that carrier declares.
    """
    delivered = normalize_parcel(delivered_sample())
    active = normalize_parcel(active_sample())
    pickup = normalize_parcel(pickup_sample())
    with_history = normalize_parcel(delivered_sample(), include_history=True)

    if "weight" in CAPABILITIES:
        assert delivered["weight"] is not None
    if "dimensions" in CAPABILITIES:
        assert delivered["dimensions"] is not None
    if "delivery_window" in CAPABILITIES:
        assert active["planned_from"] is not None or active["planned_to"] is not None
    if "pickup_point" in CAPABILITIES:
        assert pickup["pickup_point"] is not None
    if "url" in CAPABILITIES:
        assert delivered["url"] is not None
    if "history" in CAPABILITIES:
        assert with_history["history"] is not None


def test_normalize_locker_fixture_delivered():
    parcel = normalize_parcel(delivered_sample(), include_history=True)
    assert parcel["carrier"] == "Early Bird"
    assert parcel["barcode"] == "00373402216888888888"
    assert parcel["status"] == ParcelStatus.DELIVERED
    assert parcel["delivered"] is True
    assert parcel["delivered_at"] == "2026-09-11T13:01:43.811000+00:00"
    assert parcel["raw_status"] == "The package has been collected from the parcel locker."
    assert parcel["pickup"] is True
    assert parcel["pickup_point"] is None
    assert parcel["planned_from"] is None and parcel["planned_to"] is None
    assert parcel["weight"] is None and parcel["dimensions"] is None
    assert parcel["sender"] is None and parcel["receiver"] is None
    assert parcel["url"] == "https://earlybird.se/spara-och-hjalp?id=00373402216888888888"
    assert parcel["raw"]["requestId"] == "req-REDACTED"
    assert len(parcel["history"]) == 14


def test_normalize_legacy_fixture_localises_offsetless_clock():
    parcel = normalize_parcel({**LEGACY_DELIVERED, "trackingNumber": "X"}, include_history=True)
    assert parcel["status"] == ParcelStatus.DELIVERED
    assert parcel["delivered_at"] == "2024-11-15T00:40:24+00:00"
    assert parcel["history"][0]["status"] == ParcelStatus.REGISTERED
    assert [h["status"] for h in parcel["history"][1:3]] == [ParcelStatus.IN_TRANSIT] * 2


def test_normalize_history_is_opt_in():
    assert normalize_parcel(delivered_sample())["history"] is None
    assert normalize_parcel(delivered_sample(), include_history=True)["history"]


def test_normalize_active_parcel_is_in_transit_with_no_window():
    parcel = normalize_parcel(active_sample())
    assert parcel["status"] == ParcelStatus.IN_TRANSIT
    assert parcel["delivered"] is False and parcel["delivered_at"] is None
    assert parcel["planned_from"] is None


def test_normalize_pickup_parcel():
    parcel = normalize_parcel(pickup_sample())
    assert parcel["status"] == ParcelStatus.AT_PICKUP_POINT
    assert parcel["pickup"] is True
    assert parcel["pickup_point"] is None


def test_normalize_pending_placeholder():
    parcel = normalize_parcel({"trackingNumber": ACTIVE_CODE})
    assert parcel["status"] == ParcelStatus.UNKNOWN
    assert parcel["raw_status"] is None
    assert parcel["barcode"] == ACTIVE_CODE
    assert parcel["delivered"] is False


def test_normalize_without_tracking_code_has_no_url():
    parcel = normalize_parcel({})
    assert parcel["barcode"] is None and parcel["url"] is None


def test_normalize_uses_status_block_when_events_are_missing():
    parcel = normalize_parcel(
        {"type": "timeline", "status": event("Paketet är på väg. Du får ett meddelande.", T), "events": []}
    )
    assert parcel["status"] == ParcelStatus.IN_TRANSIT
    assert parcel["raw_status"] == "Paketet är på väg. Du får ett meddelande."


def test_normalize_raw_status_falls_back_to_newest_event():
    parcel = normalize_parcel({"events": [event("Paketet är på väg. Du får ett meddelande.", T)]})
    assert parcel["raw_status"] == "Paketet är på väg. Du får ett meddelande."


def test_delivered_with_unparseable_stamp_has_no_delivered_at():
    parcel = normalize_parcel(timeline(event("Paketet har hämtats ur paketskåpet.", "nonsense")))
    assert parcel["delivered"] is True and parcel["delivered_at"] is None


def test_normalize_external_link_is_in_transit_and_warns_once(caplog):
    caplog.set_level(logging.WARNING)
    first = normalize_parcel({**EXTERNAL_LINK, "trackingNumber": "X"})
    normalize_parcel({**EXTERNAL_LINK, "trackingNumber": "X"})
    assert first["status"] == ParcelStatus.IN_TRANSIT
    assert first["raw_status"] is None
    assert first["raw"]["action"]["url"] == "https://partner.example/track/123"
    assert caplog.text.count("another carrier") == 1
    assert "unrecognised_status.yml" in caplog.text
    assert "partner.example" not in caplog.text
    assert "req-REDACTED" not in caplog.text


def test_external_link_without_action_dict_still_warns(caplog):
    caplog.set_level(logging.WARNING)
    normalize_parcel({"type": "external_link"})
    assert "action_keys=None" in caplog.text




# ---------------------------------------------------------------------------
# sort_parcels_by_ts
# ---------------------------------------------------------------------------


def test_sort_parcels_ascending_puts_unparseable_last():
    parcels = [
        {"barcode": "a", "planned_from": "2026-05-02T10:00:00Z"},
        {"barcode": "b", "planned_from": None},
        {"barcode": "c", "planned_from": "2026-05-01T10:00:00Z"},
    ]
    ordered = [p["barcode"] for p in sort_parcels_by_ts(parcels, "planned_from")]
    assert ordered == ["c", "a", "b"]


def test_sort_parcels_descending_still_puts_unparseable_last():
    parcels = [
        {"barcode": "a", "delivered_at": "2026-05-02T10:00:00Z"},
        {"barcode": "b", "delivered_at": "nonsense"},
        {"barcode": "c", "delivered_at": "2026-05-01T10:00:00Z"},
    ]
    ordered = [
        p["barcode"]
        for p in sort_parcels_by_ts(parcels, "delivered_at", descending=True)
    ]
    assert ordered == ["a", "c", "b"]


# ---------------------------------------------------------------------------
# apply_delivered_filter
# ---------------------------------------------------------------------------


def _entry(filter_type: str, amount: int) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        options={
            CONF_DELIVERED_FILTER_TYPE: filter_type,
            CONF_DELIVERED_FILTER_AMOUNT: amount,
        },
        unique_id=DOMAIN,
    )


def _delivered_pair() -> list[dict]:
    now = datetime.now(timezone.utc)
    return [
        {"barcode": "RECENT", "delivered_at": (now - timedelta(days=1)).isoformat()},
        {"barcode": "OLD", "delivered_at": (now - timedelta(days=30)).isoformat()},
    ]


def test_delivered_filter_by_days():
    kept = apply_delivered_filter(_delivered_pair(), _entry("days", 7))
    assert [p["barcode"] for p in kept] == ["RECENT"]


def test_delivered_filter_by_count():
    parcels = _delivered_pair()
    assert apply_delivered_filter(parcels, _entry("parcels", 1)) == parcels[:1]


def test_delivered_filter_keeps_unparseable_timestamp():
    """Better to show a parcel with a broken date than to silently drop it."""
    parcels = [{"barcode": "WEIRD", "delivered_at": "nonsense"}]
    assert apply_delivered_filter(parcels, _entry("days", 7)) == parcels


def test_locker_route_is_a_pickup_point_from_the_reroute_on():
    """The reroute announcement already makes the parcel en route to a pickup point."""
    reroute_only = {
        "type": "timeline",
        "events": [
            {
                "text": "Since we were unable to deliver the parcel to your home, we will reroute it to a parcel locker.",
                "occurredAt": "2026-09-07T09:47:53.914Z",
            },
            {
                "text": "Your package has arrived at the terminal in Stockholm.",
                "occurredAt": "2026-09-06T04:18:00Z",
            },
        ],
        "trackingNumber": "X",
    }
    en_route = normalize_parcel(reroute_only)
    assert en_route["status"] == ParcelStatus.IN_TRANSIT
    assert en_route["pickup"] is True
    assert normalize_parcel(active_sample())["pickup"] is True
    assert normalize_parcel(pickup_sample())["pickup"] is True
    collected = normalize_parcel(delivered_sample())
    assert collected["delivered"] is True
    assert collected["pickup"] is True


def test_home_delivery_is_not_a_pickup():
    for wording in (
        "The package has been delivered to your door.",
        "The package has been delivered to your mailbox.",
        "The package has been delivered in a bag on your mailbox.",
    ):
        parcel = normalize_parcel(
            {
                "type": "timeline",
                "events": [
                    {"text": wording, "occurredAt": "2026-09-12T00:21:15Z"},
                    {"text": "Your package is on its way. You will receive a notification.", "occurredAt": "2026-09-11T14:29:46Z"},
                ],
                "trackingNumber": "X",
            }
        )
        assert parcel["delivered"] is True
        assert parcel["pickup"] is False


def test_on_its_way_without_the_locker_tail_is_not_assumed_in_transit(caplog):
    """An out-for-delivery sentence sharing the opening must reach the WARNING."""
    caplog.set_level(logging.WARNING)
    wording = "Your package is on its way to you today between 06:00 and 07:00."
    assert _status(wording) == ParcelStatus.UNKNOWN
    assert "between 06:00 and 07:00" in caplog.text
