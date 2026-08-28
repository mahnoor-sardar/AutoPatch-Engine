package com.mahify.autopatch

import com.mahify.autopatch.model.ApprovalRequest
import org.json.JSONArray
import org.json.JSONObject

/**
 * Pending approvals must be submitted with the run id shown on that card,
 * never "the first pending gate" from a later refresh.
 */
object ApprovalSubmit {
    fun runIdForDisplayedRequest(displayed: ApprovalRequest): Int {
        require(displayed.runId > 0) { "approval is missing run_id" }
        return displayed.runId
    }

    fun runLabel(runId: Int): String = "Run #$runId"

    fun parsePendingResponse(body: String): List<ApprovalRequest> {
        val root = JSONObject(body)
        val approvalsJson = root.optJSONArray("approvals") ?: JSONArray()
        val parsed = buildList {
            for (i in 0 until approvalsJson.length()) {
                val approval = approvalsJson.getJSONObject(i)
                val runId = parseRunId(approval)
                if (runId <= 0) {
                    continue
                }
                add(
                    ApprovalRequest(
                        runId = runId,
                        repository = approval.optString("repository"),
                        gate = approval.optString("gate"),
                        expiresAt = approval.optString("expires_at")
                            .takeIf { it.isNotBlank() && !approval.isNull("expires_at") },
                        diff = approval.optString("diff")
                            .takeIf { it.isNotBlank() && !approval.isNull("diff") }
                    )
                )
            }
        }
        return newestRunFirst(parsed)
    }

    fun itemKey(approval: ApprovalRequest): String =
        "${approval.runId}:${approval.gate}"

    fun newestRunFirst(approvals: List<ApprovalRequest>): List<ApprovalRequest> {
        return approvals
            .filter { it.runId > 0 }
            .sortedByDescending { it.runId }
            .distinctBy { itemKey(it) }
    }

    internal fun parseRunId(approval: JSONObject): Int {
        if (!approval.has("run_id") || approval.isNull("run_id")) {
            return 0
        }
        return when (val value = approval.get("run_id")) {
            is Int -> value
            is Number -> value.toInt()
            is String -> value.toIntOrNull() ?: 0
            else -> 0
        }
    }
}
