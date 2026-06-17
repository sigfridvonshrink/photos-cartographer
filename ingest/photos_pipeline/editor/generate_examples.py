#!/usr/bin/env python3
"""Generate example decision artifacts (fixtures) for the decision editor.

These are produced by the REAL geotag decision builders (`build_time_decisions`,
`compute_resolved_utc`, `build_gps_decisions` in `ingest/photos-2-time-gps`) and written with the
real `write_json_artifact` serializer — guaranteed byte-identical to a geotag run's output, not
hand-authored. The *inputs* are small synthetic photo sets chosen to exercise every distinct
decision-cell state the editor must render/edit; the *outputs* are authentic.

`complete` variants are produced exactly as the operator would: take the `requires-input` artifact,
fill in `user_decision` fields, and re-run the builder with it as the prior (the real
preservation/validation path).

Run from the repo root:  python3 ingest/decision-editor/generate_examples.py
"""
import json
import os
import sys
import tempfile
from datetime import datetime, timezone

# This dev tool lives at photos_pipeline/editor/generate_examples.py; it writes the demo fixtures into
# the sibling examples/ package-data dir, and imports the pipeline package from ingest/ (three levels up).
_INGEST = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "examples")

if _INGEST not in sys.path:
    sys.path.insert(0, _INGEST)
from photos_pipeline import photos_utils as utils, photos_2_time_gps as cal  # noqa: E402

BD = "6-photos-by-dest"
written = []


def _utc(h, m, s=0):
    return datetime(2024, 7, 3, h, m, s, tzinfo=timezone.utc)


def _pt(lat, lon, t):
    return cal.GPXPoint(lat, lon, t, "trip-2024-07-03.gpx", 0)


def _gpx(points):
    idx = cal.GPXIndex("")
    idx.points = list(points)
    return idx


def _file(rel, key, naive, *, gps=None, raw_times=None):
    """One by-dest photo in the in-memory file-model shape build_file_model produces."""
    return {"relative_path": rel, "destination": os.path.dirname(rel), "media_class": "raw",
            "content_fingerprint": "fp-" + rel, "size": 100, "mtime_ns": 1,
            "camera_group_key": key, "source_naive_time": naive, "source_time_tag": "DateTimeOriginal",
            "has_timestamp": True, "native_gps": gps, "has_native_gps": bool(gps),
            "raw_times": raw_times or {}}


def _policy(**over):
    base = dict(utils.CONFIG["camera_time_and_timezone_policy"])
    base.update(over)
    return base


def _set_policy(**over):
    utils.CONFIG["camera_time_and_timezone_policy"] = _policy(**over)


def _wf():
    ws = tempfile.mkdtemp()
    os.makedirs(os.path.join(ws, ".photos-ingest"), exist_ok=True)
    utils.write_json_artifact(utils.handoff_path(ws), {"files": [], "content_fingerprint": "example"})
    wf = cal.GeotagWorkflow(ws)
    wf._gpx_fingerprint = "example-gpx-fingerprint"
    return wf


def _emit(name, art):
    utils.write_json_artifact(os.path.join(OUT, name), art)
    written.append((name, art.get("status")))


def _copy(art):
    return json.loads(json.dumps(art))


def _td(wf, files, groups, gpx, fill, pre=None):
    """Build time decisions twice: a still-undecided "requires-input" state and the filled "complete".

    `pre` (optional) applies a partial prior to the requires-input pass — a legit mid-workflow state
    the editor opens (e.g. timezones already resolved, offsets still pending). It must leave the
    artifact `requires_user_input`; without it the requires-input pass is a fresh (no-prior) build."""
    base, blk = wf.build_time_decisions(files, groups, None, gpx)
    assert not blk, blk
    if pre is not None:
        req, blk = wf.build_time_decisions(files, groups, pre(_copy(base)), gpx)
        assert not blk, blk
        assert req["requires_user_input"], "pre() must leave the requires-input artifact undecided"
    else:
        req = base
    comp, blk = wf.build_time_decisions(files, groups, fill(_copy(req)), gpx)
    assert not blk, blk
    return req, comp


# =====================================================================================
# Scenario 1 — a realistic "trip": the common cases + structural edges + GPS categories.
# =====================================================================================

CAM_A = "SONY|ILCE-6400|A"          # geotagged in Japan -> gpx self-anchor, auto-resolved
CAM_B = "NIKON|D750|B"              # no GPX -> timezone-derived offset (manual override in one dest)
PHONE = "APPLE|iPhone15|P"          # smartphone -> no offset cell
JP, KY = f"{BD}/Japan", f"{BD}/Japan/Kyoto"
BE, BR = f"{BD}/Belgium", f"{BD}/Belgium/Bruges"
BRU = f"{BD}/Belgium/Brussels"      # CAM_A across 3 naive dates -> per-date offset buckets (§10.2)
PHO = f"{BD}/PhoneOnly"


