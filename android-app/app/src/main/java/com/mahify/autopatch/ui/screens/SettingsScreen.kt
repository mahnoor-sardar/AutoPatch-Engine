package com.mahify.autopatch.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.runtime.collectAsState
import androidx.lifecycle.viewmodel.compose.viewModel
import com.mahify.autopatch.HomeViewModel
import com.mahify.autopatch.model.HealthState
import com.mahify.autopatch.model.SystemStatus
import com.mahify.autopatch.ui.components.SectionHeader
import com.mahify.autopatch.ui.components.SystemStatusCard
import com.mahify.autopatch.ui.theme.AccentPrimary
import com.mahify.autopatch.ui.theme.BorderSubtle
import com.mahify.autopatch.ui.theme.SurfaceElevation1
import com.mahify.autopatch.ui.theme.TextPrimary
import com.mahify.autopatch.ui.theme.TextSecondary

@Composable
fun SettingsScreen(
    modifier: Modifier = Modifier,
    homeViewModel: HomeViewModel = viewModel()
) {
    val uiState by homeViewModel.uiState.collectAsState()
    var pushNotifications by remember { mutableStateOf(true) }
    var failureAlertsOnly by remember { mutableStateOf(false) }
    var darkModeLocked by remember { mutableStateOf(true) }

    Column(
        modifier = modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 20.dp, vertical = 16.dp),
        verticalArrangement = Arrangement.spacedBy(22.dp)
    ) {
        Column {
            Text(text = "Settings", style = MaterialTheme.typography.headlineSmall, color = TextPrimary)
            Spacer(Modifier.height(4.dp))
            Text(
                text = "Connections and preferences for AutoPatch Control.",
                style = MaterialTheme.typography.bodySmall,
                color = TextSecondary
            )
        }

        Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
            SectionHeader(title = "Connections")
            val liveSystems = listOf(
                SystemStatus(
                    id = "backend",
                    name = "Backend",
                    statusLabel = if (uiState.backendOnline) "Connected" else "Offline",
                    description = uiState.error ?: "API health",
                    health = if (uiState.backendOnline) HealthState.ONLINE else HealthState.OFFLINE,
                    icon = com.mahify.autopatch.model.MockData.systems[0].icon
                )
            )
            liveSystems.chunked(2).forEach { row ->
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    row.forEach { system ->
                        SystemStatusCard(system = system, modifier = Modifier.weight(1f))
                    }
                    if (row.size == 1) Spacer(Modifier.weight(1f))
                }
            }
        }

        Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            SectionHeader(title = "Notifications")
            SettingsToggleRow(
                title = "Push notifications",
                description = "Get notified about patch run outcomes.",
                checked = pushNotifications,
                onCheckedChange = { pushNotifications = it }
            )
            SettingsToggleRow(
                title = "Failures only",
                description = "Only notify when a patch run fails.",
                checked = failureAlertsOnly,
                onCheckedChange = { failureAlertsOnly = it }
            )
        }

        Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            SectionHeader(title = "Appearance")
            SettingsToggleRow(
                title = "Dark theme",
                description = "AutoPatch Control is designed dark-first.",
                checked = darkModeLocked,
                onCheckedChange = { darkModeLocked = it }
            )
        }

        Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
            SectionHeader(title = "About")
            Text(
                text = "AutoPatch Control · v0.1.0 (UI preview)",
                style = MaterialTheme.typography.labelMedium,
                color = TextSecondary
            )
        }

        Spacer(Modifier.height(8.dp))
    }
}

@Composable
private fun SettingsToggleRow(
    title: String,
    description: String,
    checked: Boolean,
    onCheckedChange: (Boolean) -> Unit
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .background(SurfaceElevation1, MaterialTheme.shapes.medium)
            .border(1.dp, BorderSubtle, MaterialTheme.shapes.medium)
            .padding(horizontal = 14.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Text(text = title, style = MaterialTheme.typography.titleSmall, color = TextPrimary)
            Spacer(Modifier.height(2.dp))
            Text(text = description, style = MaterialTheme.typography.labelSmall, color = TextSecondary)
        }
        Switch(
            checked = checked,
            onCheckedChange = onCheckedChange,
            colors = SwitchDefaults.colors(
                checkedThumbColor = AccentPrimary,
                checkedTrackColor = AccentPrimary.copy(alpha = 0.35f)
            )
        )
    }
}

