from types import SimpleNamespace

from app.services.github_pr import create_pull_request
from app.services.harness import _repro_command
from app.services.providers import (
    _EGRESS_RESOLVE_HOSTS,
    apply_egress_filter,
    pin_github_ipv4_hosts,
    refresh_egress_allowlist,
    _egress_filter_script,
)


def test_create_pull_request_posts_github_api(monkeypatch):
    captured = {}

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"html_url": "https://github.com/a/b/pull/1"}

    class FakeClient:
        def __init__(self, timeout=30):
            captured["timeout"] = timeout

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, headers=None, json=None):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return FakeResponse()

    monkeypatch.setattr("app.services.github_pr.httpx.Client", FakeClient)
    result = create_pull_request(
        token="t",
        repo="a/b",
        title="fix",
        body="body",
        head="autopatch/run-1",
        base="main",
    )
    assert result["html_url"].endswith("/pull/1")
    assert captured["url"] == "https://api.github.com/repos/a/b/pulls"
    assert captured["json"]["head"] == "autopatch/run-1"
    assert captured["headers"]["Authorization"] == "Bearer t"


def test_egress_script_is_fail_closed():
    script = _egress_filter_script()
    assert "OUTPUT DROP" in script
    assert "--dport 443 -j ACCEPT" not in script
    assert "--dport 80 -j ACCEPT" not in script
    assert "github.com" in script
    assert "pypi.org" in script
    assert "registry.npmjs.org" in script
    for host in _EGRESS_RESOLVE_HOSTS:
        assert host in script


def test_refresh_egress_allowlist_reuses_fail_closed_script():
    seen = {}

    class Session:
        def run(self, command, timeout=30, user=None):
            seen["command"] = command
            seen["user"] = user
            seen["timeout"] = timeout

    refresh_egress_allowlist(Session())
    apply_cmd = {}

    class ApplySession:
        def run(self, command, timeout=30, user=None):
            apply_cmd["command"] = command
            apply_cmd["user"] = user

    apply_egress_filter(ApplySession())
    assert seen["user"] == "root"
    assert apply_cmd["user"] == "root"
    assert seen["command"] == apply_cmd["command"]
    assert seen["command"] == _egress_filter_script()
    assert "OUTPUT DROP" in seen["command"]
    assert "--dport 443 -j ACCEPT" not in seen["command"]
    assert "--dport 80 -j ACCEPT" not in seen["command"]
    for host in _EGRESS_RESOLVE_HOSTS:
        assert host in seen["command"]


def test_github_ipv4_snapshot_used_for_iptables_and_hosts():
    script = _egress_filter_script()
    assert script.count("getent ahosts github.com") == 1
    assert "GITHUB_V4=" in script
    assert '"$IPTABLES" -A OUTPUT -d "$ip" -j ACCEPT' in script
    assert "printf '%s github.com\\n' \"$ip\"" in script or 'printf \'%s github.com\\n\' "$ip"' in script
    assert "BEGIN autopatch-github-ipv4-pin" in script
    assert r'sed -i "\|$BEGIN|,\\|$END|d"' in script or 'sed -i "\\|$BEGIN|,\\|$END|d"' in script
    assert "OUTPUT DROP" in script
    assert "--dport 443" not in script
    assert "--dport 80" not in script
    assert "GIT_SSL_NO_VERIFY" not in script
    github_getent = script.find("getent ahosts github.com")
    iptables_github = script.find('for ip in $GITHUB_V4')
    hosts_pin = script.find("BEGIN autopatch-github-ipv4-pin")
    assert github_getent != -1
    assert iptables_github > github_getent
    assert hosts_pin > github_getent


