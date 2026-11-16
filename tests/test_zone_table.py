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

"""The table of countries where the host's zone database has none (BACKLOG 47 (e)): the host's own table, else a copy
downloaded for the workspace on the user's word, else the copy the package carries. No test reaches the network: the
download is the `_download_zone_archive` seam, replaced here (and refused by default in conftest.py)."""
import io
import json
import os
import tarfile
import types

import pytest

import photos_1_prep as prep
import photos_utils as utils
from cartographer.reporting import CaptureSink, Reporter, TtySink, use_reporter

# The real download function, taken at import, before conftest's autouse guard replaces it for every test.
_REAL_DOWNLOAD = utils._download_zone_archive

MANAGED = ["0-sources", "1-strays", "2-missing-metadata", "3-redundant-jpgs",
           "4-videos-by-date", "5-photos-by-date", "6-photos-by-dest"]


def _archive(members):
    """A tzdata release as `tzdata-latest.tar.gz` is: a gzipped tar of the given {name: text}."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, text in members.items():
            data = text.encode("utf-8")
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


# A "release" differing from the carried copy: Lithuania alone, so the table read shows where it came from.
WEB_ZONE_TAB = "# zone.tab\nLT\t+5441+02519\tEurope/Vilnius\n"
WEB_ISO_TAB = "# iso3166.tab\nLT\tLithuania\n"
GOOD = {"zone.tab": WEB_ZONE_TAB, "iso3166.tab": WEB_ISO_TAB, "version": "2099z\n"}


@pytest.fixture
def no_host_table(monkeypatch):
    """A host whose zone database ships without its tables (some minimal images)."""
    real = utils._zone_database_file
    monkeypatch.setattr(utils, "_zone_database_file",
                        lambda name: None if name in ("zone.tab", "iso3166.tab") else real(name))


@pytest.fixture
def server(monkeypatch):
    """The download, answered from memory: records each request's url and timeout."""
    calls = []
    state = {"bytes": _archive(GOOD), "fail": None}

    def fake(url, timeout):
        calls.append((url, timeout))
        if state["fail"]:
            raise state["fail"]
        return state["bytes"]
    monkeypatch.setattr(utils, "_download_zone_archive", fake)
    return types.SimpleNamespace(calls=calls, state=state)


def _ws(tmp_path):
    ws = tmp_path / "ws"
    (ws / ".photos-ingest").mkdir(parents=True)
    return str(ws)


def _settle(ws, answer):
    cap = CaptureSink()
    with use_reporter(Reporter([cap])) as rep:
        utils.settle_zone_table(ws, answer, rep)
    return cap


def _warned(cap):
    return "\n".join(e.msg for e in cap.logs() if e.level == "warn")


def _record(ws):
    with open(utils.zone_table_path(ws)) as f:
        return json.load(f)


@pytest.mark.spec("RUL-zone_table_host_first", "BLD-country_table", test="TST-zone_table-host_then_workspace_then_carried")
def test_host_then_workspace_then_carried(tmp_path, monkeypatch, server):
    ws = _ws(tmp_path)
    assert utils.zone_table(ws)["source"] == "host"            # this host has its own table: it is read
    real = utils._zone_database_file
    monkeypatch.setattr(utils, "_zone_database_file",
                        lambda name: None if name in ("zone.tab", "iso3166.tab") else real(name))
    carried = utils.zone_table(ws)
    assert carried["source"] == "bundled" and "US" in carried["countries"]
    assert len(carried["countries"]["US"]["zones"]) > 1
    _settle(ws, "yes")
    web = utils.zone_table(ws)
    assert web["source"] == "web" and web["countries"] == {"LT": {"name": "Lithuania", "zones": ["Europe/Vilnius"]}}
    assert utils.country_table(ws) == web["countries"] and web["sha256"] != carried["sha256"]
    assert utils.zone_table(None)["source"] == "bundled"          # no workspace: no copy of its own