def scenario_trip():
    _set_policy(device_groups={"fixed_clock_cameras": [CAM_A, CAM_B], "phones": [PHONE]},
                default_folder_timezone="Europe/Brussels")
    gpx = _gpx([_pt(50.0, round(4.0 + 0.0002 * m, 6), _utc(12, m)) for m in range(11)])  # 12:00..12:10
    files = [
        _file(f"{BD}/root-cam.arw", CAM_B, "2024:07:03 13:00:00", gps={"lat": 51.5, "lon": 4.5}),  # by-dest ROOT dest
        _file(f"{PHO}/phone-only.jpg", PHONE, "2024:07:03 13:30:00",                     # phone-only dest
              gps={"lat": 51.2, "lon": 4.4}, raw_times={"OffsetTimeOriginal": "+02:00"}),
        _file(f"{JP}/anchor-1.arw", CAM_A, "2024:07:03 14:00:00", gps={"lat": 50.0, "lon": 4.0}),
        _file(f"{JP}/anchor-2.arw", CAM_A, "2024:07:03 14:10:00", gps={"lat": 50.0, "lon": 4.002}),
        _file(f"{JP}/interp.arw", CAM_A, "2024:07:03 14:05:30"),                          # -> interpolation
        _file(f"{JP}/extrap.arw", CAM_A, "2024:07:03 14:11:30"),                          # -> extrapolation
        _file(f"{JP}/blocked-a.arw", CAM_A, "2024:07:03 22:00:00"),                       # -> review (manual)
        _file(f"{JP}/blocked-b.arw", CAM_A, "2024:07:03 23:00:00"),                       # -> review (unlocated)
        _file(f"{BE}/bel-cam.arw", CAM_B, "2024:07:03 13:00:00"),                         # -> folder fallback
        _file(f"{BE}/bel-phone.jpg", PHONE, "2024:07:03 13:30:00",
              gps={"lat": 51.0, "lon": 4.3}, raw_times={"OffsetTimeOriginal": "+02:00"}),
        _file(f"{BR}/bruges.arw", CAM_B, "2024:07:03 13:15:00", gps={"lat": 51.2, "lon": 3.2}),  # tz-derived offset
        # Per-date offset buckets (§10.2): CAM_A in one dest across 3 naive dates, no GPX anchor here
        # (far from the lat50/lon4 track) -> timezone-derived per day. Summer days share -7200 (CEST),
        # the winter day is -3600 (CET) -> DST-aware split; the two equal days collapse in the editor.
        # native-GPS so the GPS phase preserves-native and the bucket stays clean.
        _file(f"{BRU}/bru-summer-1.arw", CAM_A, "2024:07:03 14:00:00", gps={"lat": 50.85, "lon": 4.35}),
        _file(f"{BRU}/bru-summer-2.arw", CAM_A, "2024:07:04 14:00:00", gps={"lat": 50.85, "lon": 4.36}),
        _file(f"{BRU}/bru-winter.arw", CAM_A, "2024:12:22 14:00:00", gps={"lat": 50.85, "lon": 4.37}),
    ]
    groups = {CAM_A: {"camera_group_class": "camera"}, CAM_B: {"camera_group_class": "camera"},
              PHONE: {"camera_group_class": "phone"}}

    def fill_time(a):
        d = a["destinations"]
        d[JP]["destination_timezone"]["user_decision"]["manual_iana_timezone"] = "Asia/Tokyo"
        for dp in (BD, PHO, BE, BR, BRU):
            d[dp]["destination_timezone"]["user_decision"]["accept_proposed_timezone"] = True
        d[BD]["camera_group_time_decisions"][CAM_B]["user_decision"]["manual_offset_seconds"] = 0
        d[BE]["camera_group_time_decisions"][CAM_B]["user_decision"]["manual_offset_seconds"] = 3600  # manual override
        d[BR]["camera_group_time_decisions"][CAM_B]["user_decision"]["accept_proposal"] = True  # accept tz-derived
        for dt in ("2024-07-03", "2024-07-04", "2024-12-22"):                      # accept each per-date bucket
            d[BRU]["camera_group_time_decisions"][f"{CAM_A}@{dt}"]["user_decision"]["accept_proposal"] = True
        return a

    def pre_time(a):
        # Mid-workflow state for the requires-input fixture: the operator has resolved Brussels'
        # timezone (so its per-date offset buckets surface DST-aware timezone_naive proposals to
        # demo §10.2), but every offset — and all other timezones — is still pending.
        a["destinations"][BRU]["destination_timezone"]["user_decision"]["accept_proposed_timezone"] = True
        return a

    wf = _wf()
    time_req, time_comp = _td(wf, files, groups, gpx, fill_time, pre=pre_time)

    # GPS is built on the completed-time resolved rows (geotag only reaches GPS once time is done).
    rows = cal.compute_resolved_utc(files, groups, time_comp)
    rfp = "example-resolved-utc-fingerprint"
    gps_req, blk = wf.build_gps_decisions(files, rows, gpx, None, rfp)
    assert not blk, blk

    def fill_gps(a):
        d = a["destinations"]
        d[BE]["folder_fallback"]["user_decision"]["fallback_lat"] = 50.8503      # manual fallback
        d[BE]["folder_fallback"]["user_decision"]["fallback_lon"] = 4.3517
        d[BR]["folder_fallback"]["user_decision"]["accept_proposal"] = True       # inherit Belgium's
        for ri in d[JP]["gps_decisions"]["review_items"]:
            if ri["relative_path"].endswith("blocked-a.arw"):
                ri["user_decision"]["manual_lat"] = 35.0116
                ri["user_decision"]["manual_lon"] = 135.7681
            elif ri["relative_path"].endswith("blocked-b.arw"):
                ri["user_decision"]["accept_unlocated"] = True
        return a

    gps_comp, blk = wf.build_gps_decisions(files, rows, gpx, fill_gps(_copy(gps_req)), rfp)
    assert not blk, blk
    assert time_comp["status"] == "complete" and gps_comp["status"] == "complete", \
        (time_comp["status"], gps_comp["status"])

    _emit("photos-21-time-decisions.requires-input.json", time_req)
    _emit("photos-21-time-decisions.complete.json", time_comp)
    _emit("photos-23-gps-decisions.requires-input.json", gps_req)
    _emit("photos-23-gps-decisions.complete.json", gps_comp)


