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

"""ssh_tunnel_hint — the copy-paste `ssh -L` line the console/editor print when bound to loopback."""
import pytest

import photos_utils as utils


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("SSH_CONNECTION", raising=False)
    monkeypatch.setenv("USER", "alice")


@pytest.mark.parametrize("host", ["0.0.0.0", "", "::", "192.168.1.10", "example.com"])
def test_no_hint_when_not_loopback(host):
    # Directly reachable -> no tunnel needed -> no hint.
    assert utils.ssh_tunnel_hint(8766, host) is None


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1"])
def test_hint_for_each_loopback_form(host, monkeypatch):
    monkeypatch.setattr(utils.socket, "gethostname", lambda: "zeus")
    assert utils.ssh_tunnel_hint(8766, host) == "ssh -L 8766:127.0.0.1:8766 alice@zeus"


def test_hint_prefers_ssh_connection_server_address(monkeypatch):
    # SSH_CONNECTION = "<client_ip> <client_port> <server_ip> <server_port>"; field 3 is the address
    # the client used to reach us — the host the client should ssh back to (its own keys/config apply).
    monkeypatch.setenv("SSH_CONNECTION", "10.0.0.5 51000 192.168.1.20 22")
    assert utils.ssh_tunnel_hint(8765, "127.0.0.1") == "ssh -L 8765:127.0.0.1:8765 alice@192.168.1.20"


def test_hint_falls_back_to_hostname_without_ssh(monkeypatch):
    monkeypatch.setattr(utils.socket, "gethostname", lambda: "myhost")
    assert utils.ssh_tunnel_hint(9000, "127.0.0.1") == "ssh -L 9000:127.0.0.1:9000 alice@myhost"


def test_hint_uses_the_bound_port_passed_in(monkeypatch):
    # Caller passes the ACTUAL bound port (which may differ from the requested one if it was busy).
    monkeypatch.setattr(utils.socket, "gethostname", lambda: "h")
    assert utils.ssh_tunnel_hint(8770, "127.0.0.1") == "ssh -L 8770:127.0.0.1:8770 alice@h"