@pytest.mark.spec("RUL-zone_table_zone_known", "BLD-country_table", test="TST-zone_table-unknown_zone_is_no_countrys")
def test_unknown_zone_is_no_countrys():
    table = utils._parse_country_table("XA\t+0000+00000\tMars/Olympus_Mons\n"
                                       "LT\t+5441+02519\tEurope/Vilnius\nLT\t+5441+02519\tMars/Tharsis\n",
                                       "XA\tNowhere\nLT\tLithuania\n")
    assert table == {"LT": {"name": "Lithuania", "zones": ["Europe/Vilnius"]}}


@pytest.mark.spec("RUL-zone_table_download_where_missing", "BLD-zone_table_question",
                  test="TST-zone_table-nothing_asked_or_fetched_where_the_host_has_it")
def test_nothing_asked_or_fetched_where_the_host_has_it(tmp_path, server):
    ws = _ws(tmp_path)
    assert utils.host_has_zone_table() and not utils.zone_table_question_pending(ws)
    _settle(ws, "yes")
    _settle(ws, None)
    assert server.calls == [] and not os.path.exists(utils.zone_table_path(ws))


@pytest.mark.spec("RUL-zone_table_download_on_word", "RUL-zone_table_never_stops_prep", "BLD-zone_table_question",
                  test="TST-zone_table-unanswered_downloads_nothing_and_goes_on")
def test_unanswered_downloads_nothing_and_goes_on(tmp_path, no_host_table, server):
    ws = _ws(tmp_path)
    assert utils.zone_table_question_pending(ws)
    # nobody at a terminal to answer — the console's run, a pipe: no question, no answer
    assert prep._zone_table_answer(types.SimpleNamespace(), ws, Reporter([CaptureSink()])) is None
    cap = _settle(ws, None)
    assert server.calls == [] and not os.path.exists(utils.zone_table_path(ws))
    assert "--download-zone-table yes" in _warned(cap)            # how to answer, said
    assert utils.zone_table(ws)["source"] == "bundled"
    assert utils.zone_table_question_pending(ws)                  # still to be answered


@pytest.mark.spec("RUL-zone_table_refusal_told", "BLD-zone_table_question",
                  test="TST-zone_table-the_question_says_what_refusing_leaves")
