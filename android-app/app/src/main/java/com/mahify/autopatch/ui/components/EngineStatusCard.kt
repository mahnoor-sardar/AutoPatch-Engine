package com.mahify.autopatch.ui.components

import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.mahify.autopatch.model.HealthState
import com.mahify.autopatch.ui.theme.AccentPrimary
import com.mahify.autopatch.ui.theme.BorderSubtle
import com.mahify.autopatch.ui.theme.SurfaceElevation1
import com.mahify.autopatch.ui.theme.SurfaceElevation2
import com.mahify.autopatch.ui.theme.TextPrimary
import com.mahify.autopatch.ui.theme.TextSecondary

/**
 * The single most visually dominant element on the dashboard. Answers
 * "is the engine working?" in under a second: label + colored dot + a slow
 * breathing pulse only when healthy (a still dot when degraded/offline reads
 * as more alarming, which is the correct signal).
 */
@Composable
fun EngineStatusCard(
    health: HealthState,
    statusLabel: String,
    description: String,
    modifier: Modifier = Modifier
) {
    Box(
        modifier = modifier
            .fillMaxWidth()
            .clip(MaterialTheme.shapes.large)
            .background(
                Brush.verticalGradient(
                    listOf(SurfaceElevation2, SurfaceElevation1)
                )
            )
            .border(1.dp, BorderSubtle, MaterialTheme.shapes.large)
            .padding(20.dp)
    ) {
        Column {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    text = "AUTOPATCH ENGINE",
                    style = MaterialTheme.typography.labelLarge,
                    color = TextSecondary
                )
            }

            Spacer(Modifier.height(14.dp))

            Row(verticalAlignment = Alignment.CenterVertically) {
                PulsingDot(health = health)
                Spacer(Modifier.width(10.dp))
                Text(
                    text = statusLabel,
                    style = MaterialTheme.typography.headlineSmall,
                    color = TextPrimary,
                    fontWeight = FontWeight.Bold
                )
            }

            Spacer(Modifier.height(8.dp))

            Text(
                text = description,
                style = MaterialTheme.typography.bodyMedium,
                color = TextSecondary
            )
        }

        // Faint brand accent glyph, bottom-right — identity without clutter.
        Box(
            modifier = Modifier
                .align(Alignment.BottomEnd)
                .size(64.dp)
                .clip(CircleShape)
                .background(AccentPrimary.copy(alpha = 0.06f))
        )
    }
}

@Composable
private fun PulsingDot(health: HealthState, modifier: Modifier = Modifier) {
    val colors = colorsFor(health)
    val isHealthy = health == HealthState.ONLINE

    val transition = rememberInfiniteTransition(label = "enginePulse")
    val scale = if (isHealthy) {
        transition.animateFloat(
            initialValue = 1f,
            targetValue = 1.9f,
            animationSpec = infiniteRepeatable(
                animation = tween(1400),
                repeatMode = RepeatMode.Restart
            ),
            label = "pulseScale"
        ).value
    } else 1f

    val alpha = if (isHealthy) {
        transition.animateFloat(
            initialValue = 0.5f,
            targetValue = 0f,
            animationSpec = infiniteRepeatable(
                animation = tween(1400),
                repeatMode = RepeatMode.Restart
            ),
            label = "pulseAlpha"
        ).value
    } else 0f

    Box(contentAlignment = Alignment.Center, modifier = modifier.size(20.dp)) {
        // Outer breathing ring — only rendered when healthy
        if (isHealthy) {
            Box(
                modifier = Modifier
                    .size(12.dp)
                    .scale(scale)
                    .background(colors.fg.copy(alpha = alpha), CircleShape)
            )
        }
        Box(
            modifier = Modifier
                .size(12.dp)
                .background(colors.fg, CircleShape)
        )
    }
}

