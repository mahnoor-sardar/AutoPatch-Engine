from abc import ABC, abstractmethod
import os
from typing import Any

from e2b import Sandbox
from e2b.sandbox.network import ALL_TRAFFIC

from app.config import settings


def e2b_api_key() -> str:
    """Same source of truth as Sandbox.create: settings, then process env."""
    return (
        (settings.e2b_api_key or "").strip()
        or (os.environ.get("E2B_API_KEY") or "").strip()
    )


def e2b_auth_kwargs() -> dict[str, str]:
    key = e2b_api_key()
    if not key:
        return {}
    return {"api_key": key}

COMMAND_TIMEOUT = 120
SANDBOX_TIMEOUT = 15 * 60
DISK_LIMIT_BYTES = 500 * 1024 * 1024

ALLOWED_EGRESS_HOSTS = [
    "github.com",
    "*.github.com",
    "*.githubusercontent.com",
    "pypi.org",
    "files.pythonhosted.org",
    "pypi.python.org",
    "registry.npmjs.org",
    "*.npmjs.org",
    "npmjs.com",
]

_EGRESS_RESOLVE_HOSTS = [
    "github.com",
    "api.github.com",
    "codeload.github.com",
    "pypi.org",
    "files.pythonhosted.org",
    "registry.npmjs.org",
    "npmjs.com",
]


def sandbox_network_policy() -> dict:
    return {
        "allow_out": list(ALLOWED_EGRESS_HOSTS),
        "deny_out": [ALL_TRAFFIC],
    }


def _egress_filter_script() -> str:
    hosts = " ".join(_EGRESS_RESOLVE_HOSTS)
    return f"""
set -euo pipefail
IPTABLES=/usr/sbin/iptables
if [ ! -x "$IPTABLES" ]; then
  IPTABLES="$(command -v iptables || true)"
fi
if [ -z "$IPTABLES" ]; then
  echo "iptables is required for sandbox egress filtering" >&2
  exit 1
fi
"$IPTABLES" -F OUTPUT
"$IPTABLES" -P OUTPUT DROP
"$IPTABLES" -A OUTPUT -o lo -j ACCEPT
"$IPTABLES" -A OUTPUT -p udp --dport 53 -j ACCEPT
"$IPTABLES" -A OUTPUT -p tcp --dport 53 -j ACCEPT
if "$IPTABLES" -A OUTPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT; then
  true
else
  "$IPTABLES" -A OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT
fi
GITHUB_V4="$(
  getent ahosts github.com 2>/dev/null | awk '{{print $1}}' | sort -u | while read -r ip; do
    case "$ip" in
      *:*) ;;
      '') ;;
      *) printf '%s\\n' "$ip" ;;
    esac
  done
)"
if [ -n "$GITHUB_V4" ]; then
  for ip in $GITHUB_V4; do
    "$IPTABLES" -A OUTPUT -d "$ip" -j ACCEPT
  done
fi
for host in {hosts}; do
  if [ "$host" = github.com ]; then
    continue
  fi
  getent ahosts "$host" 2>/dev/null | awk '{{print $1}}' | sort -u | while read -r ip; do
    case "$ip" in
      *:* ) "$IPTABLES" -A OUTPUT -d "$ip" -j ACCEPT 2>/dev/null || true ;;
      * ) "$IPTABLES" -A OUTPUT -d "$ip" -j ACCEPT ;;
    esac
  done
done
HOSTS=/etc/hosts
BEGIN='# BEGIN autopatch-github-ipv4-pin'
END='# END autopatch-github-ipv4-pin'
if grep -qF "$BEGIN" "$HOSTS" 2>/dev/null; then
  sed -i "\\|$BEGIN|,\\|$END|d" "$HOSTS"
fi
if [ -n "$GITHUB_V4" ]; then
  {{
    printf '%s\\n' "$BEGIN"
    for ip in $GITHUB_V4; do
      printf '%s github.com\\n' "$ip"
    done
    printf '%s\\n' "$END"
  }} >> "$HOSTS"
fi
IP6TABLES=/usr/sbin/ip6tables
if [ ! -x "$IP6TABLES" ]; then
  IP6TABLES="$(command -v ip6tables || true)"
fi
if [ -z "$IP6TABLES" ]; then
  echo "ip6tables is required for sandbox IPv6 egress filtering" >&2
  exit 1
fi
"$IP6TABLES" -F OUTPUT
"$IP6TABLES" -P OUTPUT DROP
"$IP6TABLES" -A OUTPUT -o lo -j ACCEPT
"$IP6TABLES" -A OUTPUT -p udp --dport 53 -j ACCEPT
"$IP6TABLES" -A OUTPUT -p tcp --dport 53 -j ACCEPT
if "$IP6TABLES" -A OUTPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT; then
  true
else
  "$IP6TABLES" -A OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT
fi
for host in {hosts}; do
  if [ "$host" = github.com ]; then
    continue
  fi
  getent ahosts "$host" 2>/dev/null | awk '{{print $1}}' | sort -u | while read -r ip; do
    case "$ip" in
      *:*) "$IP6TABLES" -A OUTPUT -d "$ip" -j ACCEPT ;;
    esac
  done
done
"""


