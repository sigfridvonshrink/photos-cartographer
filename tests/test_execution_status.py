"""Terminal-status derivation for geotag/merge executions, including the explicit `failed` status
(spec reconciliation: photos-2 §29.2 item 7 / photos-3 §9.1 item 8). `failed` = ran past the
mutation gate but achieved nothing; `partial` = mixed; `success` = clean. Pre-mutation aborts are
`rejected`, decided elsewhere."""

import photos_2_geotag as geo
import photos_3_merge as merge


# --- geotag --------------------------------------------------------------

def test_geotag_success_when_clean():
    assert geo.geotag_execution_status(0, 0, [], [], []) == "success"
    assert geo.geotag_execution_status(5, 0, [], [], []) == "success"      # applied, no problems
    assert geo.geotag_execution_status(0, 9, [], [], []) == "success"      # all already-satisfied


def test_geotag_partial_when_some_progress_or_mismatch():
    assert geo.geotag_execution_status(3, 0, ["f"], [], []) == "partial"   # some applied + a failure
    assert geo.geotag_execution_status(0, 4, [], [], ["b"]) == "partial"   # already-done + a blocker
    assert geo.geotag_execution_status(0, 0, [], ["m"], []) == "partial"   # mismatch alone -> partial
    assert geo.geotag_execution_status(0, 0, ["f"], ["m"], []) == "partial"  # mismatch forces partial


def test_geotag_failed_when_nothing_achieved():
    assert geo.geotag_execution_status(0, 0, ["f"], [], []) == "failed"    # all failed, nothing else
    assert geo.geotag_execution_status(0, 0, [], [], ["b"]) == "failed"    # all blocked, nothing else
    assert geo.geotag_execution_status(0, 0, ["f1", "f2"], [], ["b"]) == "failed"


# --- merge ---------------------------------------------------------------

def _r(kind):
    return {"final_kind": kind}


def test_merge_success_when_none_blocked():
    assert merge.merge_execution_status([]) == "success"                   # nothing to do
    assert merge.merge_execution_status([_r("placed_new"), _r("already_present")]) == "success"


def test_merge_partial_when_some_blocked_some_placed():
    assert merge.merge_execution_status([_r("placed_new"), _r("blocked")]) == "partial"
    assert merge.merge_execution_status([_r("renamed_for_library"), _r("blocked"), _r("blocked")]) == "partial"


def test_merge_failed_when_all_blocked():
    assert merge.merge_execution_status([_r("blocked")]) == "failed"
    assert merge.merge_execution_status([_r("blocked"), _r("blocked")]) == "failed"
