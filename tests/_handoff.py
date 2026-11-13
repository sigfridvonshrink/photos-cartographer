"""Test helper: hand-built handoff records made to match the files on disk, as prep's would.

Geotag stops on a by-dest photo whose record no longer holds — gone, or differing in size or modification time from
the handoff (geotag §13) — so a fixture that writes a handoff by hand records what its files really are."""
import os


def match_disk(ws, files):
    """Set each record's `size` and `mtime_ns` to those of its file in `ws`, where the file exists; return `files`."""
    for rec in files:
        p = os.path.join(str(ws), rec.get("relative_path") or "")
        if os.path.isfile(p):
            st = os.stat(p)
            rec["size"], rec["mtime_ns"] = st.st_size, st.st_mtime_ns
    return files
