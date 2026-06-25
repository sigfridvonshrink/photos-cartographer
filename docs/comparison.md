# How photos-cartographer compares to existing tools

These are all good tools — several are better than this one at the thing they focus on. The point of
this table isn't that they're bad; it's that **none of them sits where this project needed to be**: runs
on Linux, open-source, working against a local owned library, and built as a reproducible pipeline rather
than an interactive one-shot. If one of them fits you, use it.

For *why* that combination is the niche — the design reasoning behind it — see
[Who is this for?](who-is-this-for.md).

| Tool | Open source | Runs on Linux | Auto clock-fix from track | Reproducible pipeline | Why not for me |
|---|---|---|---|---|---|
| **HoudahGeo** | No | No (Mac only) | Yes (reference frames) | No (interactive) | Mac-only and paid |
| **GeoSetter** | No | No (Windows only) | Partial | No (interactive) | Windows-only, effectively unmaintained |
| **Geolignment** | Yes | No (Mac only) | Yes (geosync slider) | No (interactive) | Mac-only native app |
| **gpscorrelate** | Yes | Yes | No (manual offset) | No (one-shot CLI) | No auto clock inference; no safety/idempotency envelope |
| **darktable** (geotag module) | Yes | Yes | No (reference-photo/manual) | No (catalog-bound) | Manual offset; lives inside darktable's catalog, not a standalone pipeline |
| **exiftool `-geotag`** | Yes | Yes | Manual (`Geosync`, multi-point) | No (primitive) | It's the engine, not a workflow — no organize/dedup/decisions/safety |
| **Lightroom** (Map) | No | No | No (manual offset) | No | Proprietary/subscription; not a local-owned-library pipeline |
| **Google / Apple Photos** | No | Web only | No | No | No track-based correction; not local/owned; no correctness control |

The detail behind the table:

- **HoudahGeo** — the closest in capability. It does the part I care about most: it trusts photos that
  already carry timezone info and uses them as reference points to correct the cameras that don't, then
  matches against the track. Genuinely good. But it's Mac-only and proprietary, so it can't run on Linux.
- **GeoSetter** — for years the free Windows standard, map-driven and capable. Windows-only and now
  effectively unmaintained, which is much of why this gap exists at all.
- **Geolignment** — open-source and nicely designed around a geosync slider with multi-track folders.
  It's a native macOS app, so again no good off the Mac.
- **gpscorrelate** — open-source, cross-platform, scriptable, handles multiple GPX files. But the clock
  offset is something you supply manually (e.g. from a photo of a GPS screen); it won't infer the offset
  from the frames that already have GPS, and it's a one-shot correlate-and-write, not a recoverable
  pipeline that organizes, deduplicates, tracks decisions, and resumes after a crash.
- **darktable** — the geotagging module is solid and cross-platform, but it's a reference-photo/manual
  offset workflow bound to darktable's own catalog/sidecars, rather than a standalone reproducible
  pipeline feeding a folder-based library.
- **exiftool `-geotag`** — the actual metadata engine (and `Geosync` even supports multi-point drift
  correction). It's a primitive, not a workflow: no organization, dedup, decision-tracking, or safety
  envelope. This project can sit *on top* of exiftool rather than competing with it.
- **Lightroom Map module** — fine if you're already in Lightroom, but proprietary/subscription, manual
  offset, and oriented around the catalog rather than a local owned folder tree.
- **Cloud (Google / Apple Photos)** — effortless for phone shooters and solves the *loss* fear, but does
  no track-based correction, isn't local or owned, and gives you no control over correctness.

What's distinct here, then, isn't a new technique — the matching and offset ideas exist above. It's the
*treatment*: a Linux, open-source, reproducible pipeline (plan/validate/execute, idempotent,
recoverable, crash-resumable, decisions captured as editable artifacts) for people who keep a local owned
library and run a logger. That combination is the niche the tools above leave open.