# =====================================================================================
# Scenario 2 — offset proposal/resolution variants (photos-21 only): single-anchor (high,
# accepted), segment (medium), conflicting (review_required), and manual_real_utc resolution.
# Each camera lives in its own destination + GPX region so matches never cross.
# =====================================================================================

CAM_PT = "CAM|single-point|S"       # one point anchor -> high, accepted -> gpx_anchor_accepted
CAM_SEG = "CAM|segment|G"           # one segment anchor -> medium
CAM_CONF = "CAM|conflict|C"         # two conflicting anchors -> review_required
CAM_UTC = "CAM|manual-utc|U"        # one point anchor -> resolved via manual_real_utc
P, S, C, U = f"{BD}/SinglePoint", f"{BD}/Segment", f"{BD}/Conflict", f"{BD}/ManualUtc"


def scenario_offset_variants():
    _set_policy(device_groups={"fixed_clock_cameras": [CAM_PT, CAM_SEG, CAM_CONF, CAM_UTC], "phones": []},
                default_folder_timezone="Europe/Brussels")
    gpx = _gpx([
        _pt(52.0, 6.0, _utc(12, 0, 0)),                                  # SinglePoint anchor
        _pt(53.0, 7.0, _utc(12, 0, 0)), _pt(53.0, 7.003, _utc(12, 0, 30)),  # Segment (~200 m, 30 s apart)
        _pt(54.0, 8.0, _utc(12, 0, 0)), _pt(55.0, 9.0, _utc(9, 0, 0)),    # Conflict (offsets disagree)
        _pt(56.0, 10.0, _utc(12, 0, 0)),                                  # ManualUtc anchor
    ])
    files = [
        _file(f"{P}/p.arw", CAM_PT, "2024:07:03 14:00:00", gps={"lat": 52.0, "lon": 6.0}),
        # near the segment interior (~33 m off) but >50 m from BOTH endpoints -> segment-only -> medium
        _file(f"{S}/g.arw", CAM_SEG, "2024:07:03 14:00:15", gps={"lat": 53.0003, "lon": 7.0015}),
        _file(f"{C}/c1.arw", CAM_CONF, "2024:07:03 14:00:00", gps={"lat": 54.0, "lon": 8.0}),
        _file(f"{C}/c2.arw", CAM_CONF, "2024:07:03 14:00:00", gps={"lat": 55.0, "lon": 9.0}),
        _file(f"{U}/u.arw", CAM_UTC, "2024:07:03 14:00:00", gps={"lat": 56.0, "lon": 10.0}),
    ]
    groups = {k: {"camera_group_class": "camera"} for k in (CAM_PT, CAM_SEG, CAM_CONF, CAM_UTC)}

    def fill(a):
        d = a["destinations"]
        for dp in (P, S, C, U):
            d[dp]["destination_timezone"]["user_decision"]["accept_proposed_timezone"] = True
        d[P]["camera_group_time_decisions"][CAM_PT]["user_decision"]["accept_proposal"] = True     # gpx_anchor_accepted (single)
        d[S]["camera_group_time_decisions"][CAM_SEG]["user_decision"]["accept_proposal"] = True     # gpx_anchor_accepted (medium)
        d[C]["camera_group_time_decisions"][CAM_CONF]["user_decision"]["manual_offset_seconds"] = -7200  # resolve a conflict manually
        # ManualUtc: enter the recommended anchor's true UTC -> source manual_real_utc.
        u_prop = d[U]["camera_group_time_decisions"][CAM_UTC]["proposal"]
        d[U]["camera_group_time_decisions"][CAM_UTC]["user_decision"]["manual_real_utc"] = u_prop["proposed_real_utc"]
        return a

    _, comp = _td(_wf(), files, groups, gpx, fill)
    _emit("photos-21-time-decisions.offset-variants.json", comp)


