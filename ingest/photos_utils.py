import os
import json
import hashlib
import re

CONFIG = {
    "zfs": {
        "enabled": False,                # opt-in; the dataset is auto-detected from the workspace
        "snapshots_required": False,     # if true, failure to snapshot aborts execution
        "snapshot_prefix": "photos-ingest-",   # prepended to the plan id: <dataset>@<prefix><plan_id>
        "datasets": {
            "workspace": "auto",         # "auto" = detect from the workspace path; or an explicit dataset
            "library": "auto"            # reserved for the future finalize/merge step (not used by prep)
        }
    },
    "gpx_root": "",
    "gpx_direct_match_max_seconds": 60.0,
    "gpx_interpolation_max_gap_seconds": 120.0,
    "gpx_interpolation_max_distance_meters": 1000.0,
    "gpx_interpolation_max_speed_kmh": 150.0,
    "photo_anchor_interpolation_max_gap_seconds": 1800.0,
    "photo_anchor_extrapolation_max_seconds": 300.0,
    "camera_time_and_timezone_policy": {
        "enabled": False,
        "default_folder_timezone": "",
        "device_groups": {
            "phones": [],
            "fixed_clock_cameras": []
        },
        "single_anchor_auto_apply": False,
        "multi_anchor_auto_apply": True,
        "phone_gpx_agreement_tolerance_seconds": 60,
        "phone_gpx_conflict_threshold_seconds": 300,
        "dst_conflict_tolerance_seconds": 120,
        "phone_gpx_max_distance_meters": 250,
        "write_corrected_metadata_times": True,
        "write_corrected_offset_tags": True,
        "write_corrected_filename_times": True,
        "manual_segment_template_count": 2
    },
    "filename_timestamp_format": "%Y-%m-%d--%H-%M-%S"
}

def selected_gpx_root() -> str:
    root = CONFIG.get("gpx_root") or ""
    return os.path.realpath(os.path.abspath(root)) if root else ""

# Media classification by extension (prep Section 6.1) — the single source of truth.
_MEDIA_CLASS_BY_EXT = {}
_MEDIA_CLASS_BY_EXT.update({e: "image" for e in ("jpg", "jpeg", "png", "heic", "tiff")})
_MEDIA_CLASS_BY_EXT.update({e: "raw" for e in ("cr2", "cr3", "nef", "arw", "dng")})
_MEDIA_CLASS_BY_EXT.update({e: "video" for e in ("mp4", "mov", "avi", "mkv")})

def media_class_for_ext(ext: str) -> str:
    """Classify a file by extension into image/raw/video/other (case-insensitive,
    leading dot optional)."""
    return _MEDIA_CLASS_BY_EXT.get((ext or "").lower().lstrip('.'), "other")

# Camera-identity fields that compose the camera_group_key (order matters: it defines
# the key string). The handoff surfaces the same fields as a group's contributing identity.
CAMERA_IDENTITY_FIELDS = [
    "BodySerialNumber", "CameraSerialNumber", "InternalSerialNumber",
    "SerialNumber", "Make", "Model", "OwnerName",
]

# --- Workspace control directory layout (shared contract Section 5) ----------
# Every pipeline control/artifact file lives under CONTROL_DIR; the media scan
# skips it wholesale. These helpers are the single source of truth for the names
# and locations so the writers and the scanner can never disagree.
CONTROL_DIR = ".photos-ingest"
QUARANTINE_DIR = ".photos-ingest-quarantine"

def control_dir(ws: str) -> str:
    return os.path.join(ws, CONTROL_DIR)

def guard_path(ws: str) -> str:
    return os.path.join(ws, CONTROL_DIR, "photos-00-workspace-guard")

def config_path(ws: str) -> str:
    # Location only in this phase; the seed/read lifecycle lands in the next phase.
    return os.path.join(ws, CONTROL_DIR, "photos-00-config.json")

