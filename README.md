# Early Bird Parcel Tracker

[![Release](https://img.shields.io/github/v/release/ha-parcel-integrations/ha-early-bird.svg)](https://github.com/ha-parcel-integrations/ha-early-bird/releases)
[![Downloads](https://img.shields.io/github/downloads/ha-parcel-integrations/ha-early-bird/total.svg)](https://github.com/ha-parcel-integrations/ha-early-bird/releases)
[![HACS](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> 📦 Part of [**ha-parcel-integrations**](https://ha-parcel-integrations.github.io/), a family of package-tracking integrations for Home Assistant that all publish the same parcel format, statuses and events, so they plug into cross-carrier automations and the optional [Parcel Aggregator](https://github.com/ha-parcel-integrations/ha-parcel-aggregator). Browse the other carriers on the website.
>
> 💬 Questions or feedback? Join the discussion on the [Home Assistant community](https://community.home-assistant.io/t/packages-postnl-dhl-nl-dpd-and-gls-parcel-integration/112433/).

> **Pre-1.0.** Early Bird reports status as free text only, and the integration has been checked against 12 real parcels, 11 of them delivered. Wording for out for delivery and for a parcel returning to the sender has never been seen, so those show as the previous status or `unknown` until reported. The same goes for a parcel handed over to another carrier. Each case logs one warning; please [open an issue](https://github.com/ha-parcel-integrations/ha-early-bird/issues/new?template=unrecognised_status.yml) with the logged line.

A custom Home Assistant integration that tracks your [Early Bird](https://earlybird.se) parcels, the Swedish early-morning and evening home delivery service. No account is needed — you enter the tracking code yourself, just like on the Early Bird website.

## Contents

- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Options](#options)
- [Removal](#removal)
- [Sensors](#sensors)
- [Parcel status reference](#parcel-status-reference)
- [Events](#events)
- [Services](#services)
- [Examples](#examples)
- [Debugging](#debugging)
- [Troubleshooting](#troubleshooting)
- [Related integrations](#related-integrations)
- [Disclaimer](#disclaimer)
- [Contributing](#contributing)
- [License](#license)

## Features

- Track any number of Early Bird parcels by tracking code — no account needed
- Per-parcel sensor with the canonical status (`registered` / `in_transit` / `at_pickup_point` / `delivered` / …), the carrier's own status text and a tracking deep-link
- Summary sensors: incoming parcels, en route to pickup point, awaiting pickup, next delivery, recently delivered parcels
- Read-only **Deliveries** calendar (stays empty: Early Bird reports no delivery window)
- `early_bird.track_parcel` / `early_bird.untrack_parcel` services, so a dashboard button can add a parcel
- Events + device triggers for no-code automations (parcel registered, status changed, delivered)
- Opt-in per-parcel status history
- Manual refresh button and a diagnostic last-update sensor

## Requirements

- Home Assistant 2025.12 or newer
- An Early Bird parcel and its tracking code (from the notification link or
  message you received) — no account needed

## Installation

### HACS (recommended)

1. In HACS, choose the three-dot menu → **Custom repositories**.
2. Add `https://github.com/ha-parcel-integrations/ha-early-bird` as an **Integration**.
3. Install **Early Bird** and restart Home Assistant if HACS asks you to.

Or click the button below to open it directly in HACS:

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=ha-parcel-integrations&repository=ha-early-bird&category=integration)

### Manual

Copy `custom_components/early_bird` into your `config/custom_components/` folder and restart Home Assistant.

## Configuration

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=early_bird)

Or set it up by hand: add the integration via **Settings → Devices & Services → Add Integration → Early Bird**. There is nothing to fill in: the hub is created immediately (Early Bird tracking needs no account).

Then add parcels via the integration's **Configure** dialog, the [`early_bird.track_parcel`](#services) service, or a [dashboard button](examples/dashboards/add_parcel_card.yaml). The tracking code is in the notification Early Bird sends you.

## Options

Open **Configure** on the integration entry:

| Section | Option | Default | Description |
|---|---|---|---|
| Parcels | Add / remove | — | Manage the tracked tracking codes. Changes apply immediately, no restart. |
| Delivered parcels | Filter by / amount | last 7 days | How long delivered parcels stay visible on the delivered sensor. |
| Parcel history | Include status history | off | Adds a `history` attribute per parcel with each status update. |

Polling isn't one of these settings: the integration polls on a dynamic,
status-driven schedule with nothing to configure.

## Dynamic polling

Polling isn't a setting here — the integration adjusts its own cadence to
what your tracked parcels are actually doing:

- **Quiet hours** — no polling between 00:00–06:00 local time, aside from one
  catch-up check at each end of that window (around midnight and around 6
  AM), so an overnight update is never missed.
- **Hot (every 15 minutes)** — while any tracked parcel is out for delivery
  today, starting an hour before its delivery window opens (or immediately if
  no window is known yet).
- **Normal (every 45 minutes)** — for anything else still on its way.
- **Fully paused** — once every tracked parcel has been delivered, or nothing
  is tracked at all, polling stops until you add a parcel back (adding one
  always triggers an immediate check, regardless of the pause).
- A small, fixed per-hub offset is added on top, so not every Early Bird
  hub out there polls at exactly the same second.

Early Bird reports neither an out-for-delivery status nor a delivery window, so the hot tier is never used: a parcel in flight is checked every 45 minutes until it is delivered.

## Removal

Standard HA removal applies: **Settings → Devices & Services → Early Bird → ⋮ → Delete**. Nothing is stored on Early Bird's side.

## Sensors

| Entity | Description |
|---|---|
| `sensor.early_bird_incoming_parcels` | Number of active tracked parcels, full list under the `parcels` attribute |
| `sensor.early_bird_parcel_<code>` | One per tracked parcel; state is the canonical status, attributes carry the full normalised parcel |
| `sensor.early_bird_next_delivery` | Earliest expected delivery moment across all active parcels; stays empty, since Early Bird reports no delivery window |
| `sensor.early_bird_en_route_to_pickup_point` | Parcels being rerouted to a parcel locker, not there yet |
| `sensor.early_bird_awaiting_pickup` | Parcels ready to collect from a parcel locker |
| `sensor.early_bird_delivered_parcels` | Recently delivered parcels (see the retention option) |
| `sensor.early_bird_last_successful_update` | Diagnostic: when Early Bird was last polled successfully |

A delivered parcel moves from its per-parcel sensor to the delivered sensor automatically.

## Parcel status reference

The `status` field is the carrier-agnostic enum shared by the whole integration family:

| Status | Meaning |
|---|---|
| `registered` | The sender has booked the delivery with Early Bird |
| `in_transit` | Received by Early Bird, at a terminal, on its way, or being rerouted to a locker |
| `at_pickup_point` | Ready to collect from a parcel locker |
| `delivered` | Delivered to the door or mailbox, or collected from the locker |
| `problem` | A delivery attempt failed (blocked entrance, no one reachable) |
| `unknown` | Not found yet, or wording we have not mapped yet |

A new delivery attempt keeps the status of the event before it. A locker is a pickup point: from the reroute announcement on, `pickup` is true, so the parcel counts under *en route to pickup point* and then *awaiting pickup*. The locker itself is never named, so `pickup_point` stays empty.

The carrier's own human-readable text is always available as `raw_status`.

## Events

The integration fires these on the event bus (also available as device triggers on the Early Bird device):

| Event | When |
|---|---|
| `early_bird_parcel_registered` | A new parcel appears in the active list |
| `early_bird_parcel_status_changed` | A parcel's canonical status changes (`old_status` / `new_status` in the payload), except the final hop to delivered |
| `early_bird_parcel_delivered` | A parcel is delivered |

Every payload is the full normalised parcel plus the hub's `device_id`. Events are suppressed on the first refresh after start-up.

## Services

| Service | Fields | Description |
|---|---|---|
| `early_bird.track_parcel` | `tracking_code` | Start tracking a parcel |
| `early_bird.untrack_parcel` | `tracking_code` | Stop tracking a parcel |

## Examples

Ready-to-paste automations and dashboard snippets live in [`examples/`](examples/), including tracking a new parcel straight from a dashboard.

### Community Lovelace cards

Third-party cards that work with this integration's sensors:

- [jonisnet/hki-parcels-card](https://github.com/jonisnet/hki-parcels-card)
- [klaptafel/ha-package-tracker-card](https://github.com/klaptafel/ha-package-tracker-card)

## Debugging

```yaml
logger:
  logs:
    custom_components.early_bird: debug
```

## Troubleshooting

- **A parcel shows `unknown`** — Early Bird does not know the code (yet), the code is wrong, or the service no longer keeps an old parcel. It picks up automatically once Early Bird reports it.
- **A status logs "Unrecognised Early Bird status"** — please [open an issue](https://github.com/ha-parcel-integrations/ha-early-bird/issues/new?template=unrecognised_status.yml) with the logged line so the mapping can be extended.

## Related integrations

This integration is part of [**ha-parcel-integrations**](https://ha-parcel-integrations.github.io/) — a family of
parcel-carrier integrations that all publish the same canonical parcel format,
statuses and events.

- [**Parcel Aggregator**](https://github.com/ha-parcel-integrations/ha-parcel-aggregator) rolls every installed carrier
  up into one set of sensors.
- Browse [the organisation](https://ha-parcel-integrations.github.io/) for the current list of supported carriers.

## Disclaimer

This is an independent, community-built project. It is not affiliated with, endorsed by, sponsored by, or supported by Early Bird, Home Assistant, or any other third party referenced in this project. Please don't contact Early Bird for support with this integration.

All third-party trademarks, trade names, product names, logos, and other brand assets are the property of their respective owners. References to them are solely to identify the relevant carrier or service and do not imply affiliation, sponsorship, or endorsement. Nothing in this project grants or implies any licence or right to use third-party brand assets.

This integration may rely on public, unofficial, or undocumented carrier interfaces, accessed with your own account or API key where required. These may change or be withdrawn without notice and may be subject to Early Bird's terms. Data is sent only to Early Bird's own services or those of its group; this project operates no servers of its own. You are responsible for ensuring that your use complies with applicable law and those terms. Use is at your own risk; see the [licence](LICENSE) for warranty limitations.

This integration uses the same public tracking endpoint as the Early Bird consumer website.

## Contributing

Pull requests and issues are welcome. Please open an issue before
submitting a large change.

## License

[MIT](LICENSE)
