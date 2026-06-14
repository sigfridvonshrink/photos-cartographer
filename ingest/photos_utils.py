import os
import json
import hashlib
import re
import shutil
import tempfile
from datetime import datetime, timezone
import sqlite3
import ctypes
import errno
import fcntl
import contextlib
import socket

# --- Managed media folders (prep Section 3). The NAMES are config (single source of truth,
# seeded into photos-00-config.json); the ROLES, their dedup-retention order, which role is
# the inbox / read-only by-dest / strays, and photo-vs-video band membership are pipeline
# logic and stay in code here. Reference folders by role, never by literal name. ---
FOLDER_ROLES = ["sources", "strays", "missing_metadata", "redundant_jpgs",
                "videos_by_date", "photos_by_date", "photos_by_dest"]
DEFAULT_FOLDERS = {
    "sources": "0-sources",
    "strays": "1-strays",
    "missing_metadata": "2-missing-metadata",
    "redundant_jpgs": "3-redundant-jpgs",
    "videos_by_date": "4-videos-by-date",
    "photos_by_date": "5-photos-by-date",
    "photos_by_dest": "6-photos-by-dest",
}
# Dedup retention priority — highest-retained first (lower index wins a duplicate tie).
# `strays` is absent: non-media is never content-deduplicated.
FOLDER_DEDUP_PRIORITY = ["photos_by_dest", "photos_by_date", "videos_by_date",
                         "redundant_jpgs", "missing_metadata", "sources"]
# Roles prep scans/organizes: everything except `strays` (which prep writes but never scans).
_MANAGED_ROLES = ["sources", "missing_metadata", "redundant_jpgs",
                  "videos_by_date", "photos_by_date", "photos_by_dest"]

