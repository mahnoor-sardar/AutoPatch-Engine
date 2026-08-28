package com.mahify.autopatch

import org.junit.Assert.assertTrue
import org.junit.Test
import java.net.SocketTimeoutException

class NetworkErrorsTest {
    @Test
    fun socketTimeoutIsNotBareTimeoutWord() {
        val message = NetworkErrors.describe(
            SocketTimeoutException("timeout"),
            "http://192.168.18.36:8000/v1/sandbox/approvals/pending",
            "Pending approvals"
        )
        assertTrue(message.contains("timed out"))
        assertTrue(message.contains("192.168.18.36:8000"))
        assertTrue(message.contains("SocketTimeoutException"))
    }
}
