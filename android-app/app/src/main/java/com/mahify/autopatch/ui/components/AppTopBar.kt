package com.mahify.autopatch.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.NotificationsNone
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.mahify.autopatch.model.HealthState
import com.mahify.autopatch.ui.theme.AppNameStyle
import com.mahify.autopatch.ui.theme.SurfaceElevation1
import com.mahify.autopatch.ui.theme.TextPrimary
import com.mahify.autopatch.ui.theme.TextSecondary

@Composable
fun AppTopBar(
    connectionHealth: HealthState,
    hasUnreadNotifications: Boolean,
    onNotificationsClick: () -> Unit,
    onSettingsClick: () -> Unit,
    modifier: Modifier = Modifier
) {
    val colors = colorsFor(connectionHealth)

    Row(
        modifier = modifier
            .fillMaxWidth()
            .background(SurfaceElevation1)
            .windowInsetsPadding(WindowInsets.statusBars)
            .padding(horizontal = 20.dp, vertical = 14.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = "AutoPatch Control",
                style = AppNameStyle,
                color = TextPrimary
            )

            Spacer(Modifier.height(3.dp))

            Row(verticalAlignment = Alignment.CenterVertically) {
                StatusDot(
                    color = colors.fg,
                    size = 6.dp
                )

                Spacer(Modifier.width(5.dp))

                Text(
                    text = "System Monitor",
                    style = MaterialTheme.typography.labelMedium,
                    color = TextSecondary
                )
            }
        }

        Box {
            IconButton(onClick = onNotificationsClick) {
                Icon(
                    imageVector = Icons.Outlined.NotificationsNone,
                    contentDescription = "Notifications",
                    tint = TextPrimary
                )
            }

            if (hasUnreadNotifications) {
                Box(
                    modifier = Modifier
                        .align(Alignment.TopEnd)
                        .padding(top = 10.dp, end = 10.dp)
                        .size(7.dp)
                        .background(
                            colorsFor(HealthState.OFFLINE).fg,
                            CircleShape
                        )
                )
            }
        }

        IconButton(onClick = onSettingsClick) {
            Icon(
                imageVector = Icons.Outlined.Settings,
                contentDescription = "Settings",
                tint = TextPrimary
            )
        }
    }
}