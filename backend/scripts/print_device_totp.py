"""DEV/TEST only: print TOTP setup for registered devices.

Usage (from backend/, venv active):

    python scripts/print_device_totp.py
    python scripts/print_device_totp.py DEVICE_ID

Do not commit output. Do not run against production.
"""

from __future__ import annotations

import sys

from app.db import SessionLocal
from app.models import Device
from app.services import totp


def main(argv: list[str]) -> int:
    if not totp.totp_setup_enabled():
        print(
            "Refusing to print TOTP setup: APP_ENV is not a development value.",
            file=sys.stderr,
        )
        return 2

    wanted = argv[1] if len(argv) > 1 else None
    db = SessionLocal()
    try:
        query = db.query(Device).order_by(Device.id)
        if wanted:
            query = query.filter(Device.device_id == wanted)
        devices = query.all()
        if not devices:
            print("No matching registered device.", file=sys.stderr)
            return 1
        for device in devices:
            if not device.totp_secret:
                print(f"{device.device_id}\t(no totp secret)")
                continue
            uri = totp.provisioning_uri(device.totp_secret, device.device_id)
            print(f"device_id\t{device.device_id}")
            print(f"otpauth_url\t{uri}")
            print(f"secret\t{device.totp_secret}")
            print("---")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