CONFIG = {
    "folders": dict(DEFAULT_FOLDERS),
    "zfs": {
        "enabled": False,                # opt-in; the dataset is auto-detected from the workspace
        "snapshots_required": False,     # if true, failure to snapshot aborts execution
        "snapshot_prefix": "photos-ingest-",   # snapshot name: <dataset>@<prefix><label>-<plan_id> (label = phase)
        "datasets": {
            "workspace": "auto",         # "auto" = detect from the workspace path; or an explicit dataset
            "library": "auto"            # reserved for the future finalize/merge step (not used by prep)
        }
    },
    "gpx_root": "/srv/pictures/gpslogs/gpx",
    "gpx_direct_match_max_seconds": 60.0,
    # The interpolation gap is intentionally generous: at a narrow destination (museum/castle/park)
    # the photographer is stationary or slow and GPS goes sparse/absent (indoors, tree cover,
    # battery-save), so bracketing track points can be far apart in TIME yet close in SPACE. The
    # distance + speed caps below are the real safety net (a long gap only interpolates if you moved
    # <1 km net), so the time gap can be large without placing a photo somewhere it wasn't. (Mirrors
    # photo_anchor_interpolation_max_gap_seconds, which is already 1800 for the same kind of bracket.)
    "gpx_interpolation_max_gap_seconds": 1800.0,
    "gpx_interpolation_max_distance_meters": 1000.0,
    "gpx_interpolation_max_speed_kmh": 150.0,
    # Position-based thresholds for the calibration time-anchor inference (calibration §19):
    # how close a native-GPS frame must be to a GPX point/segment to anchor its real time, and how
    # far supporting anchors' offsets may spread before they conflict. Consumed by calibration.
    "gpx_anchor_max_point_distance_meters": 30.0,
    "gpx_anchor_max_segment_distance_meters": 30.0,
    "gpx_anchor_offset_spread_max_seconds": 120.0,
    # How far past either end of the GPX track a photo's resolved time may be placed by velocity
    # extrapolation before it is left unplaced (calibration §23/§25 GPS placement).
    "gpx_extrapolation_max_seconds": 120.0,
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
    "filename_timestamp_format": "%Y-%m-%d--%H-%M-%S",
    # Format-distribution subfolder names that mark the later development/processing phase
    # (calibration spec Section 7.1). Their presence anywhere under 6-photos-by-dest hard-stops
    # calibration (development must not start before time/GPS are fixed). Consumed by calibration.
    "destination_distribution_subfolders": ["jpg", "tif"],
    # Library-merge settings (shared contract Section 4.3 item 7). Seeded by prep for
    # forward-compatibility but CONSUMED by the future merge phase, which does the deep
    # validation — library_root must be an existing directory outside the managed 0-6 tree, and
    # the policy values are enum-checked there (merge spec Section 4). Prep only type-validates.
    "merge": {
        "library_root": "/srv/pictures/5-finished",           # permanent library dir
        "placement_policy": "preserve_destination_structure", # by-dest -> library subpath mapping
        "collision_policy": "suffix_incoming"                 # different-content name clash -> rename the incoming file
    }
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


# Exiftool intermediates/backups of a media file: `<media>_exiftool_tmp` (the temp `-overwrite_original`
# writes then atomically renames over the original) and `<media>_original` (the backup exiftool keeps
# when `-overwrite_original` is NOT used). A clean Ctrl-C is self-cleaned by exiftool, but a hard kill
# (SIGKILL/OOM/power loss) can orphan one in a managed folder; prep recognizes and quarantines these
# (the live original is always intact — the rename is atomic). Calibration's writer also unlinks a
# stale `_exiftool_tmp` for a file right before it rewrites it.
_EXIFTOOL_ARTIFACT_SUFFIXES = ("_exiftool_tmp", "_original")

def exiftool_artifact_base(name: str) -> str:
    """If `name` is an exiftool intermediate/backup OF A MEDIA FILE, return the underlying media
    filename; otherwise None. The media-extension check on the stripped name keeps unrelated files
    (e.g. a user's `notes_original.txt`) from matching — only `<media-ext>_original` /
    `<media-ext>_exiftool_tmp` qualify."""
    for suffix in _EXIFTOOL_ARTIFACT_SUFFIXES:
        if name.endswith(suffix):
            base = name[: -len(suffix)]
            if base and media_class_for_ext(os.path.splitext(base)[1]) != "other":
                return base
    return None


def _folders(cfg=None):
    return ((cfg or CONFIG).get("folders") or DEFAULT_FOLDERS)

def folder_name(role, cfg=None) -> str:
    """The configured folder name for a role (e.g. 'photos_by_dest' -> '6-photos-by-dest')."""
    return _folders(cfg)[role]

def folder_role(name, cfg=None):
    """Reverse lookup: a folder name (or a path's top component) -> its role, or None."""
    for r, n in _folders(cfg).items():
        if n == name:
            return r
    return None

def managed_folder_names(cfg=None) -> list:
    """The managed folders prep scans/organizes (every role except `strays`), in order."""
    return [folder_name(r, cfg) for r in _MANAGED_ROLES]

def missing_managed_folders(ws: str, cfg=None) -> list:
    """The managed 0-6 folders (all of FOLDER_ROLES, including `1-strays`) that are absent or not a
    directory — replaced by a file, a broken symlink, etc. — in an ACTIVATED workspace, i.e. the
    workspace root is non-conforming. Returns their names, in canonical 0-6 order.

    A non-empty result is a hard stop for every phase: the structure was almost certainly damaged
    inadvertently (a deleted folder may have taken irreplaceable media with it), so a script must
    refuse rather than silently recreate the folders and mask the loss. The caller gates this on the
    workspace being activated (the guard sentinel present) — prep's first-run init, which legitimately
    creates the 0-6, is exempt."""
    return [folder_name(r, cfg) for r in FOLDER_ROLES
            if not os.path.isdir(os.path.join(ws, folder_name(r, cfg)))]

def dedup_priority(path, cfg=None) -> int:
    """Dedup retention priority of `path` by its top folder component (lower = retained)."""
    role = folder_role(path.split('/', 1)[0], cfg)
    return FOLDER_DEDUP_PRIORITY.index(role) if role in FOLDER_DEDUP_PRIORITY else len(FOLDER_DEDUP_PRIORITY)

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

def sealed_marker_path(ws: str) -> str:
    """The terminal/seal marker a successful merge writes (prep Section 6.2 / shared 13.7).
    Its presence seals the workspace: every phase hard-stops and mutates nothing. Prep only
    READS it (the merge phase — not yet built — writes it)."""
    return os.path.join(ws, CONTROL_DIR, "photos-00-sealed.json")

def is_sealed(ws: str) -> bool:
    return os.path.exists(sealed_marker_path(ws))

def config_path(ws: str) -> str:
    # Path only; load_or_seed_config (below) seeds it on first prep run, then reads it as authoritative.
    return os.path.join(ws, CONTROL_DIR, "photos-00-config.json")

def db_path(ws: str) -> str:
    return os.path.join(ws, CONTROL_DIR, "photos-00-ingest.db")

PREP_PLAN_ARTIFACT = "photos-10-prep-plan.json"

def prep_plan_path(ws: str) -> str:
    """The prep-phase plan artifact (prep §14.2), written by `plan` and consumed by `dry-run`/`execute`
    from this canonical control-dir path — no flag tells the phase where to look. `photos-10-` precedes
    the `photos-11-handoff.json` it leads to. Re-planning backs up any prior plan via
    backup_existing_artifact (the shared `-NNN` suffix), so a superseded plan stays recoverable."""
    return os.path.join(ws, CONTROL_DIR, PREP_PLAN_ARTIFACT)

def handoff_path(ws: str) -> str:
    return os.path.join(ws, CONTROL_DIR, "photos-11-handoff.json")

def prep_log_path(ws: str) -> str:
    """End-of-prep transformation log (prep §16.1 / shared §13.3)."""
    return os.path.join(ws, CONTROL_DIR, "photos-15-prep-log.json")

def prep_db_snapshot_path(ws: str) -> str:
    """End-of-prep DB backup snapshot (shared §13.4a)."""
    return os.path.join(ws, CONTROL_DIR, "photos-15-prep-ingest.db")

def write_db_snapshot(conn, dest_path: str) -> None:
    """Capture a transactionally-consistent point-in-time image of `conn`'s database to `dest_path`
    (shared contract §13.4a): VACUUM INTO a temp name, VERIFY it, then atomic rename — so an
    interrupted capture leaves either the prior snapshot or the complete new one, never a corrupt/torn
    file. Shared by prep (photos-15-prep-ingest.db) and calibration finalize (photos-25-calibrate-ingest.db)."""
    import uuid
    tmp = os.path.join(os.path.dirname(dest_path) or ".", f".tmp-snapshot-{uuid.uuid4().hex[:8]}.db")
    try:
        if os.path.exists(tmp):
            os.remove(tmp)
        conn.execute("VACUUM INTO ?", (tmp,))
        # Verify the temp is a sound SQLite image before exposing it under the final name (§13.4a.2).
        chk = sqlite3.connect(tmp)
        try:
            if (chk.execute("PRAGMA quick_check").fetchone() or [None])[0] != "ok":
                raise RuntimeError("snapshot failed its integrity check")
        finally:
            chk.close()
        os.replace(tmp, dest_path)
    except Exception as e:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        raise RuntimeError(f"Failed to write DB backup snapshot {dest_path}: {e}")

def journal_path(ws: str, run_id: str) -> str:
    return os.path.join(ws, CONTROL_DIR, f"journal-{run_id}.json")

def sha256_file(path: str) -> str:
    """SHA-256 over a file's exact bytes — the byte-hash used to verify JSON-artifact
    dependencies (the prep handoff and the numbered calibration artifacts are re-hashed from
    their exact bytes before use, shared contract §9.1 / calibration §4)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

def sha256_text(text: str) -> str:
    """SHA-256 over a UTF-8 string — used for field-scoped config fingerprints (a SHA-256 over a
    canonical serialization of a config sub-block, shared contract §4.2)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def json_dependency(name: str, ws: str, abs_path: str) -> dict:
    """The §4 JSON-artifact dependency entry for a numbered artifact / the prep handoff: its name,
    workspace-relative path, and the SHA-256 of its exact bytes. Recorded in a downstream
    artifact's `depends_on` so the dependency can be re-read and re-hashed before use (§6)."""
    return {"dependency_type": "json_artifact", "artifact_name": name,
            "artifact_path": os.path.relpath(abs_path, ws), "sha256": sha256_file(abs_path)}

# Per-run audit keys that describe THIS run, not the organized workspace state, and so must NOT enter
# the handoff content fingerprint — they change run to run even when the result does not (§16.2):
# the top-level run_metadata/diagnostics/content_fingerprint + the execution-journal pointer, and —
# nested inside camera_groups / destination_folders — the cache-freshness counts (extracted-vs-reused
# flips on a no-op re-run) and the conflicts/duplicates (only populated on the run that quarantined).
_HANDOFF_VOLATILE_KEYS = frozenset({
    "run_metadata", "content_fingerprint", "diagnostics", "execution_journal",
    "cache_freshness", "conflicts_or_duplicates",
})

def _strip_handoff_volatile(obj):
    if isinstance(obj, dict):
        return {k: _strip_handoff_volatile(v) for k, v in obj.items() if k not in _HANDOFF_VOLATILE_KEYS}
    if isinstance(obj, list):
        return [_strip_handoff_volatile(x) for x in obj]
    return obj

def handoff_content_fingerprint(handoff: dict) -> str:
    """SHA-256 over the DETERMINISTIC content of the prep handoff (§16.2) — the file inventory, camera-
    group identity, folder mutability, and the cache/config/extractor fingerprints — with every per-run
    AUDIT field recursively removed (`run_metadata`, `diagnostics`, the execution-journal pointer, the
    `content_fingerprint` field itself, and the nested `cache_freshness` / `conflicts_or_duplicates`).
    Byte-stable for a given workspace state, so a no-op prep re-run (which only refreshes run metadata
    and freshness counts) leaves it unchanged and never restales calibration's downstream artifacts.
    The whole-file SHA-256 stays the archival-integrity hash (§13), not the staleness trigger (§4.2)."""
    return hashlib.sha256(
        json.dumps(_strip_handoff_volatile(handoff), sort_keys=True).encode("utf-8")).hexdigest()

def verify_json_dependency(dep: dict, ws: str) -> bool:
    """Re-read the named JSON dependency from disk and re-hash its exact bytes, returning True iff
    it still matches the recorded SHA-256 (§6: no mtime/size/cached shortcuts). A missing file or
    any mismatch is stale → False."""
    p = os.path.join(ws, dep.get("artifact_path", ""))
    try:
        return os.path.isfile(p) and sha256_file(p) == dep.get("sha256")
    except OSError:
        return False

def write_json_artifact(path: str, obj: dict) -> str:
    """Atomically write a numbered artifact as deterministic, pretty-printed, sorted JSON
    (temp → atomic rename). Returns its SHA-256. Artifacts must be byte-deterministic for a given
    workspace state so downstream re-hashing is stable (§4)."""
    _atomic_write_text(path, json.dumps(obj, indent=2, sort_keys=True))
    return sha256_file(path)

def backup_existing_artifact(path: str):
    """If an artifact already exists at `path`, rename it aside to the next free `<stem>-NNN<ext>`
    sibling — the shared `-{idx:03d}` no-clobber suffix (see allocate_suffix) — and return the backup
    path; if nothing is there, return None. Used before re-writing a canonical plan/decision artifact
    so the prior version is preserved rather than clobbered (shared contract §5). The rename is an
    atomic same-directory os.replace, so the prior bytes are never lost mid-swap."""
    if not os.path.lexists(path):
        return None
    d = os.path.dirname(path) or "."
    stem, ext = os.path.splitext(os.path.basename(path))
    existing = {n.lower() for n in os.listdir(d)}
    name = allocate_suffix(stem, ext.lstrip("."), existing, start_idx=1, bare_first=False)
    backup = os.path.join(d, name)
    os.replace(path, backup)
    return backup

def write_versioned_json(path: str, obj: dict):
    """Atomically write `obj` as deterministic JSON to `path`, backing up any existing artifact first
    (incremental `-NNN`). Returns (sha256, backup_path_or_None) so the caller can tell the operator
    where the plan landed and where the prior one was kept. The control dir is assumed to exist.

    A no-op guard: if the existing file is already byte-identical to what we'd write, nothing is backed
    up or rewritten (sha, None) — so an unchanged re-run (e.g. calibration regenerating identical
    decisions) never accumulates redundant backups. A plan with a fresh plan_id differs every run, so
    re-planning still always preserves the prior plan."""
    new_text = json.dumps(obj, indent=2, sort_keys=True)
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                if f.read() == new_text:
                    return sha256_file(path), None
        except OSError:
            pass
    backup = backup_existing_artifact(path)
    _atomic_write_text(path, new_text)
    return sha256_file(path), backup

def lock_path(ws: str) -> str:
    return os.path.join(ws, CONTROL_DIR, "photos-00-workspace.lock")

def ensure_control_dir(ws: str) -> str:
    d = control_dir(ws)
    os.makedirs(d, exist_ok=True)
    return d

# --- Library (merge phase) -----------------------------------------------------
# The permanent library at library_root is final and owned: it carries NONE of the workspace
# scaffolding (no 0-6 folders, no guard, no lifecycle). Its sole identity is a single dotfile
# marker in its root; its lock is another dotfile (merge spec §4/§12, shared contract §15.1/§15.2).
# These names + helpers are consumed by the merge phase (ingest/photos-3-merge, built in later
# increments); prep/calibration neither read nor write them.
LIBRARY_MARKER = ".photos-library"
LIBRARY_LOCK = ".photos-merge.lock"

def library_marker_path(library_root: str) -> str:
    return os.path.join(library_root, LIBRARY_MARKER)

def is_library(library_root: str) -> bool:
    """True iff library_root carries the .photos-library marker — the ONLY check that a directory is
    a library (merge spec §4). No structural inspection of the library beyond this marker."""
    return os.path.isfile(library_marker_path(library_root))

def write_library_marker(library_root: str) -> str:
    """Bless library_root as a library by creating the .photos-library marker. No-clobber and
    idempotent: a no-op success if the marker already exists. Written only by `merge init-library`;
    plan/dry-run/execute only ever read it. Returns the marker path."""
    p = library_marker_path(library_root)
    try:
        os.close(os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644))
    except FileExistsError:
        pass
    return p