PRIVILEGED_USER = "root"


def refresh_egress_allowlist(session: "SandboxSession") -> None:
    """Rebuild IPv4/IPv6 OUTPUT DROP + dest ACCEPTs; pin github.com to IPv4 only."""
    session.run(_egress_filter_script(), timeout=COMMAND_TIMEOUT, user=PRIVILEGED_USER)


def apply_egress_filter(session: "SandboxSession") -> None:
    refresh_egress_allowlist(session)


def pin_github_ipv4_hosts(session: "SandboxSession") -> None:
    """Same snapshot as iptables; URL host stays github.com."""
    refresh_egress_allowlist(session)


def disk_quota_script() -> str:
    mb = DISK_LIMIT_BYTES // (1024 * 1024)
    return f"""
set -euo pipefail
IMG=/opt/autopatch-workspace.img
MNT=/home/user
APP_USER=user
if [ "$(id -u)" -ne 0 ]; then
  echo "root is required to enforce the {mb}MB sandbox disk quota" >&2
  exit 1
fi
prepare_user_workspace() {{
  chown "$APP_USER:$APP_USER" "$MNT"
  mkdir -p "$MNT/repo"
  chown "$APP_USER:$APP_USER" "$MNT/repo"
  chmod 755 "$MNT" "$MNT/repo"
}}
if losetup -a 2>/dev/null | grep -q "autopatch-workspace.img"; then
  prepare_user_workspace
  exit 0
fi
if [ -e "$IMG" ] && losetup -j "$IMG" 2>/dev/null | grep -q .; then
  prepare_user_workspace
  exit 0
fi
mkdir -p /opt
if command -v fallocate >/dev/null 2>&1; then
  fallocate -l {mb}M "$IMG"
else
  dd if=/dev/zero of="$IMG" bs=1M count={mb} status=none
fi
if command -v mkfs.ext4 >/dev/null 2>&1; then
  mkfs.ext4 -F -q "$IMG"
elif command -v mkfs.ext2 >/dev/null 2>&1; then
  mkfs.ext2 -F -q "$IMG"
else
  echo "mkfs is required to enforce the {mb}MB sandbox disk quota" >&2
  exit 1
fi
mkdir -p "$MNT"
mount -o loop,rw,nosuid,nodev "$IMG" "$MNT"
prepare_user_workspace
"""


def apply_disk_quota(session: "SandboxSession") -> None:
    session.run(disk_quota_script(), timeout=COMMAND_TIMEOUT, user=PRIVILEGED_USER)