def db_path(ws: str) -> str:
    return os.path.join(ws, CONTROL_DIR, "photos-00-ingest.db")

def handoff_path(ws: str) -> str:
    return os.path.join(ws, CONTROL_DIR, "photos-11-handoff.json")

def journal_path(ws: str, run_id: str) -> str:
    return os.path.join(ws, CONTROL_DIR, f"journal-{run_id}.json")

def lock_path(ws: str) -> str:
    return os.path.join(ws, CONTROL_DIR, "photos-00-workspace.lock")

def ensure_control_dir(ws: str) -> str:
    d = control_dir(ws)
    os.makedirs(d, exist_ok=True)
    return d

def quarantine_dir(ws: str) -> str:
    return os.path.join(ws, QUARANTINE_DIR)

def quarantine_footprint(ws: str) -> dict:
    """Summarize the recoverable quarantine tree. Quarantine is never auto-deleted,
    so every run surfaces how much has accumulated (files, bytes, distinct <plan_id>
    directories, and the oldest/newest plan id present). Plan-id directory names sort
    chronologically (the %Y%m%dT%H%M%SZ-<hex> prefix), so oldest/newest = min/max name.
    """
    base = quarantine_dir(ws)
    total_files = 0
    total_bytes = 0
    plan_ids = []
    if os.path.isdir(base):
        for entry in os.scandir(base):
            if not entry.is_dir():
                continue
            plan_ids.append(entry.name)
            for root, _dirs, fnames in os.walk(entry.path):
                for fn in fnames:
                    if fn == "manifest.json":
                        continue
                    try:
                        total_bytes += os.path.getsize(os.path.join(root, fn))
                        total_files += 1
                    except OSError:
                        pass
    plan_ids.sort()
    return {
        "total_files": total_files,
        "total_bytes": total_bytes,
        "plan_id_dirs": len(plan_ids),
        "oldest_plan_id": plan_ids[0] if plan_ids else None,
        "newest_plan_id": plan_ids[-1] if plan_ids else None,
    }

def _atomic_write_text(path: str, text: str) -> None:
    import tempfile
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise

def load_or_seed_config(workspace_root: str) -> str:
    """Seed `photos-00-config.json` from the in-code CONFIG template on first run,
    then read it as the authoritative config for this workspace.

    Per the shared contract (Section 4), the on-disk file — not the in-code dict —
    governs all processing once it exists; prep is its sole writer (seeds once). The
    user changes configuration by hand-editing the JSON. Returns the whole-file
    SHA-256 (the config fingerprint). `jobs` is a runtime override and is never
    persisted to the file.
    """
    ensure_control_dir(workspace_root)
    path = config_path(workspace_root)
    if not os.path.exists(path):
        seed = {k: v for k, v in CONFIG.items() if k != "jobs"}
        _atomic_write_text(path, json.dumps(seed, indent=2, sort_keys=True))
    with open(path, "rb") as f:
        raw = f.read()
    sha = hashlib.sha256(raw).hexdigest()
    try:
        loaded = json.loads(raw.decode("utf-8"))
    except Exception as e:
        raise ValueError(f"Workspace config {path} is not valid JSON: {e}")
    if not isinstance(loaded, dict):
        raise ValueError(f"Workspace config {path} must be a JSON object.")
    validate_config(loaded)  # human-authored input is validated before it is accepted
    # Make the file authoritative; preserve the runtime jobs override.
    jobs = CONFIG.get("jobs")
    CONFIG.clear()
    CONFIG.update(loaded)
    if jobs is not None:
        CONFIG["jobs"] = jobs
    return sha


# ZFS naming charsets. A snapshot is <dataset>@<snapshot_prefix><plan_id>; the suffix
# (prefix + plan id) and the dataset name use these conservative legal charsets.
ZFS_SNAPSHOT_NAME_RE = re.compile(r"^[A-Za-z0-9_.:-]*$")
ZFS_DATASET_RE = re.compile(r"^[A-Za-z0-9_.:/-]+$")


