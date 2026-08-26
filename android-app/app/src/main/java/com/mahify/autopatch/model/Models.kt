package com.mahify.autopatch.model

import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Cloud
import androidx.compose.material.icons.outlined.Dns
import androidx.compose.material.icons.outlined.NotificationsActive
import androidx.compose.material.icons.outlined.Terminal

/** Generic health state shared by the hero card and system cards. */
enum class HealthState {
    ONLINE,
    DEGRADED,
    OFFLINE,
    UNKNOWN
}

/** Status of an individual patch run. */
enum class PatchStatus {
    RUNNING,
    COMPLETED,
    FAILED,
    QUEUED
}

data class SystemStatus(
    val id: String,
    val name: String,
    val statusLabel: String,
    val description: String,
    val health: HealthState,
    val icon: ImageVector
)

data class PatchActivity(
    val id: String,
    val patchNumber: String,
    val repository: String,
    val status: PatchStatus,
    val timeAgo: String
)

data class PatchStats(
    val total: Int,
    val successful: Int,
    val running: Int,
    val failed: Int
)

data class ApprovalRequest(
    val runId: Int,
    val repository: String,
    val gate: String,
    val expiresAt: String?
)

/** Mock data only — no networking, no persistence. Swap for real state upstream. */
object MockData {

    val systems = listOf(
        SystemStatus(
            id = "backend",
            name = "Backend",
            statusLabel = "Connected",
            description = "API responding normally",
            health = HealthState.ONLINE,
            icon = Icons.Outlined.Dns
        ),
        SystemStatus(
            id = "github",
            name = "GitHub",
            statusLabel = "Connected",
            description = "Webhooks active",
            health = HealthState.ONLINE,
            icon = Icons.Outlined.Terminal
        ),
        SystemStatus(
            id = "e2b",
            name = "E2B Sandbox",
            statusLabel = "Ready",
            description = "Idle — awaiting job",
            health = HealthState.ONLINE,
            icon = Icons.Outlined.Cloud
        ),
        SystemStatus(
            id = "firebase",
            name = "Firebase",
            statusLabel = "Connected",
            description = "Notifications enabled",
            health = HealthState.ONLINE,
            icon = Icons.Outlined.NotificationsActive
        )
    )

    val recentActivity = listOf(
        PatchActivity(
            "1",
            "#104",
            "AutoPatch-Engine",
            PatchStatus.COMPLETED,
            "2 min ago"
        ),
        PatchActivity(
            "2",
            "#103",
            "AutoPatch-Engine",
            PatchStatus.RUNNING,
            "8 min ago"
        ),
        PatchActivity(
            "3",
            "#102",
            "Backend",
            PatchStatus.FAILED,
            "24 min ago"
        ),
        PatchActivity(
            "4",
            "#101",
            "AutoPatch-Engine",
            PatchStatus.COMPLETED,
            "1 hr ago"
        ),
        PatchActivity(
            "5",
            "#100",
            "Backend",
            PatchStatus.COMPLETED,
            "3 hr ago"
        )
    )

    val stats = PatchStats(
        total = 24,
        successful = 21,
        running = 2,
        failed = 1
    )
}