package com.mahify.autopatch.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Error
import androidx.compose.material.icons.filled.Sync
import androidx.compose.material.icons.filled.Schedule
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.unit.dp
import com.mahify.autopatch.model.HealthState
import com.mahify.autopatch.model.PatchActivity
import com.mahify.autopatch.model.PatchStatus
import com.mahify.autopatch.ui.theme.BorderSubtle
import com.mahify.autopatch.ui.theme.SurfaceElevation1
import com.mahify.autopatch.ui.theme.TextPrimary
import com.mahify.autopatch.ui.theme.TextTertiary

private fun PatchStatus.health(): HealthState = when (this) {
    PatchStatus.COMPLETED -> HealthState.ONLINE
    PatchStatus.RUNNING -> HealthState.DEGRADED
    PatchStatus.FAILED -> HealthState.OFFLINE
    PatchStatus.QUEUED -> HealthState.UNKNOWN
}

private fun PatchStatus.label(): String = when (this) {
    PatchStatus.COMPLETED -> "Completed"
    PatchStatus.RUNNING -> "Running"
    PatchStatus.FAILED -> "Failed"
    PatchStatus.QUEUED -> "Queued"
}

private fun PatchStatus.icon(): ImageVector = when (this) {
    PatchStatus.COMPLETED -> Icons.Filled.CheckCircle
    PatchStatus.RUNNING -> Icons.Filled.Sync
    PatchStatus.FAILED -> Icons.Filled.Error
    PatchStatus.QUEUED -> Icons.Filled.Schedule
}

@Composable
fun ActivityItem(
    activity: PatchActivity,
    modifier: Modifier = Modifier
) {
    val health = activity.status.health()
    val colors = colorsFor(health)

    Row(
        modifier = modifier
            .fillMaxWidth()
            .background(
                SurfaceElevation1,
                MaterialTheme.shapes.medium
            )
            .border(
                1.dp,
                BorderSubtle,
                MaterialTheme.shapes.medium
            )
            .padding(14.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Box(
            modifier = Modifier
                .size(34.dp)
                .background(colors.bg, CircleShape),
            contentAlignment = Alignment.Center
        ) {
            Icon(
                imageVector = activity.status.icon(),
                contentDescription = null,
                tint = colors.fg,
                modifier = Modifier.size(18.dp)
            )
        }

        Spacer(Modifier.width(12.dp))

        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = "Patch ${activity.patchNumber}",
                style = MaterialTheme.typography.titleSmall,
                color = TextPrimary
            )

            Spacer(Modifier.height(2.dp))

            Text(
                text = activity.repository,
                style = MaterialTheme.typography.bodySmall,
                color = TextTertiary
            )
        }

        Column(horizontalAlignment = Alignment.End) {
            Text(
                text = activity.status.label(),
                style = MaterialTheme.typography.labelMedium,
                color = colors.fg
            )

            Spacer(Modifier.height(2.dp))

            Text(
                text = activity.timeAgo,
                style = MaterialTheme.typography.labelSmall,
                color = TextTertiary
            )
        }
    }
}