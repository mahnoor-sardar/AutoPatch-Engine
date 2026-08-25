package com.mahify.autopatch.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Cloud
import androidx.compose.material.icons.outlined.Dns
import androidx.compose.material.icons.outlined.ListAlt
import androidx.compose.material.icons.outlined.NotificationsNone
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material.icons.outlined.Storage
import androidx.compose.material.icons.outlined.Terminal
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel

import com.mahify.autopatch.HomeViewModel
import com.mahify.autopatch.SandboxRun
import com.mahify.autopatch.model.HealthState
import com.mahify.autopatch.model.PatchActivity
import com.mahify.autopatch.model.PatchStatus
import com.mahify.autopatch.model.SystemStatus
import com.mahify.autopatch.ui.components.ActivityItem
import com.mahify.autopatch.ui.components.EngineStatusCard
import com.mahify.autopatch.ui.components.QuickActionCard
import com.mahify.autopatch.ui.components.SectionHeader
import com.mahify.autopatch.ui.components.StatCard
import com.mahify.autopatch.ui.components.SystemStatusCard
import com.mahify.autopatch.ui.theme.StatusError
import com.mahify.autopatch.ui.theme.StatusOnline
import com.mahify.autopatch.ui.theme.StatusWarning
import com.mahify.autopatch.ui.theme.TextPrimary

@Composable
fun HomeScreen(
    onViewAllActivity: () -> Unit,
    onViewRepositories: () -> Unit,
    onOpenNotifications: () -> Unit,
    modifier: Modifier = Modifier,
    homeViewModel: HomeViewModel = viewModel()
) {
    val uiState by homeViewModel.uiState.collectAsState()

    val engineHealth = when {
        uiState.isLoading -> HealthState.UNKNOWN
        uiState.backendOnline -> HealthState.ONLINE
        else -> HealthState.OFFLINE
    }

    val engineLabel = when {
        uiState.isLoading -> "CHECKING"
        uiState.backendOnline -> "ONLINE"
        else -> "OFFLINE"
    }

    val engineDescription = when {
        uiState.isLoading -> "Checking backend connection..."
        uiState.backendOnline -> "Ready to process repository events."
        else -> "Unable to connect to the backend."
    }

    LazyColumn(
        modifier = modifier.fillMaxSize(),
        contentPadding = PaddingValues(
            horizontal = 20.dp,
            vertical = 18.dp
        ),
        verticalArrangement = Arrangement.spacedBy(22.dp)
    ) {

        item {
            EngineStatusCard(
                health = engineHealth,
                statusLabel = engineLabel,
                description = engineDescription
            )
        }

        item {
            Column(
                verticalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                SectionHeader(title = "Systems")

                SystemStatusGrid(
                    backendOnline = uiState.backendOnline,
                    postgresOnline = uiState.postgresOnline,
                    redisOnline = uiState.redisOnline
                )
            }
        }

        item {
            Column(
                verticalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                SectionHeader(title = "Quick Actions")

                Row(
                    horizontalArrangement = Arrangement.spacedBy(10.dp)
                ) {
                    QuickActionCard(
                        label = "Refresh",
                        icon = Icons.Outlined.Refresh,
                        onClick = {
                            homeViewModel.refresh()
                        },
                        modifier = Modifier.weight(1f)
                    )

                    QuickActionCard(
                        label = "Activity",
                        icon = Icons.Outlined.ListAlt,
                        onClick = onViewAllActivity,
                        modifier = Modifier.weight(1f)
                    )

                    QuickActionCard(
                        label = "Repos",
                        icon = Icons.Outlined.Storage,
                        onClick = onViewRepositories,
                        modifier = Modifier.weight(1f)
                    )

                    QuickActionCard(
                        label = "Alerts",
                        icon = Icons.Outlined.NotificationsNone,
                        onClick = onOpenNotifications,
                        modifier = Modifier.weight(1f)
                    )
                }
            }
        }

        item {
            Column(
                verticalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                SectionHeader(title = "Patch Statistics")

                Row(
                    horizontalArrangement = Arrangement.spacedBy(10.dp)
                ) {
                    StatCard(
                        value = uiState.totalRuns.toString(),
                        label = "Total",
                        accentColor = TextPrimary,
                        modifier = Modifier.weight(1f)
                    )

                    StatCard(
                        value = uiState.successfulRuns.toString(),
                        label = "Successful",
                        accentColor = StatusOnline,
                        modifier = Modifier.weight(1f)
                    )

                    StatCard(
                        value = uiState.runningRuns.toString(),
                        label = "Running",
                        accentColor = StatusWarning,
                        modifier = Modifier.weight(1f)
                    )

                    StatCard(
                        value = uiState.failedRuns.toString(),
                        label = "Failed",
                        accentColor = StatusError,
                        modifier = Modifier.weight(1f)
                    )
                }
            }
        }

        item {
            SectionHeader(
                title = "Recent Activity",
                actionLabel = "View all",
                onActionClick = onViewAllActivity
            )
        }

        items(
            uiState.recentRuns.take(4),
            key = { it.id }
        ) { run ->
            ActivityItem(
                activity = run.toPatchActivity()
            )
        }

        item {
            Spacer(Modifier.height(8.dp))
        }
    }
}