def library_lock_path(library_root: str) -> str:
    """The library-side lock dotfile (shared contract §15.2): <library_root>/.photos-merge.lock."""
    return os.path.join(library_root, LIBRARY_LOCK)

def write_sealed_marker(ws: str, run_id: str, library_root: str) -> str:
    """Write the terminal/sealed marker photos-00-sealed.json on a fully successful merge
    (merge spec §9.4 / shared contract §13.7). Atomic (write_json_artifact); returns its SHA-256.
    Afterwards is_sealed(ws) is True and every media-mutating phase hard-stops on this workspace."""
    ensure_control_dir(ws)
    return write_json_artifact(sealed_marker_path(ws),
                               {"sealed": True, "merged_run_id": run_id, "library_root": library_root})

# Shared no-clobber suffix convention (shared contract §7.2): `<base>[.ext]` for the first free name,
# then `<base>-NNN[.ext]`, allocated against a case-insensitive occupied-name set. Prep's by-date naming
# takes the bare name first and suffixes only on a collision (`bare_first=True`, §7.2); merge renames a
# colliding incoming file (`bare_first=False` — the bare root belongs to the resident library file, so
# the incoming is ALWAYS suffixed, appended from max+1; see suffix_root/max_suffix). Single source of
# truth so the phases can never drift in how a differentiating suffix is formed.
_DEDUP_SUFFIX_RE = re.compile(r"-(\d{3,})$")

def allocate_suffix(base: str, ext: str, index: set, start_idx: int = 1, bare_first: bool = False) -> str:
    """Allocate the next free name not already in `index` (compared case-insensitively), adding the
    chosen lower-cased name to `index` so sequential allocations in the same batch never collide.

    With `bare_first` (prep's by-date naming, §7.2), the un-suffixed `<base>[.ext]` is tried first and
    used when free — a lone file gets a bare timestamp name, the `-NNN` suffix appears only on a genuine
    collision. Without it (the default; merge collision renames and prep's init-move/extension-normalize
    paths, which are only ever reached once the bare name is already taken), the bare name is skipped and
    allocation goes straight to `<base>-NNN`. `-{idx:03d}` is the shared form; `start_idx` lets merge
    begin past the highest existing suffix (append-only library) rather than gap-fill from 1."""
    if bare_first:
        bare = f"{base}.{ext}" if ext else base
        if bare.lower() not in index:
            index.add(bare.lower())
            return bare
    idx = start_idx
    while True:
        suffix = f"-{idx:03d}"
        name = f"{base}{suffix}.{ext}" if ext else f"{base}{suffix}"
        if name.lower() not in index:
            index.add(name.lower())
            return name
        idx += 1

def suffix_root(stem: str) -> str:
    """The root name of an extension-less stem: strip a trailing dedup suffix `-NNN` (3+ digits — the
    `-{idx:03d}` convention) if present, else return the stem unchanged. The 3+-digit dedup suffix is
    distinguishable from the 2-digit fields of the `%Y-%m-%d--%H-%M-%S` filename-timestamp format, so a
    bare timestamp name is never mistaken for a suffixed one."""
    return _DEDUP_SUFFIX_RE.sub("", stem)

def max_suffix(root: str, names) -> int:
    """The highest dedup index N among `names` (any iterable of basenames) of the form
    `<root>-NNN[.ext]` (case-insensitive), or 0 if only the bare `root[.ext]` / none are present.
    Merge uses max(library_dir, incoming_batch) + 1 as the next suffix for an append-only library."""
    root_l = root.lower()
    hi = 0
    for n in names:
        stem = n.rsplit(".", 1)[0] if "." in n else n
        if stem.lower() == root_l:
            continue
        m = _DEDUP_SUFFIX_RE.search(stem)
        if m and stem[:m.start()].lower() == root_l:
            hi = max(hi, int(m.group(1)))
    return hi

# Library-merge archival re-seal (merge spec §9.4 step 1 / shared contract §13.6). On a successful
# merge, the package gains merge's own artifacts; merge re-bundles by recomputing every present
# artifact's SHA-256 into its OWN photos-35-archive-manifest.json, which supersedes calibration's
# photos-25 manifest (parallel to the photos-15→25→35 log chain). It reads each artifact and never
# rewrites another phase's file (shared contract §13.0a). Consumed by ingest/photos-3-merge.
MERGE_ARCHIVE_MANIFEST = "photos-35-archive-manifest.json"
CALIBRATE_ARCHIVE_MANIFEST = "photos-25-archive-manifest.json"
_MERGE_ARCHIVE_ITEMS = [
    "photos-00-config.json", "photos-11-handoff.json",
    "photos-15-prep-log.json", "photos-15-prep-ingest.db",
    "photos-21-time-decisions.json", "photos-22-gps-decisions.json",
    "photos-23-executable-plan.json", "photos-24-execution-summary.json",
    "photos-25-complete-log.json", "photos-25-calibrate-ingest.db",
    CALIBRATE_ARCHIVE_MANIFEST,
    "photos-31-merge-summary.json", "photos-35-merge-log.json", "photos-35-merge-ingest.db",
    "photos-00-ingest.db",
]

def merge_archive_manifest_path(ws: str) -> str:
    return os.path.join(ws, CONTROL_DIR, MERGE_ARCHIVE_MANIFEST)

def reseal_archival_package(ws: str, *, workspace_name: str, plan_id: str, execution_id: str,
                            merge_run_id: str, generated_at: str) -> str:
    """Re-seal the archival package after a successful merge: recompute the SHA-256 of every package
    artifact present in the control dir (including merge's photos-31/35 artifacts and the live DB) and
    write merge's own photos-35-archive-manifest.json (supersedes calibration's photos-25 manifest,
    shared contract §13.6). Reads each artifact; never mutates another phase's file (§13.0a). Returns
    the manifest's SHA-256."""
    cd = control_dir(ws)
    contents = {}
    for name in _MERGE_ARCHIVE_ITEMS:
        ap = os.path.join(cd, name)
        if os.path.isfile(ap):
            contents[name] = {"path": os.path.relpath(ap, ws), "sha256": sha256_file(ap)}
    manifest = {
        "artifact_type": "archive_manifest",
        "artifact_name": MERGE_ARCHIVE_MANIFEST,
        "schema_version": 1,
        "workspace": workspace_name,
        "plan_id": plan_id,
        "execution_id": execution_id,
        "merge_run_id": merge_run_id,
        "supersedes": CALIBRATE_ARCHIVE_MANIFEST,
        "contents": contents,
        "run_metadata": {"generated_at": generated_at},
    }
    return write_json_artifact(merge_archive_manifest_path(ws), manifest)

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


def _check_bool(path, v):
    if not isinstance(v, bool):
        raise ValueError(f"config: {path} must be a boolean.")

def _check_string(path, v):
    if not isinstance(v, str):
        raise ValueError(f"config: {path} must be a string.")

