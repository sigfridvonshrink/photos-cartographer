# Copyright 2026 sigfridvonshrink
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""The combined `photos-cartographer` CLI dispatcher (cartographer/cli.py): self-documenting blurbs,
phase→subcommand wiring, and the geotag run→plan rename. From conftest.py."""
import pytest

from cartographer import cli, photos_1_prep, photos_2_geotag, photos_3_merge


def test_no_args_prints_overall_blurb(capsys):
    assert cli.main([]) == 0
    out = capsys.readouterr().out
    assert "photos-cartographer —" in out
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
    assert "photos-cartographer" in capsys.readouterr().out


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


def _setting_names(cfg, prefix=""):
    for key, value in cfg.items():
        yield prefix + key
        if isinstance(value, dict) and key != "datasets":
            yield from _setting_names(value, prefix + key + ".")
        elif isinstance(value, dict):
            yield from (prefix + key + "." + k for k in value)


@pytest.mark.spec("RUL-one_configuration", test="TST-combined_cli-no_command_takes_a_setting")
@pytest.mark.parametrize("command", [("prep", "plan"), ("prep", "dry-run"), ("prep", "execute"),
                                     ("prep", "prune-quarantine"), ("geotag", "plan"), ("geotag", "execute"),
                                     ("geotag", "finalize"), ("merge", "init-library"), ("merge", "plan"),
                                     ("merge", "dry-run"), ("merge", "execute")], ids="-".join)
def test_no_command_takes_a_setting(command, capsys):
    """No phase's command takes a setting of the configuration on its command line — under the setting's name, its
    last part, dashed or not, before the command or after it."""
    from cartographer import photos_utils
    phase, sub = command
    parser = cli.build_parser()
    for name in _setting_names(photos_utils.DEFAULT_CONFIG):
        for flag in {name, name.split(".")[-1]}:
            for spelt in {"--" + flag, "--" + flag.replace("_", "-").replace(".", "-")}:
                for argv in ([phase, spelt, "x", sub], [phase, sub, spelt, "x"]):
                    with pytest.raises(SystemExit) as e:
                        parser.parse_args(argv)
                    assert e.value.code == 2, argv
    capsys.readouterr()