@Composable
private fun SystemStatusGrid(
    backendOnline: Boolean,
    postgresOnline: Boolean,
    redisOnline: Boolean
) {
    Column(
        verticalArrangement = Arrangement.spacedBy(10.dp)
    ) {
        Row(
            horizontalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            SystemStatusCard(
                system = SystemStatus(
                    id = "backend",
                    name = "Backend",
                    statusLabel = if (backendOnline) {
                        "Connected"
                    } else {
                        "Disconnected"
                    },
                    description = if (backendOnline) {
                        "API responding normally"
                    } else {
                        "API unavailable"
                    },
                    health = if (backendOnline) {
                        HealthState.ONLINE
                    } else {
                        HealthState.OFFLINE
                    },
                    icon = Icons.Outlined.Dns
                ),
                modifier = Modifier.weight(1f)
            )

            SystemStatusCard(
                system = SystemStatus(
                    id = "postgres",
                    name = "PostgreSQL",
                    statusLabel = if (postgresOnline) {
                        "Connected"
                    } else {
                        "Disconnected"
                    },
                    description = if (postgresOnline) {
                        "Database responding normally"
                    } else {
                        "Database unavailable"
                    },
                    health = if (postgresOnline) {
                        HealthState.ONLINE
                    } else {
                        HealthState.OFFLINE
                    },
                    icon = Icons.Outlined.Storage
                ),
                modifier = Modifier.weight(1f)
            )
        }

        Row(
            horizontalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            SystemStatusCard(
                system = SystemStatus(
                    id = "redis",
                    name = "Redis",
                    statusLabel = if (redisOnline) {
                        "Connected"
                    } else {
                        "Disconnected"
                    },
                    description = if (redisOnline) {
                        "Queue responding normally"
                    } else {
                        "Queue unavailable"
                    },
                    health = if (redisOnline) {
                        HealthState.ONLINE
                    } else {
                        HealthState.OFFLINE
                    },
                    icon = Icons.Outlined.Cloud
                ),
                modifier = Modifier.weight(1f)
            )

            SystemStatusCard(
                system = SystemStatus(
                    id = "firebase",
                    name = "Firebase",
                    statusLabel = "Unknown",
                    description = "Push status not reported",
                    health = HealthState.UNKNOWN,
                    icon = Icons.Outlined.NotificationsNone
                ),
                modifier = Modifier.weight(1f)
            )
        }
    }
}

private fun SandboxRun.toPatchActivity(): PatchActivity {
    return PatchActivity(
        id = id.toString(),
        patchNumber = "#$id",
        repository = repo,
        status = when (status.lowercase()) {
            "completed" -> PatchStatus.COMPLETED
            "failed" -> PatchStatus.FAILED
            "running" -> PatchStatus.RUNNING
            else -> PatchStatus.QUEUED
        },
        timeAgo = formatTimeAgo(
            startedAt = startedAt,
            finishedAt = finishedAt
        )
    )
}

private fun formatTimeAgo(
    startedAt: String?,
    finishedAt: String?
): String {
    val timestamp = finishedAt ?: startedAt
        ?: return "Unknown time"

    return try {
        val instant = java.time.Instant.parse(timestamp)
        val now = java.time.Instant.now()

        val seconds = java.time.Duration.between(
            instant,
            now
        ).seconds.coerceAtLeast(0)

        when {
            seconds < 60 -> "Just now"

            seconds < 3600 -> {
                val minutes = seconds / 60
                "$minutes min ago"
            }

            seconds < 86400 -> {
                val hours = seconds / 3600
                "$hours hr ago"
            }

            else -> {
                val days = seconds / 86400
                "$days days ago"
            }
        }
    } catch (_: Exception) {
        "Unknown time"
    }
}