def validate_config(cfg: dict):
    """Validate human-authored config before it is accepted — a general principle: input a
    human writes is validated, not trusted. Currently validates the `zfs` block. Raises
    ValueError with a clear message on any violation; missing keys default and unknown keys
    are ignored. (Hook for broader config/decision validation later.)"""
    z = cfg.get("zfs")
    if z is None:
        return
    if not isinstance(z, dict):
        raise ValueError("config: 'zfs' must be an object.")
    for k in ("enabled", "snapshots_required"):
        if k in z and not isinstance(z[k], bool):
            raise ValueError(f"config: zfs.{k} must be a boolean.")
    prefix = z.get("snapshot_prefix", "")
    if not isinstance(prefix, str) or not ZFS_SNAPSHOT_NAME_RE.match(prefix):
        raise ValueError(f"config: zfs.snapshot_prefix {prefix!r} is not a legal ZFS snapshot "
                         f"name (allowed characters: letters, digits, and _ . : -).")
    datasets = z.get("datasets", {})
    if not isinstance(datasets, dict):
        raise ValueError("config: zfs.datasets must be an object.")
    for tgt, val in datasets.items():
        if val == "auto":
            continue
        if not isinstance(val, str) or not ZFS_DATASET_RE.match(val):
            raise ValueError(f"config: zfs.datasets.{tgt} {val!r} must be 'auto' or a legal dataset name.")


def detect_zfs_dataset(path: str):
    """Return the name of the ZFS dataset backing `path`, or None. Resolves to a real
    absolute path first, so a bare '.' (which `zfs list` rejects) becomes a valid argument."""
    import subprocess
    abspath = os.path.realpath(os.path.abspath(path))
    try:
        res = subprocess.run(["zfs", "list", "-H", "-o", "name", abspath],
                             capture_output=True, text=True, check=True)
        name = res.stdout.strip()
        return name or None
    except Exception:
        return None

FIELD_SET_VERSION = 1
METADATA_SCHEMA_VERSION = 1
CAMERA_GROUP_KEY_VERSION = 1

EXIFTOOL_METADATA_OPTIONS = ["-json", "-n", "-a"]
EXTRACTION_OPTIONS_FINGERPRINT = hashlib.sha256(json.dumps(EXIFTOOL_METADATA_OPTIONS).encode('utf-8')).hexdigest()

def get_exiftool_version() -> str:
    import subprocess
    try:
        return subprocess.check_output(["exiftool", "-ver"], text=True).strip()
    except Exception:
        return "unknown"

_IMAGEMAGICK_VERSION = None
def get_imagemagick_version() -> str:
    """Resolve the ImageMagick version string once per process.

    The content (pixel) hash is bound to this value: a magick upgrade restales
    image/raw content hashes so they are recomputed rather than silently mixing
    signatures from different engine versions.
    """
    global _IMAGEMAGICK_VERSION
    if _IMAGEMAGICK_VERSION is not None:
        return _IMAGEMAGICK_VERSION
    import subprocess, shutil
    tool = "magick" if shutil.which("magick") else ("identify" if shutil.which("identify") else None)
    if tool:
        try:
            out = subprocess.check_output([tool, "--version"], text=True, stderr=subprocess.DEVNULL)
            first = out.splitlines()[0].strip() if out else ""
            if first:
                _IMAGEMAGICK_VERSION = first
                return _IMAGEMAGICK_VERSION
        except Exception:
            pass
    _IMAGEMAGICK_VERSION = "unknown"
    return _IMAGEMAGICK_VERSION

_IDENTIFY_COMMAND = None
def get_identify_command() -> list:
    """Return the argv prefix for ImageMagick's identify (cached), or [] if unavailable."""
    global _IDENTIFY_COMMAND
    if _IDENTIFY_COMMAND is not None:
        return _IDENTIFY_COMMAND
    import shutil
    if shutil.which("magick"):
        _IDENTIFY_COMMAND = ["magick", "identify"]
    elif shutil.which("identify"):
        _IDENTIFY_COMMAND = ["identify"]
    else:
        _IDENTIFY_COMMAND = []
    return _IDENTIFY_COMMAND

