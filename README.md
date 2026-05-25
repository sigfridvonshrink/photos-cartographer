# digikam-to-immich

This repository contains a suite of scripts designed to manage, convert, and synchronize a high-quality photo library between **digiKam** (for management and storage) and **Immich** (for display and sharing).

## Workflow & Naming Convention

The workflow revolves around a "standardized" file naming convention using the `__std` suffix. These files are derived from original RAW or high-quality TIFF assets:

-   **`*__std.jpg`**: High-quality JPEG files processed specifically for display within the Immich web/mobile interface.
-   **`*__std.jxl`**: JPEG XL files used for long-term, high-efficiency storage.

## Repository Structure

The scripts are organized based on where they are intended to run and the type of tasks they perform.

### 1. `convert/` (Compute Node)
These scripts are computationally expensive and are designed to run on a **compute node** with high CPU resources.
*Note: Scripts utilizing AI models (e.g., rotation detection) benefit significantly from a GPU.*

-   **`photos-ai-check-rotation`**: Uses a deep learning model (EfficientNet) to detect the correct "upright" orientation of images and logs results to a CSV.
-   **`photos-jxl2final`**: A Python orchestrator that performs batch conversions of JXL files to other formats (e.g., AVIF, JPEG) in parallel.
-   **`photos-jxl2jpg`**: A Bash script that stages JXL files locally and converts them to JPEG using `cjpegli` and `magick`.
-   **`photos-tiff2avif`**: A Bash script that converts TIFF files to AVIF using `avifenc`, ensuring proper color profile handling and metadata transfer.
-   **`photos-tiff2final`**: A Python orchestrator for batch converting TIFF files to JXL and AVIF.
-   **`photos-tiff2jxl`**: A Bash script that stages TIFF files locally and converts them to JXL using `cjxl`.

### 2. `storage/` (Photo Storage Machine)
These scripts help organize and maintain the main photo library and should be run on the **storage machine** with direct/local access to the photo albums.

-   **`photos-gps-tagger`**: Scans the current folder and all subfolders for images missing GPS metadata and applies coordinates from a central `gps_coords.json` file. It features intelligent chronological interpolation/extrapolation between "native" GPS points.
    The script operates in three main phases:
    1. **Scanning Phase (`--generate-json`)**: Scans for specified files and updates `gps_coords.json`.
    2. **Updating Phase (`--update-files`)**: Applies GPS coordinates to files based on the JSON and interpolation.
    3. **Cleaning Phase (`--clean-json`)**: Removes orphaned directory entries from `gps_coords.json`.
    *Note: All write operations require the `--execute` flag; by default, the script runs in dry-run mode.*

### 3. `immich/` (Immich Backend)
These scripts manage the integration with Immich and should be run on the **Immich backend server**.

-   **`photos-sync-visibility`**: Performs a bidirectional sync between the Immich "locked" (archive/timeline) status and the digiKam "Pick Label Accepted" tag. It uses a local SQLite database (`sync_state.db`) to track historical state changes.

---

## Configuration

The scripts in the `immich/` directory require a `photos-cfg.json` file.

### `photos-cfg.json` Structure
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
    "pin_code": "1234"
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
-   `torch` & `torchvision` (for AI-powered tasks)
-   `requests` (for Immich API interaction)
-   `pymysql` (for digiKam database access)
-   `pillow` (PIL)

---

## Archive
The `archive/` directory contains legacy scripts (such as the original `dk2im` conversion tools) kept for historical reference. These are not part of the active workflow.
