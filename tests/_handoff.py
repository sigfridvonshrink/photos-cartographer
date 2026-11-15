"""Test helper: hand-built handoff records made to match the files on disk, as prep's would.

Geotag stops on a by-dest photo whose record no longer holds — gone, or differing in size or modification time from
the handoff (RUL-geotag_plans_on_current_record) — so a fixture that writes a handoff by hand
records what its files really are."""
import os


def match_disk(ws, files):
    """Set each record's `size` and `mtime_ns` to those of its file in `ws`, where the file exists; return `files`."""
    for rec in files:
        p = os.path.join(str(ws), rec.get("relative_path") or "")
        if os.path.isfile(p):
            st = os.stat(p)
            rec["size"], rec["mtime_ns"] = st.st_size, st.st_mtime_ns
    return files


def vouched(ws, handoff):
    """`handoff` with `depends_on.prep_log` recording the SHA-256 of prep's log in `ws` — an empty log written when
    there is none — as prep's execution records it (BLD-prep_log_vouched): geotag plans only on the log the handoff
    vouches for (RUL-geotag_plans_on_vouched_log). The pointer lies outside the handoff's content fingerprint, so
    vouching makes nothing stale. Returns `handoff`."""
    import json
    import photos_utils
    log = os.path.join(str(ws), ".photos-ingest", "photos-15-prep-log.json")
    if not os.path.exists(log):
        with open(log, "w") as f:
            json.dump({"photos": {}}, f)
    handoff.setdefault("depends_on", {})["prep_log"] = {"sha256": photos_utils.sha256_file(log)}
    return handoff


def vouch_prep_log(ws):
    """Vouch, in the handoff on disk in `ws`, for prep's log as it now is (`vouched`)."""
    import json
    p = os.path.join(str(ws), ".photos-ingest", "photos-11-handoff.json")
    with open(p) as f:
        ho = json.load(f)
    with open(p, "w") as f:
        json.dump(vouched(ws, ho), f)
