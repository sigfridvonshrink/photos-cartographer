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

### 1. `convert/` (Compute Node)
These scripts are computationally expensive and are designed to run on a **compute node** with high CPU resources.
*Note: Scripts utilizing AI models (e.g., rotation detection) benefit significantly from a GPU.*

-   **`photos-ai-check-rotation`**: Uses a deep learning model (EfficientNet) to detect the correct "upright" orientation of images and logs results to a CSV.
-   **`photos-jxl2final`**: A Python orchestrator that performs batch conversions of JXL files to other formats (e.g., AVIF, JPEG) in parallel. Supports `--execute`, `--dry-run`, and `-j`.
-   **`photos-jxl2jpg`**: A Bash script that stages JXL files locally and converts them to JPEG using `cjpegli` and `magick`.
-   **`photos-tiff2avif`**: A Bash script that converts TIFF files to AVIF using `avifenc`, ensuring proper color profile handling and metadata transfer.
-   **`photos-tiff2final`**: A Python orchestrator for batch converting TIFF files to JXL, AVIF, and JPEG. Supports `--execute`, `--dry-run`, and `-j`.
-   **`photos-tiff2jpg`**: A Bash script that stages TIFF files locally and converts them to JPEG using `cjpegli` and `magick`, preserving metadata and handling ICC profiles.
-   **`photos-tiff2jxl`**: A Bash script that stages TIFF files locally and converts them to JXL using `cjxl`.

### 2. `storage/` (Photo Storage Machine)
These scripts help organize and maintain the main photo library and should be run on the **storage machine** with direct/local access to the photo albums.

-   **`photos-gps-tagger`**: Scans the current folder and all subfolders for images missing GPS metadata and applies coordinates from a central `gps_coords.json` file. It features intelligent chronological interpolation/extrapolation between "native" GPS points. New folders discovered during scanning will attempt to auto-geocode a location estimate using OpenStreetMap Nominatim based on the directory path.
    The script operates in three main phases:
    1.  **Scanning Phase (`--generate-json`)**: Scans for specified files and updates `gps_coords.json`, performing auto-geocoding for new entries.
    2.  **Updating Phase (`--update-files`)**: Applies GPS coordinates to files based on the JSON and interpolation.
    3.  **Cleaning Phase (`--clean-json`)**: Removes orphaned directory entries from `gps_coords.json`.
    *Note: All write operations require the `--execute` flag; by default, the script runs in dry-run mode. This script should be executed from the root of your digiKam albums directory.*

### 3. `immich/` (Immich Backend)
These scripts manage the integration with Immich and should be run on the **Immich backend server**.

-   **`photos-sync-tv-folder`**: Syncs files from a source folder to a replica folder using hardlinks based on Immich timeline visibility. It ensures that only assets visible on the Immich timeline are present in the target "TV" folder, facilitating display on devices with limited library management. Supports `--execute` and `--config`.
-   **`photos-sync-visibility`**: Performs a bidirectional sync between the Immich "locked" (archive/timeline) status and the digiKam "Pick Label Accepted" tag. It uses a local SQLite database (`sync_state.db`) to track historical state changes. Supports `--execute`, `--dry-run`, and `--config`.

#### `photos-cfg.json`
Scripts in the `immich/` directory require a configuration file with the following structure:
```json
{
  "database": {
    "host": "localhost",
    "port": 3306,
    "user": "digikam",
    "password": "yourpassword",
    "name": "digikam"
  },
  "sync_db_path": "sync_state.db",
  "immich": {
    "url": "http://your-immich-host:2283/api",
    "api_key": "YOUR_IMMICH_API_KEY",
    "email": "your-email@example.com",
    "password": "your-immich-password",
    "pin_code": "1234",
    "path_tv_from": "/srv/immich-pics/ext",
    "path_tv_to": "/srv/immich-pics/tv"
  }
}
```

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
The `archive/` directory contains legacy scripts (such as the original `dk2im` conversion tools) kept for historical reference. These are not part of the active workflow.
