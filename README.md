# photos-cartographer

The **ingestion + GPS/time-calibration pipeline** for a high-quality photo library managed in
**digiKam**. It takes an unorganized dump of photos, leaves a clean deduplicated date-organized working
set, then resolves each photo to real UTC, automatically corrects a wrong camera clock against your GPX
tracks, and geotags everything from the track — all **plan → validate → execute**, with nothing deleted
and nothing mutated without a validated plan.

This repo was carved out of a larger digiKam↔Immich script suite; the conversion, develop-workspace,
Immich-sync, and legacy-archive components live in sibling repos. The `__std.jpg` / `__std.jxl`
display/storage masters they produce are referenced here but built elsewhere.

## `ingest/` (the pipeline)

The `photos_pipeline` package (prep / geotag / merge phases + the decision editor), its tests, and the
authoritative workflow specs in `ingest/workflows/`. Behavior is **specification-driven** — the markdown
specs are the source of truth.

See **[`ingest/README.md`](ingest/README.md)** for details, and `CLAUDE.md` for build/test/CLI contract.

### General operation

-   **Required Execution Mode**: every phase follows **plan → validate (dry-run) → execute**; planning
    never mutates and execution refuses to run against a stale or tampered plan.
-   **Parallel Processing**: a `-j` / `--jobs` flag controls parallel workers (defaults to CPU count).
-   **Logging & Progress**: real-time progress with ETA and status summaries.
-   **Idempotent & resumable**: reruns act on the diff; a crash mid-run is recoverable.

## Dependencies

### System tools
-   **`exiftool`**: all metadata read/write operations.
-   **`magick`** (ImageMagick v7): image decoding for fingerprinting.
-   **`ffmpeg`**: video handling.

### Python
-   `pymysql` (digiKam database access during merge)
-   `pillow` (PIL)

Test/build tooling only: `pytest` + `coverage` (`dev-requirements.txt`). The pipeline itself needs no
pip install — see `CLAUDE.md`.
