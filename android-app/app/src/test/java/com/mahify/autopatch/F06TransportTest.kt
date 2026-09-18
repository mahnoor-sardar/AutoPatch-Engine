package com.mahify.autopatch

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

class F06TransportTest {
    private fun repoFile(vararg parts: String): File {
        val moduleRoot = File(".").canonicalFile
        return File(moduleRoot, parts.joinToString(File.separator))
    }

    @Test
    fun manifestDoesNotEnableAppWideCleartext() {
        val manifest = repoFile("src", "main", "AndroidManifest.xml").readText()
        assertFalse(manifest.contains("usesCleartextTraffic"))
        assertTrue(
            manifest.contains("android:networkSecurityConfig=\"@xml/network_security_config\"")
        )
    }

    @Test
    fun mainNetworkConfigForbidsCleartext() {
        val xml = repoFile(
            "src",
            "main",
            "res",
            "xml",
            "network_security_config.xml"
        ).readText()
        assertTrue(xml.contains("cleartextTrafficPermitted=\"false\""))
        assertFalse(xml.contains("<domain-config"))
    }

    @Test
    fun debugNetworkConfigAllowsOnlyLoopbackCleartext() {
        val xml = repoFile(
            "src",
            "debug",
            "res",
            "xml",
            "network_security_config.xml"
        ).readText()
        assertTrue(xml.contains("cleartextTrafficPermitted=\"false\""))
        assertTrue(xml.contains(">localhost<"))
        assertTrue(xml.contains(">127.0.0.1<"))
        assertFalse(xml.contains("cleartextTrafficPermitted=\"true\">\n        <domain includeSubdomains=\"true\""))
    }

    @Test
    fun releaseGradleDoesNotUseDebugPropertyNamesForSecrets() {
        val gradle = repoFile("build.gradle.kts").readText()
        assertTrue(gradle.contains("AUTOPATCH_RELEASE_API_KEY"))
        assertTrue(gradle.contains("AUTOPATCH_RELEASE_DEVICE_ENROLLMENT_SECRET"))
        assertTrue(gradle.contains("requireReleaseClientSecrets"))
        assertTrue(gradle.contains("javaStringLiteral(releaseApiKey)"))
        assertTrue(gradle.contains("javaStringLiteral(debugApiKey)"))
    }
}