import concurrent.futures
import subprocess
from typing import Dict, List, Any, Optional


class ProcessCrashedError(Exception):
    pass

class PersistentExifToolWorker:
    def __init__(self):
        self.closed = False
        self._start_process()

    def _start_process(self):
        self.process = subprocess.Popen(
            ['exiftool', '-stay_open', 'True', '-@', '-'],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1
        )

    def restart(self):
        self.close()
        self._start_process()
        self.closed = False

    def close(self):
        if not self.closed:
            try:
                self.process.stdin.write("-stay_open\nFalse\n")
                self.process.stdin.flush()
                self.process.stdin.close()
            except Exception:
                pass
            try:
                self.process.wait(timeout=2)
            except Exception:
                self.process.kill()
            self.closed = True

    def read_metadata(self, folder_path: str) -> Dict[str, Any]:
        if self.closed:
            raise ProcessCrashedError("Worker closed")
        try:
            # EXIFTOOL_METADATA_OPTIONS is ["-json", "-n", "-a"]
            # We send them via stdin to the stay_open process
            for opt in EXIFTOOL_METADATA_OPTIONS:
                self.process.stdin.write(f"{opt}\n")
            self.process.stdin.write(f"{folder_path}\n-execute\n")
            self.process.stdin.flush()
        except OSError as e:
            raise ProcessCrashedError(f"Failed to write to exiftool: {e}")

        output = []
        while True:
            try:
                line = self.process.stdout.readline()
            except OSError as e:
                raise ProcessCrashedError(f"Failed to read from exiftool: {e}")

            if not line:
                raise ProcessCrashedError("Unexpected EOF from exiftool process.")
            if line.strip() == "{ready}":
                break
            output.append(line)

        full_out = "".join(output).strip()
        if not full_out:
            return {}

        try:
            data = json.loads(full_out)
            results = {}
            if isinstance(data, list):
                for item in data:
                    src = item.get("SourceFile")
                    if src:
                        results[src] = MetadataReader._parse_exiftool_item(item)
            elif isinstance(data, dict):
                 src = data.get("SourceFile")
                 if src:
                     results[src] = MetadataReader._parse_exiftool_item(data)
            return results
        except json.JSONDecodeError:
            pass
        return {}


import threading
import queue

class ExifToolWorkerPool:
    def __init__(self, size=4):
        self.size = size
        self.workers = queue.Queue()
        self._all_workers = []
        self._lock = threading.Lock()

    def __enter__(self):
        with self._lock:
            for _ in range(self.size):
                worker = PersistentExifToolWorker()
                self._all_workers.append(worker)
                self.workers.put(worker)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.shutdown()

    def shutdown(self):
        with self._lock:
            for worker in self._all_workers:
                worker.close()
            # Empty the queue so we don't hold references
            while not self.workers.empty():
                try:
                    self.workers.get_nowait()
                except queue.Empty:
                    break

    def acquire(self, timeout=30.0) -> PersistentExifToolWorker:
        return self.workers.get(timeout=timeout)

    def release(self, worker: PersistentExifToolWorker):
        if not worker.closed:
            self.workers.put(worker)

    def replace_or_restart(self, worker: PersistentExifToolWorker) -> PersistentExifToolWorker:
        try:
            worker.restart()
            return worker
        except Exception:
            # If we cannot restart it, force close/kill it
            try:
                worker.close()
            except Exception:
                try:
                    if hasattr(worker, 'process') and worker.process:
                        worker.process.kill()
                except Exception:
                    pass

            with self._lock:
                if worker in self._all_workers:
                    self._all_workers.remove(worker)

            # The replacement worker should only be added to _all_workers after it is successfully created.
            new_worker = PersistentExifToolWorker()
            with self._lock:
                self._all_workers.append(new_worker)
            return new_worker

    def execute(self, folder_path: str, progress_coordinator=None) -> Dict[str, Any]:
        try:
            worker = self.acquire()
        except queue.Empty:
            return {"error": "extraction_failed"} # Worker queue blocked forever

        try:
            result = worker.read_metadata(folder_path)
            return result
        except ProcessCrashedError as e:
            if progress_coordinator:
                progress_coordinator.increment("worker_crashes")
            worker = self.replace_or_restart(worker)
            return {"error": "extraction_failed"}
        except Exception as e:
            worker = self.replace_or_restart(worker)
            return {"error": "extraction_failed"}
        finally:
            if worker:
                self.release(worker)