# =====================================================================================
# Scenario 3 — no default timezone: proposal_source "none" / confidence "none".
# =====================================================================================

def scenario_no_default_timezone():
    _set_policy(device_groups={"fixed_clock_cameras": [CAM_A], "phones": []}, default_folder_timezone="")
    files = [_file(f"{BD}/Nowhere/x.arw", CAM_A, "2024:07:03 14:00:00")]
    groups = {CAM_A: {"camera_group_class": "camera"}}
    req, _ = wf_req = _wf().build_time_decisions(files, groups, None, _gpx([]))
    assert not wf_req[1], wf_req[1]
    _emit("photos-21-time-decisions.no-default-timezone.json", req)


# =====================================================================================
# Scenario 4 — a stale user_decision: the operator accepted a proposal that no longer exists
# (e.g. the GPX evidence changed since they decided). The accept is inert; re-decide.
# =====================================================================================

def scenario_stale_decision():
    _set_policy(device_groups={"fixed_clock_cameras": [CAM_B], "phones": []},
                default_folder_timezone="Europe/Brussels")
    files = [_file(f"{BD}/Stale/x.arw", CAM_B, "2024:07:03 13:00:00")]   # no GPX -> manual_required (no proposal)
    groups = {CAM_B: {"camera_group_class": "camera"}}
    wf = _wf()
    base, blk = wf.build_time_decisions(files, groups, None, _gpx([]))
    assert not blk, blk
    prior = _copy(base)
    dest = f"{BD}/Stale"
    # The operator had previously accepted an offset proposal + a timezone proposal that are now gone.
    prior["destinations"][dest]["camera_group_time_decisions"][CAM_B]["user_decision"]["accept_proposal"] = True
    art, blk = wf.build_time_decisions(files, groups, prior, _gpx([]))
    assert not blk, blk
    cell = art["destinations"][dest]["camera_group_time_decisions"][CAM_B]
    assert cell["stale_user_decision"] is True, cell
    _emit("photos-21-time-decisions.stale-decision.json", art)


# =====================================================================================
# Scenario 5 — GPS-drift validation (photos-22): a timezone-derived offset with no native-GPS
# anchor but GPX coverage -> the bucket must be confirmed (or corrected) before GPS is placed.
# =====================================================================================

CAM_DR = "CAM|drift|D"
DR = f"{BD}/DriftTown"