def _check_path(path, v):
    _check_string(path, v)
    if "\x00" in v:
        raise ValueError(f"config: {path} must not contain a NUL byte.")

def _check_number(path, v, minimum=None, integer=False):
    if integer:
        if not isinstance(v, int) or isinstance(v, bool):
            raise ValueError(f"config: {path} must be an integer.")
    elif not isinstance(v, (int, float)) or isinstance(v, bool):
        raise ValueError(f"config: {path} must be a number.")
    if minimum is not None and v < minimum:
        raise ValueError(f"config: {path} must be >= {minimum}.")

def _validate_zfs(z):
    if z is None:
        return
    if not isinstance(z, dict):
        raise ValueError("config: 'zfs' must be an object.")
    for k in ("enabled", "snapshots_required"):
        if k in z:
            _check_bool(f"zfs.{k}", z[k])
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

_GPX_NUMERIC_KEYS = (
    "gpx_direct_match_max_seconds", "gpx_interpolation_max_gap_seconds",
    "gpx_interpolation_max_distance_meters", "gpx_interpolation_max_speed_kmh",
    "gpx_anchor_max_point_distance_meters", "gpx_anchor_max_segment_distance_meters",
    "gpx_anchor_offset_spread_max_seconds", "gpx_extrapolation_max_seconds",
    "photo_anchor_interpolation_max_gap_seconds", "photo_anchor_extrapolation_max_seconds",
)

def validate_config(cfg: dict):
    """Validate human-authored config before it is accepted — input a human writes is
    sanity-validated (types, ranges, paths, formats), not merely parsed as JSON. Raises
    ValueError with a clear 'config: <path> ...' message on any violation; missing keys
    default and unknown keys are ignored. The same validate-on-load discipline will extend
    to calibration decision JSON once that phase exists ([[validate-human-input]])."""
    if not isinstance(cfg, dict):
        raise ValueError("config: top level must be a JSON object.")

    _validate_zfs(cfg.get("zfs"))

    fol = cfg.get("folders")
    if fol is not None:
        if not isinstance(fol, dict):
            raise ValueError("config: folders must be an object.")
        missing = [r for r in FOLDER_ROLES if r not in fol]
        if missing:
            raise ValueError(f"config: folders is missing role(s): {', '.join(missing)}.")
        seen = {}
        for role in FOLDER_ROLES:
            name = fol[role]
            if not isinstance(name, str) or not name:
                raise ValueError(f"config: folders.{role} must be a non-empty string.")
            if "/" in name or "\x00" in name or name.startswith("."):
                raise ValueError(f"config: folders.{role} {name!r} must be a single path "
                                 f"component (no '/', no NUL, no leading '.').")
            if name in (CONTROL_DIR, QUARANTINE_DIR):
                raise ValueError(f"config: folders.{role} {name!r} collides with a control directory.")
            if name in seen:
                raise ValueError(f"config: folders.{role} and folders.{seen[name]} both name "
                                 f"{name!r} (folder names must be unique).")
            seen[name] = role

    if "filename_timestamp_format" in cfg:
        fmt = cfg["filename_timestamp_format"]
        _check_string("filename_timestamp_format", fmt)
        if not fmt:
            raise ValueError("config: filename_timestamp_format must be a non-empty strftime format.")
        try:
            out1 = datetime(2001, 2, 3, 4, 5, 6).strftime(fmt)
            out2 = datetime(2002, 3, 4, 5, 6, 7).strftime(fmt)
        except Exception as e:
            raise ValueError(f"config: filename_timestamp_format {fmt!r} is not a valid strftime format: {e}")
        if not out1:
            raise ValueError(f"config: filename_timestamp_format {fmt!r} produced an empty name.")
        if out1 == out2:
            # An unrecognized format (e.g. "%Q", a literal) does not encode the timestamp, so
            # every file would collide. strftime passes unknown directives through, so check it varies.
            raise ValueError(f"config: filename_timestamp_format {fmt!r} does not vary with the timestamp.")
        if "/" in out1 or "\x00" in out1:
            raise ValueError(f"config: filename_timestamp_format {fmt!r} produces an illegal path character.")

    if "gpx_root" in cfg:
        _check_path("gpx_root", cfg["gpx_root"])

    dds = cfg.get("destination_distribution_subfolders")
    if dds is not None:
        if not isinstance(dds, list) or not dds:
            raise ValueError("config: destination_distribution_subfolders must be a non-empty list.")
        for i, name in enumerate(dds):
            if not isinstance(name, str) or not name or "/" in name or "\x00" in name:
                raise ValueError(f"config: destination_distribution_subfolders[{i}] must be a "
                                 f"non-empty single path component.")

    mg = cfg.get("merge")
    if mg is not None:
        # Prep seeds and type-validates the library-merge block; the merge phase does the deep
        # validation (library_root is an existing directory outside the managed 0-6 tree, policy
        # enums) before it consumes them (shared contract Section 14.1 / merge spec Section 4).
        if not isinstance(mg, dict):
            raise ValueError("config: merge must be an object.")
        if "library_root" in mg:
            _check_path("merge.library_root", mg["library_root"])
        for k in ("placement_policy", "collision_policy"):
            if k in mg:
                _check_string(f"merge.{k}", mg[k])

    for k in _GPX_NUMERIC_KEYS:
        if k in cfg:
            _check_number(k, cfg[k], minimum=0)

    pol = cfg.get("camera_time_and_timezone_policy")
    if pol is not None:
        if not isinstance(pol, dict):
            raise ValueError("config: camera_time_and_timezone_policy must be an object.")
        for bk in ("enabled", "single_anchor_auto_apply", "multi_anchor_auto_apply",
                   "write_corrected_metadata_times", "write_corrected_offset_tags",
                   "write_corrected_filename_times"):
            if bk in pol:
                _check_bool(f"camera_time_and_timezone_policy.{bk}", pol[bk])
        for nk in ("phone_gpx_agreement_tolerance_seconds", "phone_gpx_conflict_threshold_seconds",
                   "dst_conflict_tolerance_seconds", "phone_gpx_max_distance_meters"):
            if nk in pol:
                _check_number(f"camera_time_and_timezone_policy.{nk}", pol[nk], minimum=0)
        if "manual_segment_template_count" in pol:
            _check_number("camera_time_and_timezone_policy.manual_segment_template_count",
                          pol["manual_segment_template_count"], minimum=0, integer=True)
        if "default_folder_timezone" in pol:
            tz = pol["default_folder_timezone"]
            _check_string("camera_time_and_timezone_policy.default_folder_timezone", tz)
            if tz:
                try:
                    from zoneinfo import ZoneInfo
                    ZoneInfo(tz)
                except Exception:
                    raise ValueError(f"config: camera_time_and_timezone_policy.default_folder_timezone "
                                     f"{tz!r} is not a valid IANA timezone.")
        dg = pol.get("device_groups")
        if dg is not None:
            if not isinstance(dg, dict):
                raise ValueError("config: camera_time_and_timezone_policy.device_groups must be an object.")
            for gk in ("phones", "fixed_clock_cameras"):
                if gk in dg:
                    lst = dg[gk]
                    if not isinstance(lst, list) or not all(isinstance(x, str) for x in lst):
                        raise ValueError(f"config: camera_time_and_timezone_policy.device_groups.{gk} "
                                         f"must be a list of strings.")


# Policy values the merge phase currently supports (merge spec §4 / stage-2 decision: v1 is
# identity placement + incoming-suffix collision only; any other value is a hard blocker).
_MERGE_PLACEMENT_POLICIES = {"preserve_destination_structure"}
_MERGE_COLLISION_POLICIES = {"suffix_incoming"}

