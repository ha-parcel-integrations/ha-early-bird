"""Sample Early Bird API payloads shared by the test modules.

The two fixture-backed replies are scrubbed copies of live responses; the
rest are built from the same shape.
"""

from __future__ import annotations

import copy

ACTIVE_CODE = "00373402216999999999"
DELIVERED_CODE = "00373402216888888888"

DELIVERED_TEXT = "The package has been collected from the parcel locker."
LOCKER_READY_TEXT = (
    "Your package is now ready for collection from the parcel locker. "
    "The iBoxen app is required to open the box."
)

LOCKER_TIMELINE: dict = {
    "type": "timeline",
    "status": {
        "text": "The package has been collected from the parcel locker.",
        "occurredAt": "2026-09-11T13:01:43.811Z",
    },
    "events": [
        {
            "text": "The package has been collected from the parcel locker.",
            "occurredAt": "2026-09-11T13:01:43.811Z",
        },
        {
            "text": "Your package is now ready for collection from the parcel locker. The iBoxen app is required to open the box.",
            "occurredAt": "2026-09-08T23:31:57.752Z",
        },
        {
            "text": "Your package has arrived at the terminal in Stockholm.",
            "occurredAt": "2026-09-08T16:19:25.196Z",
        },
        {
            "text": "Your package is on its way. You will receive a notification when it is ready to be collected from the parcel locker.",
            "occurredAt": "2026-09-08T16:19:25.196Z",
        },
        {
            "text": "Since we were unable to deliver the parcel to your home, we will reroute it to a parcel locker. We will notify you as soon as we know which locker it will be.",
            "occurredAt": "2026-09-07T09:47:53.914Z",
        },
        {
            "text": "Your package has arrived at the terminal in Stockholm.",
            "occurredAt": "2026-09-06T04:18:00Z",
        },
        {
            "text": "Your package has arrived at the terminal in Route 000 EXAMPLE.",
            "occurredAt": "2026-09-06T04:18:00Z",
        },
        {
            "text": "We failed to deliver your package as planned. We will notify you as soon as possible with information on how we will ensure that your package is delivered.",
            "occurredAt": "2026-09-06T01:10:54Z",
        },
        {
            "text": "We have scheduled a new attempt to deliver your package.",
            "occurredAt": "2026-09-05T06:55:05Z",
        },
        {
            "text": "We were unable to access the entrance and therefore failed to deliver your package. We will make a new attempt as soon as possible.",
            "occurredAt": "2026-09-05T01:49:31Z",
        },
        {
            "text": "Your package has arrived at the terminal in Stockholm.",
            "occurredAt": "2026-09-04T16:24:56Z",
        },
        {
            "text": "Your package has arrived at the terminal in Early Bird Norsborg.",
            "occurredAt": "2026-09-04T02:42:12.755Z",
        },
        {
            "text": "Early Bird has received your package.",
            "occurredAt": "2026-09-04T02:42:12.755Z",
        },
        {
            "text": "Your delivery is booked with Early Bird.",
            "occurredAt": "2026-09-03T06:57:49.024Z",
        },
    ],
    "action": None,
    "requestId": "req-REDACTED",
}

LEGACY_DELIVERED: dict = {
    "type": "timeline",
    "status": {
        "text": "Ditt paket har nu levererats av Early Bird. Om paketet inte fick plats i postlådan så har det hängts i en påse på din postlåda alternativt dörr",
        "occurredAt": "2024-11-15T01:40:24",
    },
    "events": [
        {
            "text": "Ditt paket har nu levererats av Early Bird. Om paketet inte fick plats i postlådan så har det hängts i en påse på din postlåda alternativt dörr",
            "occurredAt": "2024-11-15T01:40:24",
        },
        {
            "text": "Paketet har ankommit till sorteringsterminal Sundsvall",
            "occurredAt": "2024-11-14T21:56:23",
        },
        {
            "text": "Paketet har ankommit till sorteringsterminal Linköping",
            "occurredAt": "2024-11-14T00:42:37",
        },
        {
            "text": "Leveransen till dig är bokad av e-handlaren. När vi tar hand om ditt paket på vår terminal så skickar vi ett meddelande till dig med en länk till vår spårningssida. Där kan du se den beräknade leveransdagen och all information om paketets resa.",
            "occurredAt": "2024-11-13T09:44:33",
        },
    ],
    "action": None,
    "requestId": "req-REDACTED",
}

EXTERNAL_LINK: dict = {
    "type": "external_link",
    "action": {"url": "https://partner.example/track/123", "label": "Track"},
    "requestId": "req-REDACTED",
}


def event(text: str, occurred_at: str) -> dict:
    """One entry of the carrier's event timeline."""
    return {"text": text, "occurredAt": occurred_at}


def timeline(*events: dict) -> dict:
    """A timeline reply from events given newest first."""
    return {
        "type": "timeline",
        "status": dict(events[0]) if events else None,
        "events": list(events),
        "action": None,
        "requestId": "req-REDACTED",
    }


def delivered_sample(code: str = DELIVERED_CODE) -> dict:
    """The collected-from-locker reply, tracking number injected."""
    return {**copy.deepcopy(LOCKER_TIMELINE), "trackingNumber": code}


def active_sample(code: str = ACTIVE_CODE) -> dict:
    """A parcel still on its way (the locker reply minus its last two events)."""
    sample = copy.deepcopy(LOCKER_TIMELINE)
    sample["events"] = sample["events"][2:]
    sample["status"] = dict(sample["events"][0])
    return {**sample, "trackingNumber": code}


def pickup_sample(code: str = ACTIVE_CODE) -> dict:
    """A parcel waiting in the locker."""
    sample = copy.deepcopy(LOCKER_TIMELINE)
    sample["events"] = sample["events"][1:]
    sample["status"] = dict(sample["events"][0])
    return {**sample, "trackingNumber": code}