class SandboxSession(ABC):
    sandbox_id: str

    @abstractmethod
    def run(
        self,
        command: str,
        timeout: int = COMMAND_TIMEOUT,
        user: str | None = None,
    ) -> Any:
        raise NotImplementedError

    @abstractmethod
    def write_file(self, path: str, content: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def kill(self) -> None:
        raise NotImplementedError


class E2BSession(SandboxSession):
    def __init__(self, sandbox: Sandbox):
        self._sandbox = sandbox
        self.sandbox_id = sandbox.sandbox_id
        self._bytes_written = 0

    def run(
        self,
        command: str,
        timeout: int = COMMAND_TIMEOUT,
        user: str | None = None,
    ) -> Any:
        kwargs: dict[str, Any] = {"timeout": timeout}
        if user is not None:
            kwargs["user"] = user
        if hasattr(self._sandbox, "commands") and self._sandbox.commands is not None:
            return self._sandbox.commands.run(command, **kwargs)
        return self._sandbox.run(command, **kwargs)

    def write_file(self, path: str, content: str) -> None:
        payload = (
            content.encode("utf-8") if isinstance(content, str) else bytes(content)
        )
        next_total = self._bytes_written + len(payload)
        if len(payload) > DISK_LIMIT_BYTES or next_total > DISK_LIMIT_BYTES:
            raise RuntimeError(
                f"sandbox disk write limit exceeded: {next_total} bytes"
            )
        if hasattr(self._sandbox, "write_file"):
            self._sandbox.write_file(path, content)
        else:
            self._sandbox.files.write(path, content)
        self._bytes_written = next_total

    def read_file(self, path: str) -> str:
        if hasattr(self._sandbox, "read_file"):
            return self._sandbox.read_file(path)
        return self._sandbox.files.read(path)

    def kill(self) -> None:
        self._sandbox.kill()

    @property
    def raw(self) -> Sandbox:
        return self._sandbox

    @property
    def files(self):
        return _QuotaFiles(self)

    @property
    def commands(self):
        if hasattr(self._sandbox, "commands") and self._sandbox.commands is not None:
            return self._sandbox.commands
        return _SessionCommands(self)


class _QuotaFiles:
    def __init__(self, session: "E2BSession"):
        self._session = session

    def write(self, path: str, content: str) -> None:
        self._session.write_file(path, content)

    def read(self, path: str) -> str:
        return self._session.read_file(path)


class _SessionCommands:
    def __init__(self, session: "E2BSession"):
        self._session = session

    def run(
        self,
        command: str,
        timeout: int = COMMAND_TIMEOUT,
        user: str | None = None,
    ) -> Any:
        return self._session.run(command, timeout=timeout, user=user)


class SandboxProvider(ABC):
    @abstractmethod
    def create(self) -> SandboxSession:
        raise NotImplementedError

    @abstractmethod
    def kill(self, sandbox_id: str) -> None:
        raise NotImplementedError


class E2BSandboxProvider(SandboxProvider):
    def create(self) -> SandboxSession:
        template = (settings.e2b_template or "").strip()
        if not template:
            raise RuntimeError(
                "E2B_TEMPLATE is required; the default sandbox image "
                "cannot enforce fail-closed egress filtering"
            )
        kwargs: dict = {
            "template": template,
            "timeout": SANDBOX_TIMEOUT,
            "network": sandbox_network_policy(),
            "allow_internet_access": True,
            **e2b_auth_kwargs(),
        }
        sandbox = Sandbox.create(**kwargs)
        session = E2BSession(sandbox)
        try:
            apply_egress_filter(session)
            apply_disk_quota(session)
        except Exception:
            session.kill()
            raise
        return session

    def kill(self, sandbox_id: str) -> None:
        auth = e2b_auth_kwargs()
        connect = getattr(Sandbox, "connect", None)
        if connect is not None:
            connect(sandbox_id, **auth).kill()
            return
        Sandbox(sandbox_id, **auth).kill()


def wrap_raw_sandbox(sandbox: Sandbox) -> E2BSession:
    return E2BSession(sandbox)


_provider: SandboxProvider | None = None


def get_sandbox_provider() -> SandboxProvider:
    global _provider
    if _provider is None:
        _provider = E2BSandboxProvider()
    return _provider