def validate_merge_config(cfg: dict, ws: str):
    """Deep-validate the library-merge config before the merge phase consumes it (merge spec §4;
    shared contract §14.1). Prep only type-validates merge (validate_config); merge calls THIS, which
    additionally requires `library_root` to be a non-empty, existing directory resolving OUTSIDE the
    workspace and its managed 0-6 tree, and the policy values to be supported enums. Raises ValueError
    located to the offending field. Library *identity* (the .photos-library marker) is a separate
    preflight check (is_library), not a config concern."""
    mg = cfg.get("merge")
    if not isinstance(mg, dict):
        raise ValueError("config: merge must be an object.")
    lib = mg.get("library_root")
    if not isinstance(lib, str) or not lib:
        raise ValueError("config: merge.library_root must be a non-empty path to the permanent library.")
    if "\x00" in lib:
        raise ValueError("config: merge.library_root must not contain a NUL byte.")
    lib_real = os.path.realpath(os.path.abspath(lib))
    if not os.path.isdir(lib_real):
        raise ValueError(f"config: merge.library_root {lib!r} is not an existing directory.")
    ws_real = os.path.realpath(os.path.abspath(ws))
    if lib_real == ws_real or lib_real.startswith(ws_real + os.sep):
        raise ValueError(f"config: merge.library_root {lib!r} must resolve outside the workspace "
                         f"(it must not be the workspace or any path inside it).")
    pp = mg.get("placement_policy", "preserve_destination_structure")
    if pp not in _MERGE_PLACEMENT_POLICIES:
        raise ValueError(f"config: merge.placement_policy {pp!r} is not supported "
                         f"(allowed: {', '.join(sorted(_MERGE_PLACEMENT_POLICIES))}).")
    cp = mg.get("collision_policy", "suffix_incoming")
    if cp not in _MERGE_COLLISION_POLICIES:
        raise ValueError(f"config: merge.collision_policy {cp!r} is not supported "
                         f"(allowed: {', '.join(sorted(_MERGE_COLLISION_POLICIES))}).")


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

def take_zfs_snapshot(ws: str, snapshot_id: str, label: str, *, target_path=None,
                      dataset_key: str = "workspace"):
    """Take an optional pre-mutation ZFS snapshot — shared by prep (§14.3, workspace), calibration
    execute (§29 step 6, workspace), and merge execute (merge spec §10.3 step 3, the LIBRARY volume).
    `label` is the phase ("prep" / "calibrate" / "merge") so the phases' snapshots never resolve to the
    same name even on a shared dataset: `<dataset>@<zfs.snapshot_prefix><label>-<snapshot_id>`.

    By default the snapshot targets the workspace dataset (auto-detected from `ws` or pinned via
    `zfs.datasets.workspace`). Merge passes `target_path=library_root, dataset_key="library"` so the
    dataset is detected from the library path (or pinned via `zfs.datasets.library`) — its placements
    land there, not in the workspace tree.

    Returns None when ZFS is disabled; otherwise a record
    `{required, snapshot_name (None if no dataset was found), command, exit_code, stdout, stderr, ok}`.
    It NEVER raises — the caller records the result in its own journal/summary and, if `required` and
    not `ok`, aborts before mutating (keeping the audit record + abort decision in the phase)."""
    import subprocess
    zfs = CONFIG.get("zfs") or {}
    if not zfs.get("enabled", False):
        return None
    required = bool(zfs.get("snapshots_required", False))
    detect_path = target_path or ws
    ds_cfg = (zfs.get("datasets") or {}).get(dataset_key, "auto")
    dataset = detect_zfs_dataset(detect_path) if ds_cfg == "auto" else ds_cfg
    if not dataset:
        return {"required": required, "snapshot_name": None, "command": None, "exit_code": None,
                "stdout": "", "stderr": f"ZFS enabled but no dataset found for {detect_path}", "ok": False}
    snap = f"{dataset}@{zfs.get('snapshot_prefix', '')}{label}-{snapshot_id}"
    cmd = ["zfs", "snapshot", snap]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return {"required": required, "snapshot_name": snap, "command": " ".join(cmd),
                "exit_code": res.returncode, "stdout": res.stdout, "stderr": res.stderr,
                "ok": res.returncode == 0}
    except Exception as e:
        return {"required": required, "snapshot_name": snap, "command": " ".join(cmd),
                "exit_code": getattr(e, "returncode", -1), "stdout": getattr(e, "stdout", "") or "",
                "stderr": getattr(e, "stderr", "") or str(e), "ok": False}

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
import select
import subprocess
import threading
import atexit
from typing import Dict, List, Any, Optional


_MAGICK_COMMAND = None
def get_magick_command() -> list:
    """Return ['magick'] if ImageMagick v7's `magick` (which supports the persistent `-script -` mode)
    is available (cached), else []. The legacy v6 `identify` has no script mode, so a magick-less
    system falls back to per-file `identify` in fingerprint_image."""
    global _MAGICK_COMMAND
    if _MAGICK_COMMAND is None:
        _MAGICK_COMMAND = ["magick"] if shutil.which("magick") else []
    return _MAGICK_COMMAND


class ProcessCrashedError(Exception):
    pass


