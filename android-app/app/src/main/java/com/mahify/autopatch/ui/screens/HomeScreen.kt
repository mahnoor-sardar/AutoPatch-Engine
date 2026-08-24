package com.mahify.autopatch.ui.screens

import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.compose.runtime.collectAsState
import com.mahify.autopatch.HomeViewModel
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.NotificationsNone
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material.icons.outlined.Storage
import androidx.compose.material.icons.outlined.ListAlt
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.mahify.autopatch.model.HealthState
import com.mahify.autopatch.model.MockData
import com.mahify.autopatch.ui.components.EngineStatusCard
import com.mahify.autopatch.ui.components.ActivityItem
import com.mahify.autopatch.ui.components.QuickActionCard
import com.mahify.autopatch.ui.components.SectionHeader
import com.mahify.autopatch.ui.components.StatCard
import com.mahify.autopatch.ui.components.SystemStatusCard
import com.mahify.autopatch.ui.theme.StatusError
import com.mahify.autopatch.ui.theme.StatusOnline
import com.mahify.autopatch.ui.theme.StatusWarning
import com.mahify.autopatch.ui.theme.TextPrimary

/**
 * Home Dashboard.
 *
 * Vertical hierarchy (top to bottom = importance):
 *  1. Engine hero card — "is it working?" answered in <1s via color + label.
 *  2. Systems grid — "is anything broken?" scan across 4 dependencies.
 *  3. Quick actions — the few things a user actually needs to do here.
 *  4. Stats — quantifies health without reading like a spreadsheet (label
 *     under number, colored only where it signals status).
 *  5. Recent activity — "what happened recently?" newest-first, capped at a
 *     few rows with a "View all" affordance into the Activity tab.
 *
 */
@Composable
fun HomeScreen(
    onViewAllActivity: () -> Unit,
    onViewRepositories: () -> Unit,
    onOpenNotifications: () -> Unit,
    modifier: Modifier = Modifier,
    homeViewModel: HomeViewModel = viewModel()
) {
    val uiState by homeViewModel.uiState.collectAsState()
    var isRefreshing by remember { mutableStateOf(false) }

    LazyColumn(
        modifier = modifier.fillMaxSize(),
        contentPadding = PaddingValues(horizontal = 20.dp, vertical = 18.dp),
        verticalArrangement = Arrangement.spacedBy(22.dp)
    ) {
        item {
            EngineStatusCard(
                health = HealthState.ONLINE,
                statusLabel = "ONLINE",
                description = "Ready to process repository events."
            )
        }

        item {
            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                SectionHeader(title = "Systems")
                LazyVerticalGridFixed()
            }
        }

        item {
            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                SectionHeader(title = "Quick Actions")
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    QuickActionCard(
                        label = "Refresh",
                        icon = Icons.Outlined.Refresh,
                        onClick = { isRefreshing = !isRefreshing },
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
            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                SectionHeader(title = "Patch Statistics")
                val stats = MockData.stats
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
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

        item { Spacer(Modifier.height(8.dp)) }
    }
}

/**
 * 2-column systems grid. Implemented as a fixed-height non-scrolling grid
 * (nested inside the outer LazyColumn) since the systems list is short and
 * fixed — avoids nested-scroll complexity for 4 known items.
 */
@Composable
private fun LazyVerticalGridFixed() {
    val systems = MockData.systems
    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        systems.chunked(2).forEach { row ->
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                row.forEach { system ->
                    SystemStatusCard(system = system, modifier = Modifier.weight(1f))
                }
                if (row.size == 1) {
                    Spacer(Modifier.weight(1f))
                }
            }
        }
    }
}

