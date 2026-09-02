from app.services.patcher import LlmNotConfigured, generate_patch
from app.services.providers import (
    COMMAND_TIMEOUT,
    DISK_LIMIT_BYTES,
    SANDBOX_TIMEOUT,
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


def test_generate_patch_return_one_over_zero_is_git_applicable(monkeypatch, tmp_path):
    import subprocess
    from types import SimpleNamespace

    from app.config import settings

    # Exact run #507 attempt-1 payload: last hunk line has no terminating newline.
    llm_content = (
        "--- a/backend/tests/fixtures/autopatch_phase34.py\n"
        "+++ b/backend/tests/fixtures/autopatch_phase34.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def reproduce_failure():\n"
        "-    return 1 / 0\n"
        "+    return 1"
    )
    assert not llm_content.endswith("\n")

    monkeypatch.setattr(settings, "llm_api_key", "test-key")

    def fake_completion(**kwargs):
        return SimpleNamespace(
            choices=[
                SimpleNamespace(message=SimpleNamespace(content=llm_content))
            ]
        )

    monkeypatch.setattr("litellm.completion", fake_completion)
    diff = generate_patch(
        path="backend/tests/fixtures/autopatch_phase34.py",
        source="def reproduce_failure():\n    return 1 / 0\n",
        test_source="def test(): pass",
        stderr="ZeroDivisionError",
        exception_type="ZeroDivisionError",
    )
    assert diff.diff.endswith("\n")
    assert "+    return 1\n" in diff.diff
    assert diff.diff.splitlines()[-1] == "+    return 1"
    assert diff.tokens_used is None

    repo = tmp_path / "repo"
    target = repo / "backend" / "tests" / "fixtures" / "autopatch_phase34.py"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"def reproduce_failure():\n    return 1 / 0\n")
    patch_file = tmp_path / "autopatch.diff"
    patch_file.write_bytes(diff.diff.encode("utf-8"))
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    applied = subprocess.run(
        ["git", "apply", str(patch_file)],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    assert applied.returncode == 0, applied.stderr
    assert target.read_text(encoding="utf-8") == (
        "def reproduce_failure():\n    return 1\n"
    )


def test_generate_patch_routes_gemini_model_to_gemini_api_not_vertex(monkeypatch):
    from types import SimpleNamespace

    from app.config import settings
    from litellm.litellm_core_utils.get_llm_provider_logic import get_llm_provider

    monkeypatch.setattr(settings, "llm_api_key", "test-key")
    monkeypatch.setattr(settings, "llm_model", "gemini-3.7-flash")
    monkeypatch.setattr(
        settings,
        "llm_api_base",
        "https://generativelanguage.googleapis.com/v1beta/openai/",
    )
    seen = []

    def fake_completion(**kwargs):
        seen.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n"
                    )
                )
            ]
        )

    monkeypatch.setattr("litellm.completion", fake_completion)
    generate_patch(
        path="a.py",
        source="x=1",
        test_source="def test(): pass",
        stderr="boom",
        exception_type="ValueError",
    )
    assert seen
    kwargs = seen[0]
    assert kwargs["model"] == "gemini/gemini-3.7-flash"
    assert kwargs["api_key"] == "test-key"
    assert kwargs["timeout"] == settings.llm_timeout_seconds
    assert "api_base" not in kwargs
    _model, provider, _key, _api_base = get_llm_provider(
        model=kwargs["model"],
        api_key="dummy",
    )
    assert provider == "gemini"
    assert provider != "vertex_ai"

    seen.clear()
    monkeypatch.setattr(settings, "llm_model", "gpt-4o")
    generate_patch(
        path="a.py",
        source="x=1",
        test_source="def test(): pass",
        stderr="boom",
        exception_type="ValueError",
    )
    assert seen
    assert seen[0]["model"] == "gpt-4o"
    assert seen[0]["timeout"] == settings.llm_timeout_seconds
    assert seen[0]["api_base"] == (
        "https://generativelanguage.googleapis.com/v1beta/openai/"
    )


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
    assert '"$IPTABLES" -P OUTPUT DROP' in seen["command"]
    assert '"$IP6TABLES" -P OUTPUT DROP' in seen["command"]
    assert "--dport 443 -j ACCEPT" not in seen["command"]


def test_resource_limits_unchanged():
    assert COMMAND_TIMEOUT == 120
    assert SANDBOX_TIMEOUT == 15 * 60
    assert DISK_LIMIT_BYTES == 500 * 1024 * 1024


def test_clone_refreshes_egress_allowlist_before_git_clone(monkeypatch):
    order = []

    class Session:
        sandbox_id = "sbx-refresh"

        def kill(self):
            return None

    class Provider:
        def create(self):
            return Session()

    monkeypatch.setattr(
        "app.services.e2b_runner.get_sandbox_provider",
        lambda: Provider(),
    )
    monkeypatch.setattr(
        "app.services.e2b_runner.refresh_egress_allowlist",
        lambda session: order.append("refresh"),
    )

    def fake_clone(**kwargs):
        order.append("clone")
        return {}

    monkeypatch.setattr(
        "app.services.e2b_runner.clone_and_read_sources",
        fake_clone,
    )
    from app.services.e2b_runner import clone_and_read_sources_in_sandbox

    clone_and_read_sources_in_sandbox(
        "https://github.com/mahnoor-sardar/AutoPatch-Engine.git",
        "main",
        "token",
    )
    assert order == ["refresh", "clone"]


def test_create_still_applies_egress_then_quota(monkeypatch):
    steps = []

    class FakeSandbox:
        sandbox_id = "sbx-create"
        files = type(
            "F",
            (),
            {
                "write": staticmethod(lambda *a, **k: None),
                "read": staticmethod(lambda p: ""),
            },
        )()
        commands = type("C", (), {"run": staticmethod(lambda *a, **k: None)})()

        def kill(self):
            return None

    monkeypatch.setattr(
        "app.services.providers.Sandbox.create",
        lambda **kwargs: FakeSandbox(),
    )
    monkeypatch.setattr(
        "app.services.providers.apply_egress_filter",
        lambda session: steps.append("egress"),
    )
    monkeypatch.setattr(
        "app.services.providers.apply_disk_quota",
        lambda session: steps.append("quota"),
    )
    from app.config import settings

    monkeypatch.setattr(settings, "e2b_template", "autopatch-sandbox")
    monkeypatch.setattr(settings, "e2b_api_key", "test-key")
    E2BSandboxProvider().create()
    assert steps == ["egress", "quota"]


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
    assert captured["api_key"] == "test-key"
    assert session.sandbox_id == "sbx-template"


def test_provider_kill_passes_api_key_to_connect(monkeypatch):
    captured = {}

    class FakeConnected:
        def kill(self):
            captured["killed"] = True

    def fake_connect(sandbox_id, **kwargs):
        captured["sandbox_id"] = sandbox_id
        captured.update(kwargs)
        return FakeConnected()

    monkeypatch.setattr("app.services.providers.Sandbox.connect", fake_connect)
    from app.config import settings

    monkeypatch.setattr(settings, "e2b_api_key", "test-key")
    E2BSandboxProvider().kill("sbx-live")
    assert captured["sandbox_id"] == "sbx-live"
    assert captured["api_key"] == "test-key"
    assert captured["killed"] is True


def test_provider_create_requires_template(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "e2b_template", "  ")
    try:
        E2BSandboxProvider().create()
    except RuntimeError as exc:
        assert "E2B_TEMPLATE" in str(exc)
        return
    raise AssertionError("expected RuntimeError")
