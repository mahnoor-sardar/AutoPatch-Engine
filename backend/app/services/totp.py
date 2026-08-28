import pyotp

from app.config import settings

# DEV/TEST only: TOTP setup endpoints and scripts. Production must use
# APP_ENV=production (or anything outside this set) so secrets are not served.
_DEV_TOTP_SETUP_ENVS = frozenset({"local", "dev", "development", "test"})

ISSUER = "AutoPatch"


def new_secret() -> str:
    return pyotp.random_base32()


def verify_code(secret: str, otp_code: str) -> bool:
    if not secret or not otp_code:
        return False

    totp = pyotp.TOTP(secret)
    return bool(totp.verify(otp_code, valid_window=1))


def provisioning_uri(secret: str, device_id: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(
        name=device_id,
        issuer_name=ISSUER,
    )


def totp_setup_enabled() -> bool:
    return settings.app_env.lower() in _DEV_TOTP_SETUP_ENVS