class MetadataReader:
    @staticmethod
    def read_metadata(folder_path: str) -> Dict[str, Any]:
        """
        Reads metadata for a given folder in batch using exiftool -json.
        """
        cmd = ["exiftool"] + EXIFTOOL_METADATA_OPTIONS + [folder_path]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            if not res.stdout.strip():
                return {}
            data = json.loads(res.stdout)
            results = {}
            for item in data:
                src = item.get("SourceFile")
                if src:
                    results[src] = MetadataReader._parse_exiftool_item(item)
            return results
        except subprocess.CalledProcessError as e:
            if e.stdout.strip():
                try:
                    data = json.loads(e.stdout)
                    results = {}
                    for item in data:
                        src = item.get("SourceFile")
                        if src:
                            results[src] = MetadataReader._parse_exiftool_item(item)
                    return results
                except json.JSONDecodeError:
                    pass
            print(f"Warning: exiftool failed on {folder_path}: {e.stderr}")
            return {}

    @staticmethod
    def _parse_exiftool_item(item: Dict[str, Any]) -> Dict[str, Any]:
        parsed = {
            # Core timestamp fields
            "DateTimeOriginal": item.get("DateTimeOriginal"),
            "CreateDate": item.get("CreateDate"),
            "ModifyDate": item.get("ModifyDate"),

            # Timestamp sub-seconds and offsets
            "SubSecTimeOriginal": item.get("SubSecTimeOriginal"),
            "SubSecCreateDate": item.get("SubSecCreateDate"),
            "SubSecModifyDate": item.get("SubSecModifyDate"),
            "OffsetTime": item.get("OffsetTime"),
            "OffsetTimeOriginal": item.get("OffsetTimeOriginal"),
            "OffsetTimeDigitized": item.get("OffsetTimeDigitized"),
            "TimeZone": item.get("TimeZone"),

            # XMP / QuickTime timestamps
            "XMP:CreateDate": item.get("XMP:CreateDate"),
            "XMP:ModifyDate": item.get("XMP:ModifyDate"),
            "DateCreated": item.get("DateCreated"),
            "QuickTime:CreateDate": item.get("QuickTime:CreateDate"),
            "QuickTime:ModifyDate": item.get("QuickTime:ModifyDate"),
            "TrackCreateDate": item.get("TrackCreateDate"),
            "TrackModifyDate": item.get("TrackModifyDate"),
            "MediaCreateDate": item.get("MediaCreateDate"),
            "MediaModifyDate": item.get("MediaModifyDate"),

            # Camera identity fields
            "Make": item.get("Make"),
            "Model": item.get("Model"),
            "UniqueCameraModel": item.get("UniqueCameraModel"),
            "BodySerialNumber": item.get("BodySerialNumber"),
            "CameraSerialNumber": item.get("CameraSerialNumber"),
            "InternalSerialNumber": item.get("InternalSerialNumber"),
            "SerialNumber": item.get("SerialNumber"),
            "OwnerName": item.get("OwnerName"),
            "LensModel": item.get("LensModel"),
            "LensSerialNumber": item.get("LensSerialNumber"),

            # GPS fields
            "GPSLatitude": item.get("GPSLatitude"),
            "GPSLatitudeRef": item.get("GPSLatitudeRef"),
            "GPSLongitude": item.get("GPSLongitude"),
            "GPSLongitudeRef": item.get("GPSLongitudeRef"),
            "GPSAltitude": item.get("GPSAltitude"),
            "GPSAltitudeRef": item.get("GPSAltitudeRef"),
            "GPSDateStamp": item.get("GPSDateStamp"),
            "GPSTimeStamp": item.get("GPSTimeStamp"),
            "GPSDateTime": item.get("GPSDateTime"),
            "GPSProcessingMethod": item.get("GPSProcessingMethod"),

            # Dimensions
            "ImageWidth": item.get("ImageWidth"),
            "ImageHeight": item.get("ImageHeight"),
            "Orientation": item.get("Orientation"),
            "Rotation": item.get("Rotation"),
            "Duration": item.get("Duration"),

            # Full raw payload (needed by spec for preservation)
            "raw_payload": json.dumps(item)
        }

        # Build group_key for camera identity grouping based on standard elements
        ident_parts = []
        for k in CAMERA_IDENTITY_FIELDS:
            v = parsed.get(k)
            if v is not None:
                ident_parts.append(str(v).strip())
        parsed["camera_group_key"] = "|".join(ident_parts) if ident_parts else "unknown"

        # Passive boolean helper checks

        # Determine extraction_status for extracted_ok vs extracted_empty
        if parsed.get("DateTimeOriginal") or parsed.get("CreateDate") or parsed.get("ModifyDate") or parsed.get("Make") or parsed.get("Model"):
            parsed["extraction_status"] = "extracted_ok"
        else:
            parsed["extraction_status"] = "extracted_empty"

        parsed["has_native_gps"] = bool(parsed.get("GPSLatitude") is not None and parsed.get("GPSLongitude") is not None)
        parsed["has_timestamp"] = bool(parsed.get("DateTimeOriginal") or parsed.get("CreateDate") or parsed.get("ModifyDate"))

        # Timestamp provenance
        if parsed.get("DateTimeOriginal"):
            parsed["selected_source_naive_timestamp"] = parsed.get("DateTimeOriginal")
            parsed["selected_source_timestamp_tag"] = "DateTimeOriginal"
        elif parsed.get("CreateDate"):
            parsed["selected_source_naive_timestamp"] = parsed.get("CreateDate")
            parsed["selected_source_timestamp_tag"] = "CreateDate"
        elif parsed.get("ModifyDate"):
            parsed["selected_source_naive_timestamp"] = parsed.get("ModifyDate")
            parsed["selected_source_timestamp_tag"] = "ModifyDate"
        else:
            parsed["selected_source_naive_timestamp"] = None
            parsed["selected_source_timestamp_tag"] = None

        return parsed

    @classmethod
    def read_metadata_concurrently(cls, folders: List[str], max_workers: int = 4, progress_coordinator=None) -> tuple[Dict[str, Any], set[str]]:
        results = {}
        failed_folders = set()
        with ExifToolWorkerPool(size=max_workers) as pool:
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_folder = {executor.submit(pool.execute, f, progress_coordinator): f for f in folders}
                for future in concurrent.futures.as_completed(future_to_folder):
                    folder = future_to_folder[future]
                    try:
                        data = future.result()
                        if "error" in data:
                            failed_folders.add(folder)
                        else:
                            results.update(data)
                    except ProcessCrashedError:
                        if progress_coordinator:
                            progress_coordinator.increment("worker_crashes")
                        failed_folders.add(folder)
                    except Exception as exc:
                        failed_folders.add(folder)
                        print(f"Folder {folder} generated an exception: {exc}")
                    if progress_coordinator:
                        progress_coordinator.increment("metadata_extracted")
                        progress_coordinator.increment_completed()

        # Sort results by key deterministically
        return {k: results[k] for k in sorted(results.keys())}, failed_folders


