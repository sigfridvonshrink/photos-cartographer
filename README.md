# digikam-to-immich

This repository contains a suite of scripts designed to manage, convert, and synchronize a high-quality photo library between **digiKam** (for management and storage) and **Immich** (for display and sharing).

## Workflow & Naming Convention

The workflow revolves around a "standardized" file naming convention using the `__std` suffix. These files are derived from original RAW or high-quality TIFF assets:

-   **`*__std.jpg`**: High-quality JPEG files processed specifically for display within the Immich web/mobile interface.
-   **`*__std.jxl`**: JPEG XL files used for long-term, high-efficiency storage.

## Repository Structure

The scripts are organized based on where they are intended to run and the type of tasks they perform.

### General Operation

Most scripts in this repository follow a set of common principles:

-   **Required Execution Mode**: Scripts that modify the photo archive require an explicit execution mode flag:
    -   `--execute`: Actually perform the changes.
    -   `--dry-run`: Preview what the script would do without modifying any files.
    *Running these scripts without one of these flags (or without any arguments) will display the help text.*
-   **Parallel Processing**: Orchestrator scripts and some standalone tools support a `-j` or `--jobs` flag to control the number of parallel workers (defaulting to the system's CPU count).
-   **Logging & Progress**: Scripts provide real-time progress updates, often including ETA and status summaries.
-   **Idempotency**: Conversion and tagging scripts are designed to be idempotent, skipping files that have already been processed unless an `--overwrite` flag is used.

### 1. `ingest/` (active pipeline)
The **active** part of the project: a safety-first ingestion and GPS/time-calibration pipeline. It takes
an unorganized dump of photos, leaves a clean deduplicated date-organized working set, then resolves each
photo to real UTC, automatically corrects a wrong camera clock against your GPX tracks, and geotags
everything from the track — all **plan → validate → execute**, with nothing deleted and nothing mutated
without a validated plan. Behavior is defined by the specifications in `ingest/workflows/`.

See **[`ingest/README.md`](ingest/README.md)** for details.

### 2. `convert/` (Compute Node)
Computationally expensive image-conversion tools, designed to run on a **compute node** with high CPU
resources (AI rotation detection benefits from a GPU). They produce the `__std` display/storage masters
from RAW/TIFF originals.

See **[`convert/README.md`](convert/README.md)** for the full script list.

### 3. `develop/` (development workspace)
`photos-developer` manages the photo **development workspace** — preparing, auditing, and safely tearing
down the staging area where RAW/JPEG originals become finalized `__std.tif` display masters.

See **[`develop/README.md`](develop/README.md)** for details.

### 4. `immich/` (Immich Backend)
Scripts that integrate the digiKam library with Immich (timeline-visibility sync and the hardlinked "TV"
folder), meant to run on the **Immich backend server**.

See **[`immich/README.md`](immich/README.md)** for details and the `photos-cfg.json` shape.

---

## Dependencies

### System Dependencies
-   **`exiftool`**: Required for all metadata operations.
-   **`magick`** (ImageMagick v7): Used for image decoding and processing.
-   **`cjpegli`**: For high-quality JPEG encoding.
-   **`avifenc`**: For AVIF encoding.
-   **`cjxl`**: For JPEG XL encoding.
-   **`ffmpeg`**: Used in AVIF conversion pipelines.

### Python Libraries
-   `torch`, `torchvision`, `numpy` & `huggingface_hub` (for AI-powered tasks)
-   `requests` (for Immich API interaction)
-   `pymysql` (for digiKam database access)
-   `pillow` (PIL)

---

## Archive
The `archive/` directory holds standalone legacy tools kept for reference. Unlike the removed
reengineering prototype, these still implement functionality the active pipeline does **not** cover:

-   Direct-mutation digiKam↔Immich integration scripts (`photos-dk2im-sync`, `photos-im2dk-sync`,
    `photos-dk-pick-std-jpg`, `photos-im-mark`, `photos-gps-sync-xmp`, `photos-fix-exif-dates`).
-   `archive/storage/legacy-utils/` — the `photocheck-*` library-audit scripts and `photoflow.py`.

The phase-gated reengineering specs, the monolithic `photos-ingest` prototype that `ingest/` was split
out of, and the superseded `photos-gps-tagger` have been removed; their behavior now lives in `ingest/`.
