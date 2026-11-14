"""Test helper: the destination zone answered once at the root of photos by destination, as the user answers it.

The configured default timezone is only proposed (geotag §18): a workspace fixture that wants its destinations' zone
known answers it at `6-photos-by-dest`, and every destination beneath inherits it."""
import json
import os

ROOT = "6-photos-by-dest"


def with_root_zone(prior=None, tz="Europe/Brussels"):
    """`prior` (a photos-21 record, or None) with the zone written by hand at the root; returns a new dict."""
    prior = json.loads(json.dumps(prior or {}))
    root = prior.setdefault("destinations", {}).setdefault(ROOT, {})
    root.setdefault("destination_timezone", {}).setdefault("user_decision", {})["manual_iana_timezone"] = tz
    return prior


def answer_root_zone(ctl, tz="Europe/Brussels"):
    """Write the root's zone into the workspace's photos-21, creating it if geotag has not planned yet."""
    p = os.path.join(str(ctl), "photos-21-time-decisions.json")
    prior = json.load(open(p)) if os.path.exists(p) else None
    with open(p, "w") as f:
        json.dump(with_root_zone(prior, tz), f)
