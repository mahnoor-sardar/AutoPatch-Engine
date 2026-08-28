from types import SimpleNamespace

from app.services.github_pr import create_pull_request
from app.services.harness import _repro_command
from app.services.providers import apply_egress_filter, _egress_filter_script


def test_create_pull_request_posts_github_api(monkeypatch):
    captured = {}

    class FakeResponse:
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

        def run(self, command, timeout=30):
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
