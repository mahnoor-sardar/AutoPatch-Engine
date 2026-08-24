package com.mahify.autopatch.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.mahify.autopatch.model.HealthState
import com.mahify.autopatch.model.SystemStatus
import com.mahify.autopatch.ui.theme.BorderSubtle
import com.mahify.autopatch.ui.theme.SurfaceElevation1
import com.mahify.autopatch.ui.theme.TextPrimary
import com.mahify.autopatch.ui.theme.TextSecondary

/**
 * Individual system tile. Designed for a 2-column grid on the dashboard but
 * works equally well as a full-width row (used on the Repositories/Settings
 * screens if you list systems there too).
 */
@Composable
fun SystemStatusCard(
    system: SystemStatus,
    modifier: Modifier = Modifier
) {
    val colors = colorsFor(system.health)

    Column(
        modifier = modifier
            .fillMaxWidth()
            .background(SurfaceElevation1, MaterialTheme.shapes.medium)
            .border(1.dp, BorderSubtle, MaterialTheme.shapes.medium)
            .padding(14.dp)
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(
                modifier = Modifier
                    .size(30.dp)
                    .background(colors.bg, CircleShape),
                contentAlignment = Alignment.Center
            ) {
                Icon(
                    imageVector = system.icon,
                    contentDescription = null,
                    tint = colors.fg,
                    modifier = Modifier.size(16.dp)
                )
            }
            Spacer(Modifier.weight(1f))
            StatusDot(color = colors.fg)
        }

        Spacer(Modifier.height(12.dp))

        Text(
            text = system.name,
            style = MaterialTheme.typography.titleSmall,
            color = TextPrimary
        )
        Spacer(Modifier.height(2.dp))
        Text(
            text = system.statusLabel,
            style = MaterialTheme.typography.bodySmall,
            color = colors.fg
        )
        Spacer(Modifier.height(2.dp))
        Text(
            text = system.description,
            style = MaterialTheme.typography.labelSmall,
            color = TextSecondary,
            maxLines = 1
        )
    }
}