def is_metadata_cache_fresh(file_record: dict, metadata_record: dict, current_metadata_context: dict) -> bool:
    if not metadata_record:
        return False

    # Check if relative_path matches (if available in both)
    if metadata_record.get('relative_path') and file_record.get('relative_path'):
        if metadata_record['relative_path'] != file_record['relative_path']:
            return False

    if metadata_record.get('size') != file_record.get('size'):
        return False
    if metadata_record.get('mtime_ns') != file_record.get('mtime_ns'):
        return False

    # Check content_hash if available in file_record
    file_hash = file_record.get('content_hash')
    if file_hash:
        if metadata_record.get('content_hash') != file_hash:
            return False

    # Check context dependencies
    if metadata_record.get('extractor') != current_metadata_context.get('extractor'):
        return False
    if metadata_record.get('extractor_version') != current_metadata_context.get('extractor_version'):
        return False
    if metadata_record.get('field_set_version') != current_metadata_context.get('field_set_version'):
        return False
    if metadata_record.get('extraction_options_fingerprint') != current_metadata_context.get('extraction_options_fingerprint'):
        return False
    if metadata_record.get('metadata_schema_version') != current_metadata_context.get('metadata_schema_version'):
        return False
    if metadata_record.get('camera_group_key_version') != current_metadata_context.get('camera_group_key_version'):
        return False

    return True