def test_egress_script_fail_closes_ipv6_without_github_v6_path():
    script = _egress_filter_script()
    ipv4 = script[: script.find("IP6TABLES=")]
    ipv6 = script[script.find("IP6TABLES=") :]
    assert "IP6TABLES=" in script
    assert "ip6tables is required for sandbox IPv6 egress filtering" in script
    assert '"$IP6TABLES" -P OUTPUT DROP' in script
    assert '"$IP6TABLES" -A OUTPUT -o lo -j ACCEPT' in script
    assert '"$IP6TABLES" -A OUTPUT -p udp --dport 53 -j ACCEPT' in script
    assert '"$IP6TABLES" -A OUTPUT -p tcp --dport 53 -j ACCEPT' in script
    assert "--dport 443 -j ACCEPT" not in script
    assert "--dport 80 -j ACCEPT" not in script
    assert "GITHUB_V6" not in script
    assert "GITHUB_V4=" in ipv4
    assert '"$IPTABLES" -P OUTPUT DROP' in ipv4
    assert "BEGIN autopatch-github-ipv4-pin" in ipv4
    assert "github.com" in ipv6
    github_skip = 'if [ "$host" = github.com ]; then'
    assert ipv6.count(github_skip) == 1
    assert '"$IP6TABLES" -A OUTPUT -d "$ip" -j ACCEPT' in ipv6
    assert script.find("IP6TABLES=") > script.find("BEGIN autopatch-github-ipv4-pin")


def test_template_requires_ip6tables_binary():
    import inspect

    from app.services.e2b_template import TEMPLATE_PACKAGES, build_autopatch_template

    assert "iptables" in TEMPLATE_PACKAGES
    source = inspect.getsource(build_autopatch_template)
    assert "command -v ip6tables" in source
    assert "ip6tables --version" in source


def test_pin_github_ipv4_hosts_uses_combined_refresh():
    seen = {}

    class Session:
        def run(self, command, timeout=30, user=None):
            seen["command"] = command
            seen["user"] = user

    pin_github_ipv4_hosts(Session())
    assert seen["user"] == "root"
    assert seen["command"] == _egress_filter_script()
    assert seen["command"].count("getent ahosts github.com") == 1


def test_apply_egress_filter_does_not_swallow_errors():
    class Boom:
        def run(self, command, timeout=30, **kwargs):
            raise RuntimeError("iptables missing")

    try:
        apply_egress_filter(Boom())
    except RuntimeError as exc:
        assert "iptables" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_js_repro_uses_node_test_runner():
    assert "node --test" in _repro_command("tests/autopatch_repro.test.mjs")
    assert "tsx --test" in _repro_command("tests/autopatch_repro.test.ts")


def test_install_prefers_root_requirements():
    from app.services.e2b_runner import install_project_dependencies

    seen = []

    class Session:
        sandbox_id = "x"

        def run(self, command, timeout=30, user=None):
            seen.append(command)
            if "test -e" in command:
                if "/home/user/repo/requirements.txt" in command and "backend" not in command:
                    return SimpleNamespace(stdout="0\n")
                return SimpleNamespace(stdout="1\n")
            return SimpleNamespace(stdout="ok", stderr="")

        def kill(self):
            return None

    code, _out, _err = install_project_dependencies(Session())
    assert code == 0
    assert any("pip install -r requirements.txt" in cmd for cmd in seen)
    assert not any("backend && python -m pip" in cmd for cmd in seen)


def test_install_refreshes_egress_allowlist_before_pip(monkeypatch):
    order = []

    monkeypatch.setattr(
        "app.services.e2b_runner.refresh_egress_allowlist",
        lambda session: order.append("refresh"),
    )

    class Session:
        sandbox_id = "x"

        def run(self, command, timeout=30, user=None):
            if "pip install" in command:
                order.append("pip")
            if "test -e" in command:
                if "/home/user/repo/requirements.txt" in command and "backend" not in command:
                    return SimpleNamespace(stdout="0\n")
                return SimpleNamespace(stdout="1\n")
            return SimpleNamespace(stdout="ok", stderr="")

        def kill(self):
            return None

    from app.services.e2b_runner import install_project_dependencies

    code, _out, _err = install_project_dependencies(Session())
    assert code == 0
    assert order[0] == "refresh"
    assert "pip" in order
    assert order.index("refresh") < order.index("pip")
