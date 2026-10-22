"""Canonical parcel shape, status mapping and list helpers.

Everything in this module is a **pure function** — no I/O, no Home Assistant
objects beyond the config entry's options. That is deliberate: it keeps the
carrier-specific mapping (which you rewrite per carrier) apart from the
coordinator (which is nearly identical everywhere), and it makes the mapping
trivially unit-testable without spinning up HA.

Two things here are carrier-specific: the wording-based status map and
:func:`normalize_parcel`. Everything else — the history builder, the sort
contract, the delivered filter, the one-shot warnings — is suite-wide
machinery.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import logging
from typing import Any
from zoneinfo import ZoneInfo

from homeassistant.config_entries import ConfigEntry

from .const import (
    CONF_DELIVERED_FILTER_AMOUNT,
    CONF_DELIVERED_FILTER_TYPE,
    DEFAULT_DELIVERED_FILTER_AMOUNT,
    DEFAULT_DELIVERED_FILTER_TYPE,
    HISTORY_MAX_EVENTS,
    LOCAL_TIMEZONE,
    TRACKING_URL,
    ParcelStatus,
)

_LOGGER = logging.getLogger(__name__)

# Where users report a status we do not map yet. Rewritten by the bootstrap
# script; it must point at the carrier's own repo so the log line is
# copy-pasteable straight into a new issue.
#
# The ``?template=`` parameter matters: without it the link opens a blank form,
# and the report comes back missing the version and the log line we need.
NEW_ISSUE_URL = (
    "https://github.com/ha-parcel-integrations/ha-early-bird/issues/new"
    "?template=unrecognised_status.yml"
)

# Loaded at import time: building a ZoneInfo reads the tz database from disk,
# which must not happen on the event loop.
_LOCAL_TZ = ZoneInfo(LOCAL_TIMEZONE)

# The API has no status code, only free-text wording in English and Swedish,
# with terminal names and variable tail sentences. Wording is matched by
# lower-cased stem so those tails do not matter.
_STEMS: tuple[tuple[tuple[str, ...], ParcelStatus], ...] = (
    (
        (
            "your delivery is booked with early bird",
            "din leverans är bokad med early bird",
            "leveransen till dig är bokad av e-handlaren",
        ),
        ParcelStatus.REGISTERED,
    ),
    (
        (
            "early bird has received your package",
            "early bird har tagit emot ditt paket",
            "your package has arrived at the terminal in",
            "ditt paket har kommit till terminalen i",
            "paketet har ankommit till sorteringsterminal",
            "your package is on its way. you will receive a notification",
            "paketet är på väg. du får ett meddelande",
            "since we were unable to deliver the parcel to your home",
            "eftersom vi inte kunde leverera paketet hem",
        ),
        ParcelStatus.IN_TRANSIT,
    ),
    (
        (
            "we failed to deliver your package",
            "vi misslyckades med att leverera",
            "we were unable to access the entrance",
            "vi kunde inte komma in i porten",
        ),
        ParcelStatus.PROBLEM,
    ),
    (
        (
            "your package is now ready for collection from the parcel locker",
            "ditt paket finns nu redo att hämtas",
        ),
        ParcelStatus.AT_PICKUP_POINT,
    ),
    (
        (
            "the package has been collected from the parcel locker",
            "paketet har hämtats ur paketskåpet",
            "the package has been delivered",
            "ditt paket har nu levererats",
        ),
        ParcelStatus.DELIVERED,
    ),
)

# Wording that routes a parcel to a locker (a pickup point): the reroute
# announcement and everything after it. Matched anywhere in the text, so the
# tail sentences and locker names do not matter.
_PICKUP_MARKERS = (
    "parcel locker",
    "paketskåp",
    "since we were unable to deliver the parcel to your home",
    "eftersom vi inte kunde leverera paketet hem",
    "ditt paket finns nu redo att hämtas",
)

# A new delivery attempt carries no state of its own: the parcel keeps the
# status of the newest earlier event that does.
_INHERIT_STEMS = (
    "we have scheduled a new attempt",
    "vi har bokat in ett nytt försök",
)

# Wordings already warned about, so each is logged once per HA session
# instead of on every poll.
_unmapped_statuses_logged: set[str] = set()
_external_link_logged = False


def _clean(text: Any) -> str:
    """Return the wording trimmed, or an empty string for a non-string."""
    return " ".join(text.split()) if isinstance(text, str) else ""


def _classify(text: Any) -> tuple[bool, ParcelStatus | None]:
    """Return ``(known, status)`` for one piece of wording.

    ``known`` is False for wording the map has never seen; a known wording
    with no status of its own (a new delivery attempt) gives ``(True, None)``.
    """
    lowered = _clean(text).lower()
    for stems, status in _STEMS:
        if lowered.startswith(stems):
            return True, status
    if lowered.startswith(_INHERIT_STEMS):
        return True, None
    return False, None


def _warn_unmapped_status(text: str) -> None:
    """Log unrecognised wording once, with a copy-paste issue link."""
    if not text or text in _unmapped_statuses_logged:
        return
    _unmapped_statuses_logged.add(text)
    _LOGGER.warning(
        "Unrecognised Early Bird status — help us map it. Open an issue "
        "and paste this line: %s\n  status=%s → falls back to the newest "
        "recognised event, else 'unknown'",
        NEW_ISSUE_URL,
        text,
    )


def _warn_external_link(raw: dict) -> None:
    """Log the first hand-over to another carrier, keys only."""
    global _external_link_logged  # noqa: PLW0603 - one-shot flag, reset by tests
    if _external_link_logged:
        return
    _external_link_logged = True
    action = raw.get("action")
    _LOGGER.warning(
        "Early Bird handed a parcel over to another carrier, a reply shape we "
        "have not confirmed — help us verify it. Open an issue and paste this "
        "line: %s\n  keys=%s action_keys=%s",
        NEW_ISSUE_URL,
        sorted(raw),
        sorted(action) if isinstance(action, dict) else None,
    )


def map_event_status(text: str | None) -> ParcelStatus | None:
    """Map one history event's wording to a status, or ``None``.

    Unrecognised wording keeps ``status: null`` on the history entry (rather
    than ``unknown``, so a consumer can tell "no mapping" from "mapped to
    unknown") and warns once.
    """
    known, status = _classify(text)
    if not known:
        _warn_unmapped_status(_clean(text))
    return status


def _events(raw: dict) -> list[dict]:
    """Return the reply's events newest first, falling back to its status."""
    events = raw.get("events")
    if not events and isinstance(raw.get("status"), dict):
        events = [raw["status"]]
    return [event for event in events or [] if isinstance(event, dict)]


def _is_pickup(events: list[dict], status: ParcelStatus) -> bool:
    """Whether the parcel is destined for, or collected from, a locker."""
    if status is ParcelStatus.AT_PICKUP_POINT:
        return True
    return any(
        marker in _clean(event.get("text")).lower()
        for event in events
        for marker in _PICKUP_MARKERS
    )


def _resolve_status(events: list[dict]) -> tuple[ParcelStatus, dict | None]:
    """Return the status and the event it came from, newest event first."""
    for event in events:
        known, status = _classify(event.get("text"))
        if not known:
            _warn_unmapped_status(_clean(event.get("text")))
        elif status is not None:
            return status, event
    return ParcelStatus.UNKNOWN, None


def parse_iso(value: str | None) -> datetime | None:
    """Parse an ISO 8601 string to an aware datetime, or ``None`` on failure.

    Naive values are treated as UTC so a list always sorts without crashing on
    a mixed set.
    """
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def parse_occurred(value: Any) -> datetime | None:
    """Parse an ``occurredAt`` stamp to an aware UTC datetime.

    Current parcels carry a UTC instant or an offset. Earlier-system parcels
    carry a wall clock with no offset, which is Swedish local time.
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_LOCAL_TZ)
    return parsed.astimezone(UTC)


def to_iso_timestamp(value: Any) -> str | None:
    """Return an ISO 8601 string for an API timestamp field.

    Numbers are treated as **epoch milliseconds** — the common case for the
    consumer APIs in this suite. Strings pass through untouched; their
    consumers are guarded by :func:`parse_iso`. Adjust the numeric branch if
    your carrier stamps in seconds.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value / 1000, tz=UTC).isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    return str(value)