class PersistentMagickWorker:
    """A persistent `magick -script -` process — the ImageMagick analog of exiftool's `-stay_open` —
    reused across files for the content signature instead of spawning `identify` once per file
    (§17.5). One worker per scanning thread (thread-local); restarted on crash; closed at exit. The
    `magick -script` signature is byte-identical to `identify -format %#` (verified)."""
    _instances = []
    _lock = threading.Lock()

    def __init__(self):
        self.closed = False
        self._start()
        with PersistentMagickWorker._lock:
            PersistentMagickWorker._instances.append(self)

    def _start(self):
        self.process = subprocess.Popen(
            get_magick_command() + ["-limit", "thread", "1", "-script", "-"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, bufsize=1)

    def restart(self):
        self.close(remove=False)
        self._start()
        self.closed = False

    def signature(self, filepath: str):
        """The decoded-content signature (`%#`) of `filepath` over sRGB/8-bit-normalized pixels.
        Returns the hex string, or None on empty output. Raises ProcessCrashedError if the worker
        process dies (e.g. on an unreadable image — `magick -script` aborts) so the caller can
        restart + retry."""
        if self.closed:
            raise ProcessCrashedError("Magick worker closed")
        esc = str(filepath).replace("\\", "\\\\").replace('"', '\\"')
        cmd = (f'-read "{esc}" -colorspace sRGB -depth 8 -print "%#\\n" '
               f'-delete 0--1 -print "{{ready}}\\n"\n')
        try:
            self.process.stdin.write(cmd)
            self.process.stdin.flush()
        except OSError as e:
            raise ProcessCrashedError(f"Failed to write to magick: {e}")
        out = []
        for _ in range(64):          # a real reply is 1-2 lines then {ready}; cap to never hang on a broken process
            try:
                line = self.process.stdout.readline()
            except OSError as e:
                raise ProcessCrashedError(f"Failed to read from magick: {e}")
            if not line:
                raise ProcessCrashedError("Unexpected EOF from magick process.")
            if line.strip() == "{ready}":
                return out[0] if out else None
            if line.strip():
                out.append(line.strip())
        raise ProcessCrashedError("magick produced no {ready} sentinel")

    def close(self, remove=True):
        if not self.closed:
            try:
                self.process.stdin.close()
            except Exception:
                pass
            try:
                self.process.wait(timeout=2)
            except Exception:
                self.process.kill()
            self.closed = True
        if remove:
            with PersistentMagickWorker._lock:
                if self in PersistentMagickWorker._instances:
                    PersistentMagickWorker._instances.remove(self)

    @classmethod
    def cleanup_all(cls):
        with cls._lock:
            instances = list(cls._instances)
        for w in instances:
            w.close()


_magick_tls = threading.local()

def _thread_magick_worker():
    """The calling thread's persistent magick worker, created lazily and reused across files."""
    w = getattr(_magick_tls, "worker", None)
    if w is None or w.closed:
        w = PersistentMagickWorker()
        _magick_tls.worker = w
    return w

atexit.register(PersistentMagickWorker.cleanup_all)


class ContentHasher:
    """Content fingerprints — the cross-phase identity spine, shared by prep and calibration.

    `fingerprint_image` is an EXIF-invariant pixel-content hash via ImageMagick's signature
    (`identify %#`): it survives the EXIF writes calibration later makes, so calibration recomputes
    it after each metadata write to confirm only metadata (not decoded content) changed."""

    @staticmethod
    def fingerprint_image(filepath: str) -> Dict[str, Any]:
        """EXIF-invariant pixel-content hash via ImageMagick's signature (`identify %#`).

        Used for both `image` and `raw`: it hashes normalized pixels, so it survives the EXIF writes
        calibration later makes (the content hash is the cross-phase identity spine). The result is
        bound to the ImageMagick version so a magick upgrade restales the cache rather than silently
        mixing signatures.
        """
        engine_version = get_imagemagick_version()
        if get_magick_command():
            # Persistent `magick -script -` worker, one per thread, reused across files (§17.5) —
            # restarted on crash (an unreadable image aborts the script process).
            last_error = "ImageMagick failed"
            for _attempt in range(2):
                worker = _thread_magick_worker()
                try:
                    sig = worker.signature(filepath)
                    if sig:
                        return {"status": "valid", "strategy": "image-content-hash-v1",
                                "value": sig, "engine_version": engine_version}
                    last_error = "ImageMagick produced no signature"
                    worker.restart()
                except ProcessCrashedError as e:
                    last_error = str(e)
                    try:
                        worker.restart()
                    except Exception:
                        _magick_tls.worker = None      # drop the dead worker; a fresh one next attempt
            return {"status": "failed", "strategy": "image-content-hash-v1", "value": None,
                    "error": last_error, "engine_version": engine_version}

        # Fallback: legacy per-file `identify` (no `magick` script mode on this system).
        identify_cmd = get_identify_command()
        if not identify_cmd:
            return {"status": "failed", "strategy": "image-content-hash-v1", "value": None,
                    "error": "ImageMagick not found", "engine_version": engine_version}
        cmd = identify_cmd + ["-format", "%#", "-colorspace", "sRGB", "-depth", "8", filepath]
        last_error = "ImageMagick failed"
        for _attempt in range(2):
            try:
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
                stdout_data = ""
                while True:
                    reads, _, _ = select.select([proc.stdout], [], [], 10.0)
                    if not reads:
                        proc.kill()
                        raise subprocess.TimeoutExpired(cmd, 10.0)
                    chunk = proc.stdout.read(1024)
                    if not chunk:
                        break
                    stdout_data += chunk
                proc.wait()
                if proc.returncode == 0 and stdout_data.strip():
                    return {"status": "valid", "strategy": "image-content-hash-v1",
                            "value": stdout_data.strip(), "engine_version": engine_version}
                last_error = f"ImageMagick exited {proc.returncode}"
            except subprocess.TimeoutExpired:
                last_error = "ImageMagick timed out"
            except Exception as e:
                last_error = str(e)
        return {"status": "failed", "strategy": "image-content-hash-v1", "value": None,
                "error": last_error, "engine_version": engine_version}

    @staticmethod
    def fingerprint_video(filepath: str) -> Dict[str, Any]:
        cmd = ["ffmpeg", "-i", filepath, "-c", "copy", "-f", "md5", "-"]
        last_error = None
        for attempt in range(2):                       # safe restart on a transient ffmpeg failure
            try:
                res = subprocess.run(cmd, capture_output=True, text=True, check=True)
                for line in res.stdout.splitlines():
                    if line.startswith("MD5="):
                        return {"status": "valid", "strategy": "video-md5-v1", "value": line.split("=")[1].strip()}
                last_error = "No MD5 output"
            except subprocess.CalledProcessError as e:
                last_error = str(e)
                if attempt == 1:
                    print(f"Warning: ffmpeg failed on {filepath}: {e.stderr}")
        return {"status": "failed", "strategy": "video-md5-v1", "value": None, "error": last_error}


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
    # Metadata is read by the persistent-worker pool (PersistentExifToolWorker.read_metadata
    # via ExifToolWorkerPool, used by read_metadata_concurrently below). An earlier one-shot
    # MetadataReader.read_metadata predated the concurrent pool and had no remaining caller;
    # it was removed. _parse_exiftool_item (shared with the live worker) stays.
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
                try:
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
                except KeyboardInterrupt:
                    # Ctrl-C: cancel pending extractions instead of letting the `with` exit drain
                    # them. The ExifToolWorkerPool's __exit__ then closes/kills the worker processes.
                    executor.shutdown(wait=False, cancel_futures=True)
                    raise

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
        print(f"  End-of-prep audit record          : prep-log {pc.get('prep_log_written', False)}, "
              f"DB snapshot {pc.get('prep_db_snapshot_written', False)}", file=out)
        print(f"  Quarantine footprint              : {qf.get('total_files', 0)} files, "
              f"{qf.get('total_bytes', 0)} bytes across {qf.get('plan_id_dirs', 0)} plan(s) "
              f"(never auto-deleted)", file=out)
        print("========================", file=out)


# ============================================================================
# Shared workspace infrastructure (extracted from photos-1-prep so calibration
# can import it too). The DB and lock are phase-neutral: prep and calibration
# share one photos-00-ingest.db and one whole-run lock (shared contract §2/§13.4).
# ============================================================================

# SQLite cache schema version and content-hash scheme version, recorded in the cache `meta`
# table, the journal, and the handoff depends_on so a stale/foreign cache or journal is
# detectable downstream (prep Section 5). The per-hash engine binding (e.g. ImageMagick
# version) is carried separately in each content hash's engine_version.
CACHE_SCHEMA_VERSION = 1
FINGERPRINT_ALGORITHM_VERSION = "1"

# --- Atomic no-clobber move (prep Section 4 / 14.3.4) -------------------------
# No-clobber is enforced at plan time (the clobber simulation) AND here at execution
# time, atomically, so a destination that appears between validation and the move (or a
# clobber planning somehow missed) can never overwrite an irreplaceable original.
_RENAMEAT2 = None            # cached libc.renameat2, or False if unavailable
_AT_FDCWD = -100
_RENAME_NOREPLACE = 1

def _get_renameat2():
    global _RENAMEAT2
    if _RENAMEAT2 is None:
        try:
            libc = ctypes.CDLL(None, use_errno=True)
            fn = libc.renameat2
            fn.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
            fn.restype = ctypes.c_int
            _RENAMEAT2 = fn
        except (OSError, AttributeError):
            _RENAMEAT2 = False
    return _RENAMEAT2

def _move_link_unlink(src: str, dest: str):
    """Portable same-filesystem no-clobber move: hardlink (fails if dest exists, never
    overwrites) then unlink the source. Fallback when renameat2 is unavailable."""
    os.link(src, dest)   # raises FileExistsError if dest exists; OSError(EXDEV) across filesystems
    os.unlink(src)

def _rename_no_clobber_same_fs(src: str, dest: str):
    """Atomic SAME-filesystem no-clobber rename: renameat2(RENAME_NOREPLACE) as a single race-free
    syscall, else a portable hardlink+unlink. Raises FileExistsError if dest exists and OSError(EXDEV)
    if src and dest are on different filesystems — the caller (_move_no_clobber) handles EXDEV. There
    is deliberately NO cross-fs fallback here, so the cross-fs path can reuse it without recursing."""
    fn = _get_renameat2()
    if fn:
        res = fn(_AT_FDCWD, os.fsencode(src), _AT_FDCWD, os.fsencode(dest), _RENAME_NOREPLACE)
        if res == 0:
            return
        eno = ctypes.get_errno()
        if eno == errno.EEXIST:
            raise FileExistsError(f"Destination exists: {dest}")
        if eno not in (errno.ENOSYS, errno.EINVAL, errno.ENOTSUP):
            raise OSError(eno, os.strerror(eno), dest)   # EXDEV lands here for the caller to handle
        # renameat2 not supported on this kernel/fs — fall through to the hardlink fallback.
    _move_link_unlink(src, dest)                         # raises FileExistsError / OSError(EXDEV)

def _move_cross_fs_no_clobber(src: str, dest: str, verify=None):
    """Cross-filesystem no-clobber move (shared contract §15.3) — the fallback when a plain move
    cannot cross filesystems (EXDEV). Copy src to a temporary name on the DESTINATION filesystem,
    verify it, fsync it, atomically rename it into the final target (failing if the target exists —
    no clobber), then remove the source LAST. A crash leaves the source intact (plus at most a
    discardable temp), never a half-copied file under the final name and never an overwrite.

    `verify(src, tmp)` runs before the copy is exposed under the final name and must raise to abort;
    it defaults to a byte-size equality check. (The merge phase, §11, can pass a fingerprint check.)"""
    dest_dir = os.path.dirname(dest) or "."
    fd, tmp = tempfile.mkstemp(dir=dest_dir, prefix=".tmp-xdev-", suffix=".part")
    os.close(fd)
    try:
        shutil.copyfile(src, tmp)                       # contents
        try:
            shutil.copystat(src, tmp)                   # best-effort mtime/mode
        except OSError:
            pass
        if verify is not None:
            verify(src, tmp)
        elif os.path.getsize(tmp) != os.path.getsize(src):
            raise OSError(errno.EIO, "cross-filesystem copy size mismatch", src)
        dfd = os.open(tmp, os.O_RDONLY)                 # durable before we expose it under the final name
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
        _rename_no_clobber_same_fs(tmp, dest)           # tmp & dest share dest's fs -> no recursion
        tmp = None                                      # consumed by the rename
    finally:
        if tmp is not None and os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
    os.unlink(src)                                      # remove the source LAST (crash-safe)

def _move_no_clobber(src: str, dest: str, verify=None):
    """Move src -> dest, failing (FileExistsError) instead of overwriting an existing destination.
    Primary path is an atomic same-filesystem MOVE (_rename_no_clobber_same_fs). Only when that move
    cannot cross filesystems (EXDEV) does it fall back to the cross-fs copy-then-remove workaround
    (§15.3) — a same-fs move never touches the fallback.

    `verify(src, tmp)` applies only to the cross-fs fallback (a same-fs rename is lossless, so there is
    nothing to verify); it runs against the temp copy before it is exposed under the final name and must
    raise to abort. The merge phase (§11) passes a content-fingerprint check to catch a torn copy."""
    try:
        _rename_no_clobber_same_fs(src, dest)
    except OSError as e:
        if e.errno == errno.EXDEV:                      # crossing filesystems — use the workaround
            _move_cross_fs_no_clobber(src, dest, verify=verify)
        else:
            raise                                       # incl. FileExistsError (EEXIST): no-clobber

class WorkspaceCache:
    """
    SQLite accelerator cache for inventory, metadata, and hashes.
    """
    def __init__(self, workspace_root: str, db_name: str = None, in_memory: bool = False, read_only: bool = False):
        from photos_utils import db_path as _db_path
        self.in_memory = in_memory
        self.read_only = read_only
        self.db_path = os.path.join(workspace_root, db_name) if db_name else _db_path(workspace_root)

        if in_memory:
            self.conn = sqlite3.connect(":memory:", check_same_thread=False)
            self._init_db()
        else:
            if read_only:
                if not os.path.exists(self.db_path):
                    # Connect to in-memory as a dummy fallback if it doesn't exist to prevent creating a file
                    self.conn = sqlite3.connect(":memory:", check_same_thread=False)
                    self._init_db()
                else:
                    self.conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True, check_same_thread=False)
            else:
                from photos_utils import ensure_control_dir
                ensure_control_dir(workspace_root)
                self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
                self._init_db()

        self.conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._batch_depth = 0  # >0 while inside transaction(): defer commits to one batch

    def _init_db(self):
        with self.conn:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS file_cache (
                    relative_path TEXT PRIMARY KEY,
                    absolute_path TEXT,
                    size INTEGER,
                    mtime_ns INTEGER,
                    inode INTEGER,
                    media_class TEXT,
                    hash TEXT,
                    content_hash TEXT,
                    last_seen_ns INTEGER
                )
            """)
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_hash ON file_cache(hash)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_content_hash ON file_cache(content_hash)")

            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS metadata_cache (
                    relative_path TEXT PRIMARY KEY,
                    size INTEGER,
                    mtime_ns INTEGER,
                    content_hash TEXT,
                    extractor TEXT,
                    extractor_version TEXT,
                    field_set_version INTEGER,
                    extraction_options_fingerprint TEXT,
                    metadata_schema_version INTEGER,
                    camera_group_key_version INTEGER,
                    camera_group_key TEXT,
                    has_native_gps INTEGER,
                    has_timestamp INTEGER,
                    parsed_json TEXT,
                    raw_payload TEXT,
                    extraction_status TEXT,
                    extraction_error TEXT,
                    FOREIGN KEY(relative_path) REFERENCES file_cache(relative_path) ON DELETE CASCADE
                )
            """)

            # Perform idempotent migration for existing databases missing phase 8C columns
            cur = self.conn.cursor()
            cur.execute("PRAGMA table_info(metadata_cache)")
            columns = {row[1] for row in cur.fetchall()}

            missing_columns = []
            if "metadata_schema_version" not in columns:
                missing_columns.append("metadata_schema_version INTEGER")
            if "camera_group_key_version" not in columns:
                missing_columns.append("camera_group_key_version INTEGER")
            if "extraction_status" not in columns:
                missing_columns.append("extraction_status TEXT")
            if "extraction_error" not in columns:
                missing_columns.append("extraction_error TEXT")

            for col in missing_columns:
                self.conn.execute(f"ALTER TABLE metadata_cache ADD COLUMN {col}")

            # Cache identity/version row (prep Section 5). Seeded once and kept, so an older
            # DB retains its recorded version and a future schema bump becomes detectable.
            self.conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
            self.conn.execute("INSERT OR IGNORE INTO meta (key, value) VALUES (?, ?)",
                              ("cache_schema_version", str(CACHE_SCHEMA_VERSION)))
            self.conn.execute("INSERT OR IGNORE INTO meta (key, value) VALUES (?, ?)",
                              ("fingerprint_algorithm_version", FINGERPRINT_ALGORITHM_VERSION))

            # Library-file fingerprint cache (merge spec §7 / shared contract §13.4). The permanent
            # library has no database of its own; when merge fingerprints a resident library file to
            # resolve a collision, it caches the result HERE in the workspace DB, keyed by absolute
            # library path + size + mtime_ns, so the same unchanged library file is fingerprinted at
            # most once per run and across re-runs. Consumed by the merge phase only.
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS library_fingerprint_cache (
                    library_path TEXT PRIMARY KEY,
                    size INTEGER,
                    mtime_ns INTEGER,
                    fingerprint_value TEXT,
                    fingerprint_strategy TEXT,
                    engine_version TEXT
                )
            """)

    def get_meta(self, key: str) -> Optional[str]:
        with self._lock:
            cur = self.conn.cursor()
            cur.execute("SELECT value FROM meta WHERE key = ?", (key,))
            row = cur.fetchone()
            return row[0] if row else None

    def get_all_files(self) -> Dict[str, dict]:
        with self._lock:
            cur = self.conn.cursor()
            cur.execute("SELECT * FROM file_cache")
            return {row['relative_path']: dict(row) for row in cur.fetchall()}

    def get_all_metadata(self) -> Dict[str, dict]:
        with self._lock:
            cur = self.conn.cursor()
            cur.execute("SELECT * FROM metadata_cache")
            return {row['relative_path']: dict(row) for row in cur.fetchall()}

    def begin_batch(self):
        """Defer per-op commits; effects then commit once via commit_batch (§14.3.7)."""
        self._batch_depth += 1

    def commit_batch(self):
        if self._batch_depth > 0:
            self._batch_depth -= 1
        if self._batch_depth == 0:
            with self._lock:
                self.conn.commit()

    def rollback_batch(self):
        if self._batch_depth > 0:
            self._batch_depth -= 1
        if self._batch_depth == 0:
            with self._lock:
                self.conn.rollback()

    @contextlib.contextmanager
    def transaction(self):
        """Batch post-verification cache effects into one transaction (prep Section 14.3.7).
        While active, the write methods skip their per-op commit; this commits once on a clean
        exit and rolls back on exception. Reference-counted, so nesting is safe."""
        self.begin_batch()
        try:
            yield
        except BaseException:
            self.rollback_batch()
            raise
        else:
            self.commit_batch()

    @contextlib.contextmanager
    def _write_ctx(self):
        """Per-op commit by default; inside transaction() defer to the batch's single commit."""
        if self._batch_depth > 0:
            with self._lock:
                yield
        else:
            with self._lock, self.conn:
                yield

    def remove_file(self, relative_path: str):
        with self._write_ctx():
            self.conn.execute("DELETE FROM file_cache WHERE relative_path = ?", (relative_path,))
            self.conn.execute("DELETE FROM metadata_cache WHERE relative_path = ?", (relative_path,))

    def rename_file(self, old_rel_path: str, new_rel_path: str, new_abs_path: str):
        # Retained for executor rename support and shared index tests
        with self._write_ctx():
            self.conn.execute("UPDATE file_cache SET relative_path = ?, absolute_path = ? WHERE relative_path = ?", (new_rel_path, new_abs_path, old_rel_path))
            self.conn.execute("UPDATE metadata_cache SET relative_path = ? WHERE relative_path = ?", (new_rel_path, old_rel_path))

    def upsert_file(self, data: Dict[str, Any]):
        with self._write_ctx():
            self.conn.execute("""
                INSERT INTO file_cache (
                    relative_path, absolute_path, size, mtime_ns, inode, media_class,
                    hash, content_hash, last_seen_ns
                ) VALUES (
                    :relative_path, :absolute_path, :size, :mtime_ns, :inode, :media_class,
                    :hash, :content_hash, :last_seen_ns
                )
                ON CONFLICT(relative_path) DO UPDATE SET
                    absolute_path = excluded.absolute_path,
                    size = excluded.size,
                    mtime_ns = excluded.mtime_ns,
                    inode = excluded.inode,
                    media_class = excluded.media_class,
                    hash = excluded.hash,
                    content_hash = excluded.content_hash,
                    last_seen_ns = excluded.last_seen_ns
            """, data)

            # Conditionally upsert metadata if metadata keys are provided
            if 'metadata' in data and data['metadata']:
                md = data['metadata']
                md_row = {
                    "relative_path": data["relative_path"],
                    "size": data["size"],
                    "mtime_ns": data["mtime_ns"],
                    "content_hash": data.get("content_hash"),
                    "extractor": md.get("extractor", "exiftool"),
                    "extractor_version": md.get("extractor_version", "unknown"),
                    "field_set_version": md.get("field_set_version", 1),
                    "extraction_options_fingerprint": md.get("extraction_options_fingerprint", "unknown"),
                    "metadata_schema_version": md.get("metadata_schema_version", 1),
                    "camera_group_key_version": md.get("camera_group_key_version", 1),
                    "camera_group_key": md.get("camera_group_key", "unknown"),
                    "has_native_gps": 1 if md.get("has_native_gps") else 0,
                    "has_timestamp": 1 if md.get("has_timestamp") else 0,
                    "parsed_json": md.get("parsed_json", "{}"),
                    "raw_payload": md.get("raw_payload", "{}"),
                    "extraction_status": md.get("extraction_status", "extracted_ok"),
                    "extraction_error": md.get("extraction_error", None)
                }
                self.conn.execute("""
                    INSERT INTO metadata_cache (
                        relative_path, size, mtime_ns, content_hash, extractor,
                        extractor_version, field_set_version, extraction_options_fingerprint,
                        metadata_schema_version, camera_group_key_version,
                        camera_group_key, has_native_gps, has_timestamp, parsed_json, raw_payload,
                        extraction_status, extraction_error
                    ) VALUES (
                        :relative_path, :size, :mtime_ns, :content_hash, :extractor,
                        :extractor_version, :field_set_version, :extraction_options_fingerprint,
                        :metadata_schema_version, :camera_group_key_version,
                        :camera_group_key, :has_native_gps, :has_timestamp, :parsed_json, :raw_payload,
                        :extraction_status, :extraction_error
                    )
                    ON CONFLICT(relative_path) DO UPDATE SET
                        size = excluded.size,
                        mtime_ns = excluded.mtime_ns,
                        content_hash = excluded.content_hash,
                        extractor = excluded.extractor,
                        extractor_version = excluded.extractor_version,
                        field_set_version = excluded.field_set_version,
                        extraction_options_fingerprint = excluded.extraction_options_fingerprint,
                        metadata_schema_version = excluded.metadata_schema_version,
                        camera_group_key_version = excluded.camera_group_key_version,
                        camera_group_key = excluded.camera_group_key,
                        has_native_gps = excluded.has_native_gps,
                        has_timestamp = excluded.has_timestamp,
                        parsed_json = excluded.parsed_json,
                        raw_payload = excluded.raw_payload,
                        extraction_status = excluded.extraction_status,
                        extraction_error = excluded.extraction_error
                """, md_row)

    def cache_library_fingerprint(self, library_path: str, size: int, mtime_ns: int, fp: Dict[str, Any]):
        """Cache a resident library file's content fingerprint (merge spec §7 / shared contract §13.4),
        keyed by absolute library path + size + mtime_ns. `fp` is a ContentHasher fingerprint dict
        (value / strategy / engine_version). Re-keying on (path,size,mtime_ns) means a changed library
        file naturally misses and is re-fingerprinted."""
        with self._write_ctx():
            self.conn.execute("""
                INSERT INTO library_fingerprint_cache
                    (library_path, size, mtime_ns, fingerprint_value, fingerprint_strategy, engine_version)
                VALUES (:library_path, :size, :mtime_ns, :value, :strategy, :engine_version)
                ON CONFLICT(library_path) DO UPDATE SET
                    size = excluded.size,
                    mtime_ns = excluded.mtime_ns,
                    fingerprint_value = excluded.fingerprint_value,
                    fingerprint_strategy = excluded.fingerprint_strategy,
                    engine_version = excluded.engine_version
            """, {"library_path": library_path, "size": size, "mtime_ns": mtime_ns,
                  "value": fp.get("value"), "strategy": fp.get("strategy"),
                  "engine_version": fp.get("engine_version")})

    def get_cached_library_fingerprint(self, library_path: str, size: int, mtime_ns: int):
        """Return the cached fingerprint dict for a library file iff the cached size + mtime_ns still
        match the current ones (else None — the file changed, so re-fingerprint). Shape mirrors a
        ContentHasher result: {status: 'valid', value, strategy, engine_version}."""
        with self._lock:
            cur = self.conn.cursor()
            cur.execute("SELECT size, mtime_ns, fingerprint_value, fingerprint_strategy, engine_version "
                        "FROM library_fingerprint_cache WHERE library_path = ?", (library_path,))
            row = cur.fetchone()
        if row is None or row["size"] != size or row["mtime_ns"] != mtime_ns:
            return None
        return {"status": "valid", "value": row["fingerprint_value"],
                "strategy": row["fingerprint_strategy"], "engine_version": row["engine_version"]}

    def close(self):
        self.conn.close()


