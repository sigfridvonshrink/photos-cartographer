"""Phase 3c (geotag) — §10.2 per-date offset buckets.

A camera is set to local time each morning, so its clock offset is constant only WITHIN a naive
calendar day. When one (camera group, destination) spans >1 naive date, the offset cell SPLITS into
per-day buckets keyed `<group>@<YYYY-MM-DD>`; the single-date common case keeps the bare `<group>`
key. Each bucket proposes independently (here: timezone-derived, DST-aware). Resolved-UTC picks the
file's own date bucket. From conftest.py.
"""
import photos_2_time_gps as cal
import photos_utils as utils

BYDEST = "6-photos-by-dest"
CAM = "SONY|ILCE-6400|123"
GROUPS = {CAM: {"camera_group_class": "camera"}}


def _wf(tmp_path):
    ws = tmp_path / "ws"
    (ws / ".photos-ingest").mkdir(parents=True)
    (ws / ".photos-ingest" / "photos-11-handoff.json").write_text("{}")
    wf = cal.GeotagWorkflow(str(ws))
    wf._gpx_fingerprint = "fp"
    return wf


def _gpx():
    idx = cal.GPXIndex("")
    idx.points = []
    return idx


def _file(rel, dest, naive):
    return {"relative_path": rel, "destination": dest, "camera_group_key": CAM,
            "native_gps": None, "has_native_gps": False, "has_timestamp": True,
            "source_naive_time": naive, "camera_identity": {}}


def _tz(default="Europe/Brussels"):
    utils.CONFIG["camera_time_and_timezone_policy"]["default_folder_timezone"] = default


def _prior(cells=None):
    # accept the destination timezone so the leaf resolves a tz (needed for tz-derived offsets),
    # carrying any per-bucket offset decisions alongside.
    dest = {"destination_timezone": {"user_decision": {"accept_proposed_timezone": True}}}
    if cells:
        dest["camera_group_time_decisions"] = cells
    return {"destinations": {f"{BYDEST}/D": dest}}


def test_single_date_keeps_bare_group_key(tmp_path):
    _tz()
    wf = _wf(tmp_path)
    files = [_file(f"{BYDEST}/D/a.arw", f"{BYDEST}/D", "2024:07:03 09:00:00"),
             _file(f"{BYDEST}/D/b.arw", f"{BYDEST}/D", "2024:07:03 18:00:00")]
    art, _ = wf.build_time_decisions(files, GROUPS, _prior(), _gpx())
    cells = art["destinations"][f"{BYDEST}/D"]["camera_group_time_decisions"]
    assert set(cells) == {CAM}                              # one day → one bare bucket
    assert "date" not in cells[CAM]


def test_multi_date_splits_into_per_day_buckets(tmp_path):
    _tz()
    wf = _wf(tmp_path)
    files = [_file(f"{BYDEST}/D/a.arw", f"{BYDEST}/D", "2024:07:03 14:00:00"),   # summer +2
             _file(f"{BYDEST}/D/b.arw", f"{BYDEST}/D", "2024:01:03 14:00:00")]   # winter +1
    art, _ = wf.build_time_decisions(files, GROUPS, _prior(), _gpx())
    cells = art["destinations"][f"{BYDEST}/D"]["camera_group_time_decisions"]
    assert set(cells) == {f"{CAM}@2024-07-03", f"{CAM}@2024-01-03"}
    summer, winter = cells[f"{CAM}@2024-07-03"], cells[f"{CAM}@2024-01-03"]
    assert summer["date"] == "2024-07-03" and winter["date"] == "2024-01-03"
    # each bucket derives its OWN DST-aware offset from the local clock
    assert summer["proposal"]["proposed_offset_seconds"] == -7200
    assert winter["proposal"]["proposed_offset_seconds"] == -3600


def test_per_bucket_manual_decision_is_independent(tmp_path):
    _tz()
    wf = _wf(tmp_path)
    files = [_file(f"{BYDEST}/D/a.arw", f"{BYDEST}/D", "2024:07:03 14:00:00"),
             _file(f"{BYDEST}/D/b.arw", f"{BYDEST}/D", "2024:01:03 14:00:00")]
    prior = _prior({f"{CAM}@2024-07-03": {"user_decision": {"manual_offset_seconds": -111}}})
    art, _ = wf.build_time_decisions(files, GROUPS, prior, _gpx())
    cells = art["destinations"][f"{BYDEST}/D"]["camera_group_time_decisions"]
    assert cells[f"{CAM}@2024-07-03"]["effective_time_anchor"] == {"offset_seconds": -111, "source": "manual"}
    assert cells[f"{CAM}@2024-01-03"]["requires_user_input"] is True   # the other day untouched


def test_resolved_utc_picks_the_files_own_date_bucket(tmp_path):
    _tz()
    wf = _wf(tmp_path)
    files = [_file(f"{BYDEST}/D/a.arw", f"{BYDEST}/D", "2024:07:03 14:00:00"),
             _file(f"{BYDEST}/D/b.arw", f"{BYDEST}/D", "2024:01:03 14:00:00")]
    # accept both per-day proposals so each bucket resolves to its tz-derived offset
    prior = _prior({f"{CAM}@2024-07-03": {"user_decision": {"accept_proposal": True}},
                    f"{CAM}@2024-01-03": {"user_decision": {"accept_proposal": True}}})
    art, _ = wf.build_time_decisions(files, GROUPS, prior, _gpx())
    rows = {r["relative_path"]: r for r in cal.compute_resolved_utc(files, GROUPS, art)}
    assert rows[f"{BYDEST}/D/a.arw"]["utc_offset_used"] == -7200  # summer file uses summer bucket
    assert rows[f"{BYDEST}/D/a.arw"]["resolved_utc"] == "2024-07-03T12:00:00Z"
    assert rows[f"{BYDEST}/D/b.arw"]["utc_offset_used"] == -3600  # winter file uses winter bucket
    assert rows[f"{BYDEST}/D/b.arw"]["resolved_utc"] == "2024-01-03T13:00:00Z"
