package com.mahify.autopatch

import com.mahify.autopatch.model.ApprovalRequest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Test

class ApprovalSubmitTest {
    @Test
    fun approveUsesDisplayedRunIdNotFirstPending() {
        val displayed = ApprovalRequest(
            runId = 165,
            repository = "owner/repo",
            gate = "sandbox_provision",
            expiresAt = null
        )
        val firstPending = ApprovalRequest(
            runId = 129,
            repository = "owner/repo",
            gate = "sandbox_provision",
            expiresAt = null
        )
        assertEquals(165, ApprovalSubmit.runIdForDisplayedRequest(displayed))
        assertEquals("Run #165", ApprovalSubmit.runLabel(displayed.runId))
        assertNotEquals(
            firstPending.runId,
            ApprovalSubmit.runIdForDisplayedRequest(displayed)
        )
    }

    @Test
    fun pendingJsonUsesEachCardsRunIdNotGateOrder() {
        val body = """
            {
              "approvals": [
                {
                  "run_id": 129,
                  "repository": "owner/repo",
                  "gate": "sandbox_provision",
                  "expires_at": null,
                  "diff": null
                },
                {
                  "run_id": 165,
                  "repository": "owner/repo",
                  "gate": "sandbox_provision",
                  "expires_at": null,
                  "diff": null
                }
              ]
            }
        """.trimIndent()
        val pending = ApprovalSubmit.parsePendingResponse(body)
        assertEquals(listOf(165, 129), pending.map { it.runId })
        val displayed = pending.first()
        assertEquals("Run #165", ApprovalSubmit.runLabel(displayed.runId))
        assertEquals(165, ApprovalSubmit.runIdForDisplayedRequest(displayed))
    }

    @Test
    fun duplicateRunIdAndGateDedupedNewestFirstUniqueKeys() {
        val body = """
            {
              "approvals": [
                {
                  "run_id": 163,
                  "repository": "owner/repo",
                  "gate": "sandbox_provision",
                  "expires_at": null,
                  "diff": null
                },
                {
                  "run_id": 165,
                  "repository": "owner/repo",
                  "gate": "sandbox_provision",
                  "expires_at": null,
                  "diff": null
                },
                {
                  "run_id": 163,
                  "repository": "owner/repo",
                  "gate": "sandbox_provision",
                  "expires_at": "later",
                  "diff": null
                }
              ]
            }
        """.trimIndent()
        val pending = ApprovalSubmit.parsePendingResponse(body)
        assertEquals(listOf(165, 163), pending.map { it.runId })
        val keys = pending.map { ApprovalSubmit.itemKey(it) }
        assertEquals(keys.distinct(), keys)
        assertEquals(
            listOf("165:sandbox_provision", "163:sandbox_provision"),
            keys
        )
        val displayed = pending.first()
        assertEquals(165, ApprovalSubmit.runIdForDisplayedRequest(displayed))
        assertEquals("Run #165", ApprovalSubmit.runLabel(displayed.runId))
    }
}