def scenario_drift_validation():
    _set_policy(device_groups={"fixed_clock_cameras": [CAM_DR], "phones": []},
                default_folder_timezone="Europe/Brussels")
    gpx = _gpx([_pt(50.0, round(4.0 + 0.0006 * m, 6), _utc(12, m)) for m in range(11)])  # 12:00..12:10
    files = [_file(f"{DR}/d1.arw", CAM_DR, "2024:07:03 14:00:00"),       # no native GPS -> tz-derived offset
             _file(f"{DR}/d2.arw", CAM_DR, "2024:07:03 14:05:00")]
    groups = {CAM_DR: {"camera_group_class": "camera"}}

    def fill_time(a):
        d = a["destinations"]
        for dp in (BD, DR):
            d[dp]["destination_timezone"]["user_decision"]["accept_proposed_timezone"] = True
        d[DR]["camera_group_time_decisions"][CAM_DR]["user_decision"]["accept_proposal"] = True  # tz-derived
        return a

    wf = _wf()
    _, time_comp = _td(wf, files, groups, gpx, fill_time)
    assert time_comp["status"] == "complete", time_comp["status"]
    # build_drift_validation hashes the on-disk photos-21, exactly as the real run writes it first.
    utils.write_json_artifact(cal.time_decisions_path(wf.workspace_root), time_comp)
    rows0 = cal.compute_resolved_utc(files, groups, time_comp)
    drift_req, blk = wf.build_drift_validation(files, time_comp, rows0, gpx, None)
    assert not blk, blk

    def fill_drift(a):                                                   # confirm the bucket (zero scrub)
        a["destinations"][DR]["drift_decisions"][CAM_DR]["user_decision"]["confirmed"] = True
        return a

    drift_comp, blk = wf.build_drift_validation(files, time_comp, rows0, gpx, fill_drift(_copy(drift_req)))
    assert not blk, blk
    assert drift_req["requires_user_input"] and drift_comp["status"] == "complete", \
        (drift_req["status"], drift_comp["status"])
    _emit("photos-22-gps-drift-validation.requires-input.json", drift_req)
    _emit("photos-22-gps-drift-validation.complete.json", drift_comp)


# =====================================================================================

def _verify():
    """Fail loudly unless every distinct decision-cell state appears across the fixtures."""
    blob = ""
    for name, _ in written:
        blob += open(os.path.join(OUT, name)).read()
    required = [
        '"proposal_source": "config_default"', '"proposal_source": "inherited"',  # inherited: timezone only
        '"proposal_source": "none"', '"proposal_source": "gpx_self_anchor"',
        '"proposal_source": "timezone_naive"', '"proposal_source": "manual_required"',
        '"source": "gpx_anchor_auto"', '"source": "gpx_anchor_accepted"',
        '"source": "timezone_accepted"', '"source": "manual"', '"source": "manual_real_utc"',
        '"confidence": "high"', '"confidence": "medium"', '"confidence": "review_required"',
        '"stale_user_decision": true',
        '"reason": "no_reliable_gps_source"', '"reason": "manual_locked"', '"reason": "accepted_unlocated"',
    ]
    missing = [m for m in required if m not in blob]
    # GPS automatic categories live in summary counts (>0 somewhere).
    cat_missing = []
    for name, _ in written:
        pass
    gps = json.load(open(os.path.join(OUT, "photos-23-gps-decisions.complete.json")))
    totals = {k: 0 for k in ("preserve_native_gps", "automatic_gpx_interpolation",
                             "automatic_gpx_extrapolation", "automatic_folder_fallback")}
    for d in gps["destinations"].values():
        for k in totals:
            totals[k] += d["gps_decisions"]["summary"][k]
    cat_missing = [k for k, v in totals.items() if v == 0]
    # by-dest-root destination + phone-only destination (no offset cells) present.
    td = json.load(open(os.path.join(OUT, "photos-21-time-decisions.complete.json")))
    struct = []
    if BD not in td["destinations"]:
        struct.append("by-dest-root destination")
    if not any(not v["camera_group_time_decisions"] for v in td["destinations"].values()):
        struct.append("phone-only destination (no offset cells)")
    # GPS-drift (22): the gate's two states + the scrub evidence the editor renders.
    dr_req = json.load(open(os.path.join(OUT, "photos-22-gps-drift-validation.requires-input.json")))
    dr_comp = json.load(open(os.path.join(OUT, "photos-22-gps-drift-validation.complete.json")))
    drift = []
    rc = next(iter(dr_req["destinations"][DR]["drift_decisions"].values()))
    cc = next(iter(dr_comp["destinations"][DR]["drift_decisions"].values()))
    if not (rc["requires_user_input"] and rc["proposal"]["frames"] and rc["proposal"]["track_segment"]):
        drift.append("22 requires-input cell with frames + track_segment")
    if not (cc["effective_drift_offset"] and cc["effective_drift_offset"].get("source") == "gps_drift_validated"):
        drift.append("22 confirmed cell with gps_drift_validated effective offset")
    problems = missing + [f"GPS category {c}" for c in cat_missing] + struct + drift
    if problems:
        raise SystemExit("MISSING decision states in fixtures:\n  " + "\n  ".join(problems))


def main():
    os.makedirs(OUT, exist_ok=True)
    scenario_trip()
    scenario_offset_variants()
    scenario_no_default_timezone()
    scenario_stale_decision()
    scenario_drift_validation()
    _verify()
    for name, status in written:
        print(f"wrote examples/{name}  (status={status})")
    print(f"OK — {len(written)} fixtures; every decision-cell state covered.")


if __name__ == "__main__":
    main()
