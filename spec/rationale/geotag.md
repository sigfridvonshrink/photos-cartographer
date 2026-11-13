# Geotag — why

**Not normative.** Each item here is the reasoning behind the [intent](../intent/geotag.md) or [build](../build/geotag.md)
items it `justifies`, under the same section numbers. Where the two differ, the intent wins and this is stale.

## 2. Core workflow rule

:::{rat} A position is looked up by time
:id: RAT-position_follows_time
:status: ruled
:justifies: RUL-time_before_gps

A photo with no position of its own is placed where the track was at the moment it was taken — its true time, after
the camera's clock is corrected. Placed before that time is settled, it would be placed at the wrong moment of the
track, possibly kilometres off, and every position would have to be planned again once the time changed. So the time
is settled for every photo first, and only then is any position planned.
:::

:::{rat} No phase invents a time
:id: RAT-no_phase_invents_time
:status: ruled
:justifies: RUL-untimed_photo_stops_geotag

A photo with no recorded time has nothing to correct and nothing to look up: its true time is unknown, and no
camera's offset or destination's timezone can supply one. Prep sets such a photo aside in missing metadata for the
user to deal with by hand. Sorted into a destination anyway, it would pass through geotag's decisions with nothing to
ask about it and stop only at the last plan, where nothing the user could decide would clear it. Stopping at the start,
naming it and where it belongs, makes the one possible fix plain.
:::
