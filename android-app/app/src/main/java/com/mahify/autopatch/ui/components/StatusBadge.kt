package com.mahify.autopatch.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.mahify.autopatch.model.HealthState
import com.mahify.autopatch.ui.theme.StatusError
import com.mahify.autopatch.ui.theme.StatusErrorMuted
import com.mahify.autopatch.ui.theme.StatusNeutral
import com.mahify.autopatch.ui.theme.StatusOnline
import com.mahify.autopatch.ui.theme.StatusOnlineMuted
import com.mahify.autopatch.ui.theme.StatusWarning
import com.mahify.autopatch.ui.theme.StatusWarningMuted

data class StatusColorSet(val fg: Color, val bg: Color)

fun colorsFor(health: HealthState): StatusColorSet = when (health) {
    HealthState.ONLINE -> StatusColorSet(StatusOnline, StatusOnlineMuted)
    HealthState.DEGRADED -> StatusColorSet(StatusWarning, StatusWarningMuted)
    HealthState.OFFLINE -> StatusColorSet(StatusError, StatusErrorMuted)
    HealthState.UNKNOWN -> StatusColorSet(StatusNeutral, Color(0xFF1B1C22))
}

/**
 * A compact pill: dot + label. Used inside system cards, top bar connection
 * indicator, and activity rows.
 */
@Composable
fun StatusBadge(
    label: String,
    health: HealthState,
    modifier: Modifier = Modifier
) {
    val colors = colorsFor(health)
    Row(
        modifier = modifier
            .background(colors.bg, RoundedCornerShape(20.dp))
            .padding(horizontal = 10.dp, vertical = 5.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(6.dp)
    ) {
        StatusDot(color = colors.fg)
        Text(
            text = label,
            style = MaterialTheme.typography.labelMedium,
            color = colors.fg
        )
    }
}

@Composable
fun StatusDot(
    color: Color,
    modifier: Modifier = Modifier,
    size: androidx.compose.ui.unit.Dp = 7.dp
) {
    Box(
        modifier = modifier
            .size(size)
            .background(color, CircleShape)
    )
}

