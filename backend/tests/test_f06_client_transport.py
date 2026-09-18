from pathlib import Path
import re

REPO = Path(__file__).resolve().parents[2]
ANDROID_APP = REPO / "android-app" / "app"
WEB_CONFIG = REPO / "web" / "lib" / "config.ts"


def test_android_manifest_does_not_enable_app_wide_cleartext():
    manifest = (ANDROID_APP / "src/main/AndroidManifest.xml").read_text(
        encoding="utf-8"
    )
    assert "usesCleartextTraffic" not in manifest
    assert 'android:networkSecurityConfig="@xml/network_security_config"' in manifest


def test_release_network_config_forbids_cleartext():
    xml = (
        ANDROID_APP / "src/main/res/xml/network_security_config.xml"
    ).read_text(encoding="utf-8")
    assert 'cleartextTrafficPermitted="false"' in xml
    assert "domain-config" not in xml


def test_debug_network_config_allows_only_loopback_cleartext():
    xml = (
        ANDROID_APP / "src/debug/res/xml/network_security_config.xml"
    ).read_text(encoding="utf-8")
    assert 'cleartextTrafficPermitted="false"' in xml
    assert "<domain includeSubdomains=\"false\">localhost</domain>" in xml
    assert "<domain includeSubdomains=\"false\">127.0.0.1</domain>" in xml
    assert xml.count("<domain ") == 3
    assert "0.0.0.0" not in xml


def test_release_gradle_refuses_development_client_secrets():
    gradle = (ANDROID_APP / "build.gradle.kts").read_text(encoding="utf-8")
    assert "AUTOPATCH_RELEASE_API_KEY" in gradle
    assert "AUTOPATCH_RELEASE_DEVICE_ENROLLMENT_SECRET" in gradle
    assert "requireReleaseClientSecrets" in gradle
    assert "dev-local-key" in gradle
    assert "dev-enrollment-secret" in gradle
    assert "assemble" in gradle
    debug_block = re.search(
        r"debug\s*\{.*?AUTOPATCH_API_KEY.*?debugApiKey.*?\n\s*\}",
        gradle,
        re.S,
    )
    release_block = re.search(
        r"release\s*\{.*?AUTOPATCH_RELEASE_API_KEY|releaseApiKey",
        gradle,
        re.S,
    )
    assert debug_block or "debugApiKey" in gradle
    assert release_block or "releaseApiKey" in gradle
    assert "javaStringLiteral(debugApiKey)" in gradle
    assert "javaStringLiteral(releaseApiKey)" in gradle
    assert "javaStringLiteral(debugEnrollmentSecret)" in gradle
    assert "javaStringLiteral(releaseEnrollmentSecret)" in gradle


def test_ws_url_has_no_credential_query_parameters():
    source = WEB_CONFIG.read_text(encoding="utf-8")
    assert "function wsUrl()" in source
    assert "/v1/ws/runs" in source
    assert "api_key" not in source
    assert "API_KEY" not in source
    assert "?" not in source.split("function wsUrl()")[1].split("}")[0]
