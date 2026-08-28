package com.mahify.autopatch

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class TotpTest {
    @Test
    fun currentCode_isSixDigits() {
        val code = Totp.currentCode("JBSWY3DPEHPK3PXP")
        assertEquals(6, code.length)
        assertTrue(code.all { it.isDigit() })
    }

    @Test
    fun verify_acceptsCurrentCodeAndRejectsWrong() {
        val secret = "JBSWY3DPEHPK3PXP"
        val now = 1_700_000_000_000L
        val code = Totp.currentCode(secret, now)
        assertTrue(Totp.verify(secret, code, now))
        assertTrue(Totp.verify(secret, Totp.currentCode(secret, now - 30_000L), now))
        assertFalse(Totp.verify(secret, "000000", now))
        assertFalse(Totp.verify(secret, "", now))
        assertFalse(Totp.verify("", code, now))
    }

    @Test
    fun approvalToken_isHex() {
        val token = Totp.approvalToken("secret", "dev|1|sandbox_provision", 100L)
        assertEquals(64, token.length)
        assertTrue(token.matches(Regex("[0-9a-f]+")))
    }

    @Test
    fun diffParser_colorsAdditionsAndDeletions() {
        val lines = DiffParser.parse(
            "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-old\n+new\n"
        )
        assertEquals(DiffLineKind.META, lines[0].kind)
        assertEquals(DiffLineKind.HUNK, lines[3].kind)
        assertEquals(DiffLineKind.DEL, lines[4].kind)
        assertEquals(DiffLineKind.ADD, lines[5].kind)
    }
}