import sys
import threading
import time

class ProgressCoordinator:
    def __init__(self, quiet=None):
        self.is_tty = sys.stderr.isatty()
        if quiet is None:
            self.quiet = not self.is_tty
        else:
            self.quiet = quiet
            if quiet:
                self.is_tty = False
        self.counters = {}
        self._lock = threading.Lock()
        self.current_phase = ""
        self.total_items = 0
        self.completed_items = 0
        self.start_time = time.time()
        self.last_print_time = 0

    def start_phase(self, phase_name: str, total_items: int = 0):
        with self._lock:
            self.current_phase = phase_name
            self.total_items = total_items
            self.completed_items = 0
            self.start_time = time.time()
            if not self.quiet:
                if self.is_tty:
                    print(f"\r\033[KStarting {phase_name}...", end="", file=sys.stderr)
                else:
                    print(f"Starting {phase_name}...", file=sys.stderr)

    def increment(self, counter_name: str, amount: int = 1):
        with self._lock:
            self.counters[counter_name] = self.counters.get(counter_name, 0) + amount

    def increment_completed(self, amount: int = 1):
        with self._lock:
            self.completed_items += amount
            self._render_progress()

    def _render_progress(self):
        if self.quiet:
            return

        now = time.time()
        if self.is_tty:
            if now - self.last_print_time > 0.1:
                self.last_print_time = now
                pct = ""
                if self.total_items > 0:
                    pct = f" ({self.completed_items / self.total_items * 100:.1f}%)"
                print(f"\r\033[K{self.current_phase}: {self.completed_items}/{self.total_items}{pct} ...", end="", file=sys.stderr)
                sys.stderr.flush()
        else:
            if now - self.last_print_time > 10.0:
                self.last_print_time = now
                pct = ""
                if self.total_items > 0:
                    pct = f" ({self.completed_items / self.total_items * 100:.1f}%)"
                print(f"{self.current_phase}: {self.completed_items}/{self.total_items}{pct} ...", file=sys.stderr)

    def finish_phase(self):
        with self._lock:
            if not self.quiet:
                elapsed = time.time() - self.start_time
                if self.is_tty:
                    print(f"\r\033[KFinished {self.current_phase} in {elapsed:.2f}s", file=sys.stderr)
                else:
                    print(f"Finished {self.current_phase} in {elapsed:.2f}s", file=sys.stderr)

    def print_summary(self, plan_summary=None):
        # The run summary is a deliverable (prep Section 19), not transient progress, so
        # it prints even when live progress is quiet/redirected.
        report = (plan_summary or {}).get("report")
        if report:
            self._print_report(report, plan_summary)
            return
        if self.quiet:
            return
        # Fallback: the older flat performance list (no structured report present).
        print("\n--- Performance Summary ---", file=sys.stderr)
        if plan_summary and "performance_and_cache" in plan_summary:
            pc = plan_summary["performance_and_cache"]
            fields = [
                "jobs_requested", "progress_mode", "worker_crashes", "worker_restarts",
                "metadata_extracted", "metadata_reused", "metadata_failed",
                "hashes_computed", "hashes_reused", "hashes_failed",
                "db_effects_seen", "db_upserts_applied", "db_removes_applied", "db_renames_applied",
                "dependency_validation_status", "handoff_written_after_successful_validation"
            ]
            for f in fields:
                print(f"  {f}: {pc.get(f, 0 if 'applied' in f or 'failed' in f or 'crashes' in f or 'reused' in f or 'computed' in f or 'restarts' in f or 'seen' in f or 'extracted' in f else False)}", file=sys.stderr)
        else:
            for k, v in sorted(self.counters.items()):
                print(f"  {k}: {v}", file=sys.stderr)
        print("---------------------------", file=sys.stderr)

    def _print_report(self, r, plan_summary=None):
        """Render the prep run report (prep Section 19) as labelled categories."""
        pc = (plan_summary or {}).get("performance_and_cache", {}) or {}
        qf = r.get("quarantine_footprint", {}) or {}
        out = sys.stderr
        print("\n=== Prep run summary ===", file=out)
        print(f"  Media operations planned/executed : {r.get('media_operations', 0)}  "
              f"(cache ops: {r.get('cache_operations', 0)})", file=out)
        print(f"  No-op / already-correct           : {r.get('no_op_already_correct', 0)}", file=out)
        print(f"  Recognized moves (carried forward): {r.get('recognized_moves', 0)}", file=out)
        print(f"  By-dest files scanned read-only   : {r.get('by_dest_files_scanned_read_only', 0)}  "
              f"(mutated: {r.get('by_dest_mutated', 0)})", file=out)
        print(f"  Duplicates -> quarantine          : {r.get('duplicates_against_mutable', 0)} vs mutable, "
              f"{r.get('duplicates_against_by_dest', 0)} vs by-dest", file=out)
        print(f"  Metadata reused/extracted/carried/failed : "
              f"{r.get('metadata_reused', 0)}/{r.get('metadata_extracted', 0)}/"
              f"{r.get('metadata_carried_forward', 0)}/{r.get('metadata_failed', 0)}  "
              f"(extractor {r.get('extractor', '?')} {r.get('extractor_version', '?')}, "
              f"field-set v{r.get('field_set_version', '?')})", file=out)
        print(f"  Cache effects applied (upsert/remove/rename): "
              f"{pc.get('db_upserts_applied', 0)}/{pc.get('db_removes_applied', 0)}/"
              f"{pc.get('db_renames_applied', 0)}", file=out)
        print(f"  Camera groups / native-GPS / missing-timestamp : "
              f"{r.get('camera_groups_found', 0)} / {r.get('native_gps_files', 0)} / "
              f"{r.get('missing_timestamp_files', 0)}", file=out)
        print(f"  Blockers / warnings               : {r.get('blockers', 0)} / {r.get('warnings', 0)}", file=out)
        print(f"  Dependency validation             : {pc.get('dependency_validation_status', 'n/a')}  "
              f"(handoff written after validation: {pc.get('handoff_written_after_successful_validation', False)})",
              file=out)
        print(f"  Quarantine footprint              : {qf.get('total_files', 0)} files, "
              f"{qf.get('total_bytes', 0)} bytes across {qf.get('plan_id_dirs', 0)} plan(s) "
              f"(never auto-deleted)", file=out)
        print("========================", file=out)
