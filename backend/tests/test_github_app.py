import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.services import github_app


def test_make_app_jwt(monkeypatch):
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )

    monkeypatch.setattr(github_app.settings, "github_app_id", "123456")
    monkeypatch.setattr(
        github_app,
        "_private_key",
        lambda: pem.decode("utf-8"),
    )

    token = github_app.make_app_jwt()

    header = jwt.get_unverified_header(token)
    claims = jwt.decode(token, options={"verify_signature": False})

    assert header["alg"] == "RS256"
    assert claims["iss"] == "123456"
    assert "iat" in claims
    assert "exp" in claims