class _FlockLock:
    """Non-blocking exclusive flock keyed to an explicit lock-file path, recording this run's owner
    identity {pid, started_at, host}. Opened O_RDWR|O_CREAT (no truncate) so a *failed* acquire never
    clobbers the current holder's identity; only a successful acquire rewrites it. fcntl.flock is
    auto-released by the kernel if this process dies, so a crash never wedges the lock and no stale-lock
    takeover code is needed. Base of both WorkspaceLock and the library-side LibraryLock."""
    def __init__(self, lock_file_path: str):
        self.lock_path = lock_file_path
        self._lock_fd = None
        self.owner = None  # on a failed acquire, the identity of the current holder (if readable)

    def acquire(self) -> bool:
        try:
            fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o644)
            self._lock_fd = os.fdopen(fd, 'r+')
        except OSError:
            self._lock_fd = None
            return False
        try:
            fcntl.flock(self._lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (IOError, OSError):
            self.owner = self.read_owner()  # who holds it, for the caller's message
            self._lock_fd.close()
            self._lock_fd = None
            return False
        identity = {
            "pid": os.getpid(),
            "started_at": datetime.now(timezone.utc).isoformat(),
            "host": socket.gethostname(),
        }
        self._lock_fd.seek(0)
        self._lock_fd.truncate(0)
        self._lock_fd.write(json.dumps(identity))
        self._lock_fd.flush()
        return True

    def read_owner(self):
        """Best-effort read of the lock file's recorded owner identity (or None)."""
        try:
            with open(self.lock_path, 'r') as f:
                return json.loads(f.read() or "null")
        except Exception:
            return None

    def release(self):
        """Releases the lock. Does NOT delete the file to avoid inode race conditions."""
        if self._lock_fd:
            fcntl.flock(self._lock_fd.fileno(), fcntl.LOCK_UN)
            self._lock_fd.close()
            self._lock_fd = None


class LibraryLock(_FlockLock):
    """The library-side lock (shared contract §15.2 / merge spec §12), keyed to library_root as a
    `.photos-merge.lock` dotfile in the library root. Serializes merge runs writing the SAME library
    even when they originate from different workspaces (each with its own WorkspaceLock). Same
    fail-fast, stale-detectable discipline. The library_root must already exist and be a library (the
    marker/identity check precedes lock acquisition), so the lock file is never dropped into a
    non-library directory. Consumed by the merge phase."""
    def __init__(self, library_root: str):
        super().__init__(library_lock_path(library_root))


class WorkspaceLock(_FlockLock):
    """The whole-run workspace lock (shared contract §2), keyed to the control dir's
    photos-00-workspace.lock. Inherits the non-blocking flock + owner-identity discipline from
    _FlockLock; only the keyed path (and ensuring the control dir exists) differs."""
    def __init__(self, workspace_root: str):
        from photos_utils import lock_path, ensure_control_dir
        ensure_control_dir(workspace_root)
        super().__init__(lock_path(workspace_root))
