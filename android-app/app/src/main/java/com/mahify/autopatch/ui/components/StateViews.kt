package com.mahify.autopatch.ui.components

import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.CloudOff
import androidx.compose.material.icons.outlined.Inbox
import androidx.compose.material.icons.outlined.WifiOff
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.unit.dp
import com.mahify.autopatch.ui.theme.AccentPrimary
import com.mahify.autopatch.ui.theme.ShimmerBase
import com.mahify.autopatch.ui.theme.ShimmerHighlight
import com.mahify.autopatch.ui.theme.SurfaceElevation1
import com.mahify.autopatch.ui.theme.TextPrimary
import com.mahify.autopatch.ui.theme.TextSecondary

/** A shimmering block used to build skeleton loading layouts. */
@Composable
fun ShimmerBlock(
    modifier: Modifier = Modifier,
    cornerRadius: androidx.compose.ui.unit.Dp = 10.dp
) {
    val transition = rememberInfiniteTransition(label = "shimmer")
    val alpha = transition.animateFloat(
        initialValue = 0.4f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(
            animation = tween(900),
            repeatMode = RepeatMode.Reverse
        ),
        label = "shimmerAlpha"
    ).value

    Box(
        modifier = modifier
            .background(
                ShimmerBase.copy(alpha = alpha.coerceIn(0.4f, 1f)),
                androidx.compose.foundation.shape.RoundedCornerShape(cornerRadius)
            )
    )
}

/** Full-dashboard skeleton shown on first load. */
@Composable
fun LoadingDashboard(modifier: Modifier = Modifier) {
    Column(
        modifier = modifier
            .fillMaxWidth()
            .padding(20.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp)
    ) {
        ShimmerBlock(modifier = Modifier.fillMaxWidth().height(120.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            ShimmerBlock(modifier = Modifier.weight(1f).height(90.dp))
            ShimmerBlock(modifier = Modifier.weight(1f).height(90.dp))
        }
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            ShimmerBlock(modifier = Modifier.weight(1f).height(90.dp))
            ShimmerBlock(modifier = Modifier.weight(1f).height(90.dp))
        }
        ShimmerBlock(modifier = Modifier.fillMaxWidth().height(64.dp))
        ShimmerBlock(modifier = Modifier.fillMaxWidth().height(64.dp))
        ShimmerBlock(modifier = Modifier.fillMaxWidth().height(64.dp))
    }
}

/** Generic empty / disconnected / error placeholder — never lets a screen look "broken". */
@Composable
fun StatePlaceholder(
    icon: ImageVector,
    title: String,
    description: String,
    modifier: Modifier = Modifier,
    actionLabel: String? = null,
    onAction: (() -> Unit)? = null
) {
    Column(
        modifier = modifier
            .fillMaxWidth()
            .padding(vertical = 40.dp, horizontal = 24.dp),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Box(
            modifier = Modifier
                .size(56.dp)
                .background(SurfaceElevation1, androidx.compose.foundation.shape.CircleShape),
            contentAlignment = Alignment.Center
        ) {
            Icon(imageVector = icon, contentDescription = null, tint = TextSecondary, modifier = Modifier.size(26.dp))
        }
        Spacer(Modifier.height(16.dp))
        Text(text = title, style = MaterialTheme.typography.titleMedium, color = TextPrimary)
        Spacer(Modifier.height(6.dp))
        Text(
            text = description,
            style = MaterialTheme.typography.bodySmall,
            color = TextSecondary,
            textAlign = androidx.compose.ui.text.style.TextAlign.Center
        )
        if (actionLabel != null && onAction != null) {
            Spacer(Modifier.height(18.dp))
            Button(
                onClick = onAction,
                colors = ButtonDefaults.buttonColors(containerColor = AccentPrimary)
            ) {
                Text(actionLabel)
            }
        }
    }
}

@Composable
fun NoActivityYet(modifier: Modifier = Modifier) {
    StatePlaceholder(
        icon = Icons.Outlined.Inbox,
        title = "No activity yet",
        description = "Patch runs will appear here as soon as AutoPatch Engine processes a repository event.",
        modifier = modifier
    )
}

@Composable
fun BackendDisconnected(onRetry: () -> Unit, modifier: Modifier = Modifier) {
    StatePlaceholder(
        icon = Icons.Outlined.CloudOff,
        title = "Backend disconnected",
        description = "AutoPatch Control can't reach the backend right now. Check your connection and try again.",
        actionLabel = "Retry",
        onAction = onRetry,
        modifier = modifier
    )
}

@Composable
fun GitHubDisconnected(onRetry: () -> Unit, modifier: Modifier = Modifier) {
    StatePlaceholder(
        icon = Icons.Outlined.WifiOff,
        title = "GitHub disconnected",
        description = "Repository events can't be received until the GitHub connection is restored.",
        actionLabel = "Reconnect",
        onAction = onRetry,
        modifier = modifier
    )
}

@Composable
fun E2BUnavailable(modifier: Modifier = Modifier) {
    StatePlaceholder(
        icon = Icons.Outlined.CloudOff,
        title = "E2B Sandbox unavailable",
        description = "The sandbox environment is temporarily unreachable. New patch runs will queue until it recovers.",
        modifier = modifier
    )
}

