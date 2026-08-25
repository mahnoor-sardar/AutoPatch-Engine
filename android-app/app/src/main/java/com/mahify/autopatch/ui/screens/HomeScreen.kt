package com.mahify.autopatch.ui.screens

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.ListAlt
import androidx.compose.material.icons.outlined.NotificationsNone
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material.icons.outlined.Storage
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel

import com.mahify.autopatch.HomeViewModel
import com.mahify.autopatch.model.HealthState
import com.mahify.autopatch.model.MockData
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
                            homeViewModel.refreshHealth()
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

                val stats = MockData.stats

                Row(
                    horizontalArrangement = Arrangement.spacedBy(10.dp)
                ) {
                    StatCard(
                        value = stats.total.toString(),
                        label = "Total",
                        accentColor = TextPrimary,
                        modifier = Modifier.weight(1f)
                    )

                    StatCard(
                        value = stats.successful.toString(),
                        label = "Successful",
                        accentColor = StatusOnline,
                        modifier = Modifier.weight(1f)
                    )

                    StatCard(
                        value = stats.running.toString(),
                        label = "Running",
                        accentColor = StatusWarning,
                        modifier = Modifier.weight(1f)
                    )

                    StatCard(
                        value = stats.failed.toString(),
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

        items(MockData.recentActivity.take(4)) { activity ->
            ActivityItem(activity = activity)
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
                system = MockData.systems[0].copy(
                    health = if (backendOnline) {
                        HealthState.ONLINE
                    } else {
                        HealthState.OFFLINE
                    }
                ),
                modifier = Modifier.weight(1f)
            )

            SystemStatusCard(
                system = MockData.systems[1].copy(
                    health = if (postgresOnline) {
                        HealthState.ONLINE
                    } else {
                        HealthState.OFFLINE
                    }
                ),
                modifier = Modifier.weight(1f)
            )
        }

        Row(
            horizontalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            SystemStatusCard(
                system = MockData.systems[2].copy(
                    health = if (redisOnline) {
                        HealthState.ONLINE
                    } else {
                        HealthState.OFFLINE
                    }
                ),
                modifier = Modifier.weight(1f)
            )

            SystemStatusCard(
                system = MockData.systems[3],
                modifier = Modifier.weight(1f)
            )
        }
    }
}