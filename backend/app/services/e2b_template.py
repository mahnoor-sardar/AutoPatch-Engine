"""E2B custom template used by AutoPatch sandboxes.

The default E2B base image is Debian 12 but does not include iptables.
Security packages are installed at *template build* time as root via the
SDK apt_install() helper. Runtime sandboxes still default to `user`;
egress and disk-quota scripts run as root through commands.run(user="root").
"""

from e2b import Template

TEMPLATE_NAME = "autopatch-sandbox"

# Runtime apply_disk_quota() mounts a fresh ext4 image over /home/user.
# That filesystem is created empty and owned by root, so the template
# cannot pre-seed a writable /home/user/repo. Ownership is restored
# for uid `user` at the end of the privileged quota script.
TEMPLATE_PACKAGES = [
    "iptables",
    "e2fsprogs",
    "util-linux",
    "iproute2",
    "kmod",
    "ca-certificates",
]


def build_autopatch_template():
    return (
        Template()
        .from_base_image()
        .apt_install(TEMPLATE_PACKAGES)
        .run_cmd(
            "command -v iptables && iptables --version && "
            "(command -v mkfs.ext4 || command -v mkfs.ext2) && "
            "command -v mount && command -v git && command -v python3",
            user="root",
        )
        .set_user("user")
        .set_workdir("/home/user")
    )
