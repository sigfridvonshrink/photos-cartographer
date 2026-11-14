"""Test helper: settings for a run put everywhere but in the workspace's configuration (RUL-one_configuration).

`settings_elsewhere` puts a complete, valid configuration that differs from the workspace's in each place a setting
could otherwise come from: the seed-defaults file named by $PHOTOS_CARTOGRAPHER_CONFIG and the one beside the
executable, a configuration file in the folder above the workspace and in the user's home, and an environment variable
named after each setting. A run of an initialized workspace must follow its own configuration all the same."""
import json
import os
import sys


def settings_elsewhere(monkeypatch, tmp_path, other):
    """Put `other` (a complete configuration) everywhere but in the workspace under `tmp_path`."""
    text = json.dumps(other)
    seed = tmp_path / "elsewhere" / "defaults.json"
    seed.parent.mkdir()
    seed.write_text(text)
    monkeypatch.setenv("PHOTOS_CARTOGRAPHER_CONFIG", str(seed))
    exe = tmp_path / "bin" / "photos-cartographer"
    exe.parent.mkdir()
    exe.write_text("")
    (exe.parent / "photos-config-defaults.json").write_text(text)
    monkeypatch.setattr(sys, "argv", [str(exe)])
    home = tmp_path / "home"
    for folder in (tmp_path, tmp_path / ".photos-ingest", home, home / ".photos-ingest",
                   home / ".config" / "photos-cartographer"):
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "photos-00-config.json").write_text(text)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))

    def flat(cfg, prefix=""):
        for key, value in cfg.items():
            if isinstance(value, dict):
                yield from flat(value, prefix + key + "_")
            yield prefix + key, value
    for name, value in flat(other):
        shown = value if isinstance(value, str) else json.dumps(value)
        for var in (name.upper(), "PHOTOS_CARTOGRAPHER_" + name.upper()):
            monkeypatch.setenv(var, shown)
    return exe