def test_the_question_says_what_refusing_leaves(tmp_path, monkeypatch, no_host_table, server):
    ws = _ws(tmp_path)
    question = utils.zone_table_question(utils.bundled_zone_table()["tzdata_version"])
    assert "refuse" in question and "stale" in question and "2026c" in question
    # at a terminal, the question is put and answered before anything is downloaded
    monkeypatch.setattr(prep.sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr("builtins.input", lambda prompt="": "y")
    cap = CaptureSink()
    rep = Reporter([TtySink(stream=io.StringIO()), cap])
    assert prep._zone_table_answer(types.SimpleNamespace(), ws, rep) == "yes"
    assert question in _warned(cap) and server.calls == []
    monkeypatch.setattr("builtins.input", lambda prompt="": "")       # the default is no
    assert prep._zone_table_answer(types.SimpleNamespace(), ws, rep) == "no"
    # an answer given with the command is taken as given: nothing is asked
    monkeypatch.setattr("builtins.input", lambda prompt="": pytest.fail("asked although answered"))
    assert prep._zone_table_answer(types.SimpleNamespace(download_zone_table="no"), ws, rep) == "no"
    # and the console's runs, whose reporter writes to no terminal, are never asked
    assert prep._zone_table_answer(types.SimpleNamespace(), ws, Reporter([cap])) is None


@pytest.mark.spec("RUL-zone_table_asked_once", "BLD-zone_table_question", test="TST-zone_table-the_answer_is_kept")
def test_the_answer_is_kept(tmp_path, monkeypatch, no_host_table, server):
    ws = _ws(tmp_path)
    cap = _settle(ws, "no")
    assert _record(ws)["download"] == "declined" and server.calls == []
    assert "stale" in "\n".join(e.msg for e in cap.logs())
    assert not utils.zone_table_question_pending(ws)
    monkeypatch.setattr(prep.sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr("builtins.input", lambda prompt="": pytest.fail("asked again"))
    rep = Reporter([TtySink(stream=io.StringIO())])
    assert prep._zone_table_answer(types.SimpleNamespace(), ws, rep) is None
    assert _warned(_settle(ws, None)) == ""                        # answered: nothing more to say
    assert utils.zone_table(ws)["source"] == "bundled"


@pytest.mark.spec("RUL-zone_table_downloaded_once", "RUL-zone_table_copy_kept", "BLD-zone_table_download",
                  test="TST-zone_table-a_permission_downloads_once_into_the_records")
def test_a_permission_downloads_once_into_the_records(tmp_path, no_host_table, server):
    ws = _ws(tmp_path)
    _settle(ws, "yes")
    assert server.calls == [(utils.ZONE_TABLE_URL, utils.ZONE_TABLE_TIMEOUT_S)]
    rec = _record(ws)
    assert rec["download"] == "accepted" and rec["copy"]["zone_tab"] == WEB_ZONE_TAB
    assert rec["copy"]["iso3166_tab"] == WEB_ISO_TAB and rec["copy"]["tzdata_version"] == "2099z"
    for _ in range(2):
        _settle(ws, None)                                          # later runs: never fetched again silently
    assert len(server.calls) == 1
    # the copy is a control record, archived (and so sealed) with the others; the archive itself never lands on disk
    assert utils.ZONE_TABLE_ARTIFACT in [os.path.basename(m) for m in utils.control_archive_members(ws)]
    assert sorted(os.listdir(os.path.join(ws, ".photos-ingest"))) == [utils.ZONE_TABLE_ARTIFACT]


@pytest.mark.spec("RUL-zone_table_checked", "RUL-zone_table_failure_told", "BLD-zone_table_download",
                  test="TST-zone_table-a_bad_download_leaves_the_table_in_use")
@pytest.mark.parametrize("bad", ["offline", "not_an_archive", "no_zone_tab", "malformed", "empty"])
def test_a_bad_download_leaves_the_table_in_use(tmp_path, no_host_table, server, bad):
    ws = _ws(tmp_path)
    if bad == "offline":
        server.state["fail"] = OSError("timed out")
    elif bad == "not_an_archive":
        server.state["bytes"] = b"<html>not found</html>"
    elif bad == "no_zone_tab":
        server.state["bytes"] = _archive({"iso3166.tab": WEB_ISO_TAB})
    elif bad == "malformed":
        server.state["bytes"] = _archive(dict(GOOD, **{"zone.tab": WEB_ZONE_TAB + "LT Europe/Vilnius\n"}))
    else:
        server.state["bytes"] = _archive(dict(GOOD, **{"zone.tab": "# nothing\n"}))
    cap = _settle(ws, "yes")
    assert "could not be downloaded" in _warned(cap) and "carried" in _warned(cap)
    rec = _record(ws)
    assert rec["download"] == "accepted" and "copy" not in rec and rec["failure"]
    assert utils.zone_table(ws)["source"] == "bundled"
    # a copy downloaded earlier stays: a later failing download changes nothing
    server.state.update(fail=None, bytes=_archive(GOOD))
    _settle(ws, "yes")
    kept = _record(ws)
    server.state["fail"] = OSError("offline")
    cap = _settle(ws, "yes")
    assert "earlier stays in use" in _warned(cap)
    assert _record(ws) == kept and utils.zone_table(ws)["source"] == "web"


@pytest.mark.spec("RUL-zone_table_request_bare", "BLD-zone_table_download",
                  test="TST-zone_table-the_request_names_only_the_tool")
def test_the_request_names_only_the_tool(tmp_path, monkeypatch):
    import urllib.request
    seen = []

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    payload = _archive(GOOD)

    class Opener:
        def open(self, req, timeout=None):
            seen.append((req, timeout))
            return Resp(payload)
    monkeypatch.setattr(utils, "_https_only_opener", Opener)
    assert _REAL_DOWNLOAD(utils.ZONE_TABLE_URL, utils.ZONE_TABLE_TIMEOUT_S) == payload
    (req, timeout), = seen
    assert req.full_url == "https://data.iana.org/time-zones/tzdata-latest.tar.gz" and timeout == 20
    assert req.header_items() == [("User-agent", "photos-cartographer")]
    assert req.data is None and req.get_method() == "GET"
    ws = str(tmp_path)
    assert ws not in req.full_url and os.environ.get("USER", "\0") not in req.full_url


@pytest.mark.spec("RUL-zone_table_never_stops_prep", "RUL-zone_table_downloaded_once", "BLD-zone_table_question",
                  test="TST-zone_table-prep_plan_takes_the_answer_and_goes_on")
@pytest.mark.parametrize("answer", [None, "no", "yes"])
def test_prep_plan_takes_the_answer_and_goes_on(tmp_path, monkeypatch, no_host_table, server, answer):
    """The first `prep plan` of a workspace, given the answer or none, plans as it would anyway."""
    ws = tmp_path / "ws"
    for d in MANAGED:
        (ws / d).mkdir(parents=True)
    (ws / ".photos-ingest").mkdir()
    (ws / ".photos-ingest" / "photos-00-workspace-guard").touch()
    prep.CONFIG["zfs"] = {"enabled": False}
    monkeypatch.chdir(ws)
    cap = CaptureSink()
    with use_reporter(Reporter([cap])):
        try:
            prep.run(types.SimpleNamespace(command="plan", jobs=1, download_zone_table=answer))
        except SystemExit as e:
            assert not e.code, [x.msg for x in cap.logs()]
    assert os.path.exists(utils.prep_plan_path(str(ws)))
    if answer is None:
        assert not os.path.exists(utils.zone_table_path(str(ws))) and server.calls == []
    else:
        assert _record(str(ws))["download"] == {"yes": "accepted", "no": "declined"}[answer]
        assert len(server.calls) == (answer == "yes")


def test_the_flag_is_on_prep_plan_only():
    import argparse
    parser = argparse.ArgumentParser()
    prep.add_arguments(parser)
    assert parser.parse_args(["plan", "--download-zone-table", "yes"]).download_zone_table == "yes"
    assert parser.parse_args(["plan"]).download_zone_table is None
    with pytest.raises(SystemExit):
        parser.parse_args(["plan", "--download-zone-table", "maybe"])
    with pytest.raises(SystemExit):
        parser.parse_args(["execute", "--download-zone-table", "yes"])


@pytest.mark.spec("BLD-zone_table_question", test="TST-zone_table-the_console_asks_the_same_question")
def test_the_console_asks_the_same_question(tmp_path, monkeypatch, server):
    """The console's prep Plan asks what `prep plan` asks, and carries the answer into the same run as the flag."""
    from cartographer.console import server as console
    ws = _ws(tmp_path)
    assert console._zone_table_state(ws, False) is None                 # the host has its own table
    real = utils._zone_database_file
    monkeypatch.setattr(utils, "_zone_database_file",
                        lambda name: None if name in ("zone.tab", "iso3166.tab") else real(name))
    st = console._zone_table_state(ws, False)
    assert st == {"question": utils.zone_table_question(utils.bundled_zone_table()["tzdata_version"])}
    assert console._zone_table_state(ws, True) is None                  # sealed: prep plan is refused anyway
    assert console._zone_table_extra("prep", "plan", {"zone_table": "yes"}) == (["--download-zone-table", "yes"], None)
    assert console._zone_table_extra("prep", "plan", {}) == ([], None)
    assert console._zone_table_extra("prep", "plan", {"zone_table": "sure"})[1]
    assert console._zone_table_extra("geotag", "plan", {"zone_table": "no"})[1]
    assert callable(console._make_target("prep", "plan", ["--download-zone-table", "no"]))
    _settle(ws, "no")
    assert console._zone_table_state(ws, False) is None                 # answered: not asked again
    js = console._asset("app.js").decode()
    assert "zone_table: answer" in js and "s.zone_table" in js
    assert 'id="zone-overlay"' in console._asset("/").decode()


@pytest.mark.spec("RUL-unreadable_zone_table_record_stops", "BLD-zone_table_question", "BLD-exit_statuses",
                  test="TST-zone_table-an_unreadable_record_stops_the_run")
@pytest.mark.parametrize("held", ["{torn", '"accepted"', '{"download": "maybe"}'])
def test_an_unreadable_record_stops_the_run(tmp_path, monkeypatch, no_host_table, server, held):
    """A record of the answer that is there and cannot be read is not no answer: `prep plan` and a geotag command stop
    on it, naming it, nothing planned, asked, downloaded or written over; the console asks nothing."""
    from cartographer.console import server as console
    import photos_2_geotag as cal
    ws = tmp_path / "ws"
    for d in MANAGED:
        (ws / d).mkdir(parents=True)
    (ws / ".photos-ingest").mkdir()
    (ws / ".photos-ingest" / "photos-00-workspace-guard").touch()
    rec = ws / ".photos-ingest" / utils.ZONE_TABLE_ARTIFACT
    rec.write_text(held)
    prep.CONFIG["zfs"] = {"enabled": False}
    monkeypatch.chdir(ws)
    monkeypatch.setattr("builtins.input", lambda prompt="": pytest.fail("asked"))
    for phase, args in ((prep, dict(command="plan", jobs=1, download_zone_table="yes")),
                        (cal, dict(command="plan", jobs=1, accept_changes=None))):
        cap = CaptureSink()
        with use_reporter(Reporter([cap])):
            with pytest.raises(SystemExit) as e:
                phase.run(types.SimpleNamespace(**args))
        said = "\n".join(x.msg for x in cap.logs())
        assert e.value.code == 2 and utils.ZONE_TABLE_ARTIFACT in said and "cannot be read" in said, said
    assert not os.path.exists(utils.prep_plan_path(str(ws))) and server.calls == []
    assert rec.read_text() == held and os.listdir(ws / ".photos-ingest").count(utils.ZONE_TABLE_ARTIFACT) == 1
    assert console._zone_table_state(str(ws), False) is None


@pytest.mark.spec("BLD-zone_table_download", "RUL-zone_table_failure_told",
                  test="TST-zone_table-a_redirect_off_https_is_refused")
def test_a_redirect_off_https_is_refused(monkeypatch):
    """The download follows a redirect only to another HTTPS address: one to plain HTTP is refused, the plain address
    never opened; one to HTTPS is followed. An address not HTTPS is refused before anything is opened."""
    import email.message
    import urllib.request
    import urllib.response
    opened, real_opener = [], utils._https_only_opener

    def server(redirect_to):
        class Fake(urllib.request.BaseHandler):
            handler_order = 100                                    # before the library's own HTTP(S) handlers

            def _answer(self, req):
                opened.append(req.full_url)
                headers = email.message.Message()
                moved = req.full_url == utils.ZONE_TABLE_URL
                if moved:
                    headers["Location"] = redirect_to
                resp = urllib.response.addinfourl(io.BytesIO(b"" if moved else b"the archive"), headers,
                                                  req.full_url, 302 if moved else 200)
                resp.msg = "Found" if moved else "OK"
                return resp
            https_open = http_open = _answer
        return lambda: (lambda o: (o.add_handler(Fake()), o)[1])(real_opener())

    monkeypatch.setattr(utils, "_https_only_opener", server("http://mirror.example/tzdata-latest.tar.gz"))
    with pytest.raises(Exception, match="not HTTPS"):
        _REAL_DOWNLOAD(utils.ZONE_TABLE_URL, 5)
    assert opened == [utils.ZONE_TABLE_URL]                        # the plain address never opened

    opened.clear()
    monkeypatch.setattr(utils, "_https_only_opener", server("https://mirror.example/tzdata-latest.tar.gz"))
    assert _REAL_DOWNLOAD(utils.ZONE_TABLE_URL, 5) == b"the archive"
    assert opened == [utils.ZONE_TABLE_URL, "https://mirror.example/tzdata-latest.tar.gz"]

    opened.clear()
    with pytest.raises(ValueError, match="not an HTTPS address"):
        _REAL_DOWNLOAD("http://data.iana.org/time-zones/tzdata-latest.tar.gz", 5)
    assert opened == []
