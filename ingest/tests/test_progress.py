"""ProgressCoordinator.set_detail — the per-item label (e.g. the destination being calibrated) that
calibration shows on the progress line so a heavy destination is visible while it's worked on. From
conftest.py (photos_utils loaded once into sys.modules)."""
import photos_utils as utils


def test_set_detail_appears_on_line_and_forces_render(capsys):
    c = utils.ProgressCoordinator(quiet=False)        # non-quiet; captured stderr is non-tty -> line mode
    c.start_phase("calibrating clock offsets", 3)
    c.set_detail("Japan/Kyoto")                        # forces an immediate render
    err = capsys.readouterr().err
    assert "calibrating clock offsets" in err and "Japan/Kyoto" in err


def test_start_phase_resets_detail(capsys):
    c = utils.ProgressCoordinator(quiet=False)
    c.start_phase("calibrating clock offsets", 2)
    c.set_detail("Japan/Kyoto")
    capsys.readouterr()                                # discard
    c.start_phase("deciding GPS placement", 5)         # must clear the prior detail
    c.set_detail("")
    err = capsys.readouterr().err
    assert "deciding GPS placement" in err and "Japan/Kyoto" not in err


def test_detail_silent_when_quiet(capsys):
    c = utils.ProgressCoordinator(quiet=True)          # piped/cron/tests default: no progress noise
    c.start_phase("calibrating clock offsets", 1)
    c.set_detail("Japan/Kyoto")
    c.increment_completed(1)
    assert capsys.readouterr().err == ""


def test_gpx_build_reports_per_file_progress(tmp_path):
    import photos_2_time_gps as cal
    d = tmp_path / "gpx"; d.mkdir()
    for i in range(3):
        (d / f"track{i}.gpx").write_text("")           # extension is enough to be counted
    c = utils.ProgressCoordinator(quiet=True)          # quiet: no output, but the count still advances
    cal.GPXIndex(str(d)).build(c)
    assert c.total_items == 3 and c.completed_items == 3
