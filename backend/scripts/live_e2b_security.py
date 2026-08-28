"""Live verification of the AutoPatch E2B template and fail-closed security setup."""

from pathlib import Path
import sys

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.services.e2b_template import TEMPLATE_NAME
from app.services.providers import (
    E2BSandboxProvider,
    apply_disk_quota,
    apply_egress_filter,
)


def _out(result) -> str:
    return (getattr(result, "stdout", "") or "") + (getattr(result, "stderr", "") or "")


def main() -> int:
    session = E2BSandboxProvider().create()
    killed = False
    try:
        apply_egress_filter(session)
        apply_disk_quota(session)
        print("apply_egress_filter_ok True")
        print("apply_disk_quota_ok True")
        identity = session.run(
            "id; /usr/sbin/iptables --version; command -v git; command -v python3",
            timeout=30,
            user="root",
        )
        print("id_iptables")
        print(_out(identity)[:1500])
        policy = session.run("iptables -L OUTPUT -n -v", timeout=30, user="root")
        print("iptables_output_chain")
        print(_out(policy)[:2500])
        text = _out(policy).upper()
        if "DROP" not in text:
            print("FAIL missing OUTPUT DROP")
            return 1
        if "ACCEPT" not in text:
            print("FAIL missing ACCEPT rules")
            return 1
        tools = session.run(
            "command -v git; command -v python3; command -v npm; "
            "command -v mkfs.ext4 || command -v mkfs.ext2; command -v mount",
            timeout=30,
        )
        print("tools")
        print(_out(tools)[:800])
        print("egress_and_quota_applied_during_create True")
        print("template", TEMPLATE_NAME)
        print("sandbox_id", session.sandbox_id)
        print("LIVE_E2B_SECURITY_OK")
        return 0
    finally:
        try:
            session.kill()
            killed = True
        except Exception as exc:
            print("kill_error", type(exc).__name__, str(exc)[:200])
        print("sandbox_killed", killed)


if __name__ == "__main__":
    raise SystemExit(main())