def format_dimensions(
    length: float | None, width: float | None, height: float | None
) -> dict[str, Any] | None:
    """Return the canonical ``dimensions`` dict, or ``None`` when incomplete.

    Units contract: **centimetres**, with ``text`` pre-formatted as
    ``"L x W x H cm"`` (integer values, lowercase ``x``) so dashboards can show
    a dimension without doing their own formatting. Convert before calling if
    the carrier reports millimetres or inches.
    """
    if length is None or width is None or height is None:
        return None
    return {
        "length": length,
        "width": width,
        "height": height,
        "text": f"{int(length)} x {int(width)} x {int(height)} cm",
    }


def build_history(
    events: list | None, *, max_events: int = HISTORY_MAX_EVENTS
) -> list[dict]:
    """Build the canonical ``history`` list from the newest-first events.

    Each entry is ``{timestamp, status, raw_status}`` — identical across all
    suite carriers, and top-level (not under ``raw``) so it survives the
    aggregator's ``strip_raw()``. ``raw_status`` is the carrier's own wording.
    Returned oldest → newest and capped to the most recent ``max_events``.
    """
    ordered: list[dict] = []
    for event in reversed(events or []):
        if not isinstance(event, dict):
            continue
        occurred = parse_occurred(event.get("occurredAt"))
        if occurred is None:
            continue
        ordered.append(
            {
                "timestamp": occurred.isoformat(),
                "status": map_event_status(event.get("text")),
                "raw_status": event.get("text"),
            }
        )
    return ordered[-max_events:]


