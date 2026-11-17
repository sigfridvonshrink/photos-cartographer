"""Test helper: hand-built handoff records made to match the files on disk, as prep's would.

Geotag stops on a by-dest photo whose record no longer holds — gone, or differing in size or modification time from
the handoff (RUL-geotag_plans_on_current_record) — so a fixture that writes a handoff by hand
records what its files really are."""
import os


def match_disk(ws, files):
    """Set each record's `size` and `mtime_ns` to those of its file in `ws`, where the file exists; return `files`. The
    workspace's state is recorded with it, as prep's execution records it with its handoff (`recorded`)."""
    recorded(ws)
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


def recorded(ws):
    """Record the state of the files in `ws` as an execution records it (BLD-workspace_record): what a hand-built
    fixture stands for — a workspace as prep's execution left it — or, in a test of a later check, a hand change taken
    as the workspace's state, so that the check under test is the one that meets it. A workspace prep's execution left
    holds its configuration, seeded by its first run (RUL-config_seeded_once): one the fixture did not write is seeded
    here, as that run would have. Returns `ws`."""
    import photos_utils
    if not os.path.exists(photos_utils.config_path(str(ws))):
        photos_utils.load_or_seed_config(str(ws))
    photos_utils.write_workspace_record(str(ws))
    return ws
