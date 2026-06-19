"""The combined `photos-ingest` CLI dispatcher (photos_pipeline/cli.py): self-documenting blurbs,
phase→subcommand wiring, and the geotag run→plan rename. From conftest.py."""
import pytest

from photos_pipeline import cli, photos_1_prep, photos_2_geotag, photos_3_merge


def test_no_args_prints_overall_blurb(capsys):
    assert cli.main([]) == 0
    out = capsys.readouterr().out
    assert "photos-ingest —" in out
    assert "prep" in out and "geotag" in out and "merge" in out


@pytest.mark.parametrize("phase, needle", [
    ("prep", "prep — get a raw photo dump"),
    ("geotag", "geotag — place every photo"),
    ("merge", "merge — move the calibrated library"),
])
def test_phase_without_subcommand_prints_phase_blurb(capsys, phase, needle):
    assert cli.main([phase]) == 0
    assert needle in capsys.readouterr().out


def test_version(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["--version"])
    assert e.value.code == 0
    assert "photos-ingest" in capsys.readouterr().out


def _parse(argv):
    return cli.build_parser().parse_args(argv)


def test_phase_subcommand_wires_the_right_handler():
    a = _parse(["prep", "plan"])
    assert a.phase == "prep" and a.command == "plan" and a._run is photos_1_prep.run
    a = _parse(["geotag", "plan"])
    assert a.phase == "geotag" and a.command == "plan" and a._run is photos_2_geotag.run
    a = _parse(["merge", "init-library"])
    assert a.phase == "merge" and a.command == "init-library" and a._run is photos_3_merge.run


def test_geotag_run_was_renamed_to_plan():
    # the old `run` subcommand no longer exists; `plan` is the current name
    with pytest.raises(SystemExit):
        _parse(["geotag", "run"])
    assert _parse(["geotag", "plan"]).command == "plan"


def test_jobs_option_on_phase():
    a = _parse(["prep", "-j", "3", "plan"])
    assert a.jobs == 3 and a.command == "plan"