def tracking_url(tracking_code: str | None) -> str | None:
    """Construct the consumer tracking deep-link for a parcel."""
    if not tracking_code:
        return None
    return TRACKING_URL.format(tracking_code=tracking_code)


def normalize_parcel(raw: dict, *, include_history: bool = False) -> dict:
    """Return a carrier-agnostic parcel dict with the payload under ``raw``.

    The keys of the returned dict are the contract; ``None`` where the carrier
    does not expose a value. The reply does not echo the tracking number, so
    the coordinator injects it as ``trackingNumber``. Status is derived from
    the event wording alone.
    """
    tracking_code = raw.get("trackingNumber")
    events = _events(raw)

    if raw.get("type") == "external_link":
        _warn_external_link(raw)
        status, source = ParcelStatus.IN_TRANSIT, None
    else:
        status, source = _resolve_status(events)
    delivered = status is ParcelStatus.DELIVERED

    delivered_at = None
    if delivered and source is not None:
        occurred = parse_occurred(source.get("occurredAt"))
        delivered_at = occurred.isoformat() if occurred else None

    headline = raw.get("status")
    raw_status = (headline.get("text") if isinstance(headline, dict) else None) or (
        events[0].get("text") if events else None
    )

    return {
        "carrier": "Early Bird",
        "barcode": tracking_code,
        "sender": None,
        "receiver": None,
        "status": status,
        "raw_status": raw_status,
        "delivered": delivered,
        "delivered_at": delivered_at,
        "planned_from": None,
        "planned_to": None,
        "pickup": _is_pickup(events, status),
        "pickup_point": None,
        "url": tracking_url(tracking_code),
        "weight": None,
        "dimensions": None,
        "history": build_history(events) if include_history else None,
        "raw": raw,
    }


def sort_parcels_by_ts(
    parcels: list[dict], key_field: str, *, descending: bool = False
) -> list[dict]:
    """Return normalised parcels sorted by the ISO timestamp at ``key_field``.

    The suite's sort contract: incoming/outgoing ascending on ``planned_from``,
    delivered descending on ``delivered_at``. Parcels whose value is missing or
    unparseable always sort to the end, regardless of ``descending``.
    """
    with_ts: list[tuple[datetime, dict]] = []
    without_ts: list[dict] = []
    for parcel in parcels:
        parsed = parse_iso(parcel.get(key_field))
        if parsed is None:
            without_ts.append(parcel)
        else:
            with_ts.append((parsed, parcel))
    with_ts.sort(key=lambda item: item[0], reverse=descending)
    return [parcel for _, parcel in with_ts] + without_ts


def apply_delivered_filter(parcels: list[dict], entry: ConfigEntry) -> list[dict]:
    """Trim the delivered list per the entry's retention option.

    ``parcels`` must already be sorted newest-first. ``days`` keeps deliveries
    from the last N days (an unparseable ``delivered_at`` is kept rather than
    silently dropped); the ``parcels`` type keeps the N most recent. Parcels
    stay *tracked* either way — this only controls what the delivered sensor
    shows.
    """
    options = entry.options
    filter_type = options.get(CONF_DELIVERED_FILTER_TYPE, DEFAULT_DELIVERED_FILTER_TYPE)
    amount = int(
        options.get(CONF_DELIVERED_FILTER_AMOUNT, DEFAULT_DELIVERED_FILTER_AMOUNT)
    )
    if filter_type == "days":
        cutoff = datetime.now(UTC) - timedelta(days=amount)
        return [
            parcel
            for parcel in parcels
            if (parsed := parse_iso(parcel.get("delivered_at"))) is None
            or parsed >= cutoff
        ]
    return parcels[:amount]
