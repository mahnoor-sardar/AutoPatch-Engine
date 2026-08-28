from app.services.patcher import LlmNotConfigured, generate_patch
from app.services.providers import (
    E2BSandboxProvider,
    apply_disk_quota,
    apply_egress_filter,
    sandbox_network_policy,
)
from e2b.sandbox.network import ALL_TRAFFIC


def test_generate_patch_requires_api_key(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "llm_api_key", "")
    try:
        generate_patch(
            path="a.py",
            source="x=1",
            test_source="def test(): pass",
            stderr="boom",
            exception_type="ValueError",
        )
    except LlmNotConfigured:
        return
    raise AssertionError("expected LlmNotConfigured")


def test_network_policy_denies_all_by_default():
    policy = sandbox_network_policy()
    assert ALL_TRAFFIC in policy["deny_out"]
    assert "github.com" in policy["allow_out"]
    assert "pypi.org" in policy["allow_out"]


def test_apply_egress_filter_runs_as_root():
    seen = {}

    class Session:
        def run(self, command, timeout=30, user=None):
            seen["user"] = user
            seen["command"] = command
            return None

    apply_egress_filter(Session())
    assert seen["user"] == "root"
    assert "OUTPUT DROP" in seen["command"]
    assert "--dport 443 -j ACCEPT" not in seen["command"]


def test_apply_disk_quota_runs_as_root():
    seen = {}

    class Session:
        def run(self, command, timeout=120, user=None):
            seen["user"] = user
            seen["command"] = command
            return None

    apply_disk_quota(Session())
    assert seen["user"] == "root"
    assert "mount -o loop" in seen["command"]


def test_provider_create_uses_custom_template(monkeypatch):
    captured = {}

    class FakeSandbox:
        sandbox_id = "sbx-template"
        files = type("F", (), {"write": staticmethod(lambda *a, **k: None), "read": staticmethod(lambda p: "")})()
        commands = type("C", (), {"run": staticmethod(lambda *a, **k: None)})()

        def kill(self):
            return None

    def fake_create(**kwargs):
        captured.update(kwargs)
        return FakeSandbox()

    monkeypatch.setattr("app.services.providers.Sandbox.create", fake_create)
    monkeypatch.setattr("app.services.providers.apply_egress_filter", lambda session: None)
    monkeypatch.setattr("app.services.providers.apply_disk_quota", lambda session: None)
    from app.config import settings

    monkeypatch.setattr(settings, "e2b_template", "autopatch-sandbox")
    monkeypatch.setattr(settings, "e2b_api_key", "test-key")
    session = E2BSandboxProvider().create()
    assert captured["template"] == "autopatch-sandbox"
    assert session.sandbox_id == "sbx-template"


def test_provider_create_requires_template(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "e2b_template", "  ")
    try:
        E2BSandboxProvider().create()
    except RuntimeError as exc:
        assert "E2B_TEMPLATE" in str(exc)
        return
    raise AssertionError("expected RuntimeError")
