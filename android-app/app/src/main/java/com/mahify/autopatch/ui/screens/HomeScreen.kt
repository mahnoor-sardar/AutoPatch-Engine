package com.mahify.autopatch.ui.screens

import android.content.Context
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import android.provider.Settings
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Cloud
import androidx.compose.material.icons.outlined.Dns
import androidx.compose.material.icons.outlined.ListAlt
import androidx.compose.material.icons.outlined.NotificationsNone
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material.icons.outlined.Security
import androidx.compose.material.icons.outlined.Storage
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel

import com.mahify.autopatch.ApprovalSubmit
import com.mahify.autopatch.HomeViewModel
import com.mahify.autopatch.SandboxRun
import com.mahify.autopatch.model.ApprovalRequest
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
import com.mahify.autopatch.ui.theme.BorderSubtle
import com.mahify.autopatch.ui.theme.StatusError
import com.mahify.autopatch.ui.theme.StatusOnline
import com.mahify.autopatch.ui.theme.StatusWarning
import com.mahify.autopatch.ui.theme.SurfaceElevation1
import com.mahify.autopatch.ui.theme.TextPrimary
import com.mahify.autopatch.ui.theme.TextSecondary

@Composable
fun HomeScreen(
    onViewAllActivity: () -> Unit,
    onViewRepositories: () -> Unit,
    onOpenNotifications: () -> Unit,
    modifier: Modifier = Modifier,
    homeViewModel: HomeViewModel = viewModel()
) {
    val uiState by homeViewModel.uiState.collectAsState()

    val context = androidx.compose.ui.platform.LocalContext.current

    LaunchedEffect(Unit) {
        homeViewModel.loadPendingApproval(context)
    }

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

        /*
         * Android approval gate.
         *
         * This becomes visible only when the backend reports
         * a pending sandbox approval for this device.
         */
        items(
            ApprovalSubmit.newestRunFirst(uiState.pendingApprovals),
            key = { ApprovalSubmit.itemKey(it) }
        ) { approval ->
            ApprovalCard(
                approval = approval,
                loading = uiState.approvalLoading,
                error = uiState.approvalError,
                onApprove = { otpCode ->
                    homeViewModel.approvePendingApproval(
                        context,
                        approval,
                        otpCode
                    )
                },
                onReject = { otpCode ->
                    homeViewModel.rejectPendingApproval(
                        context,
                        approval,
                        otpCode
                    )
                },
                onBiometric = {
                    requestBiometricApproval(
                        context,
                        onSuccess = {
                            homeViewModel.approveWithSignedToken(
                                context,
                                approval
                            )
                        },
                        onError = { message ->
                            homeViewModel.setApprovalError(message)
                        }
                    )
                },
                onRefresh = {
                    homeViewModel.loadPendingApproval(context)
                }
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
                    redisOnline = uiState.redisOnline,
                    firebaseOnline = uiState.firebaseOnline
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
                            homeViewModel.loadPendingApproval(context)
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
            uiState.recentRuns.distinctBy { it.id }.take(4),
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
private fun ApprovalCard(
    approval: ApprovalRequest,
    loading: Boolean,
    error: String?,
    onApprove: (otpCode: String) -> Unit,
    onReject: (otpCode: String) -> Unit,
    onBiometric: () -> Unit,
    onRefresh: () -> Unit
) {
    val runId = ApprovalSubmit.runIdForDisplayedRequest(approval)
    val runLabel = ApprovalSubmit.runLabel(runId)
    var otpCode by remember(runId) { mutableStateOf("") }
    val otpValid = otpCode.length == 6 && otpCode.all { it.isDigit() }

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .background(
                SurfaceElevation1,
                RoundedCornerShape(16.dp)
            )
            .border(
                1.dp,
                BorderSubtle,
                RoundedCornerShape(16.dp)
            )
            .padding(18.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {

        Row(
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            Box(
                modifier = Modifier
                    .background(
                        StatusWarning.copy(alpha = 0.15f),
                        RoundedCornerShape(12.dp)
                    )
                    .padding(10.dp)
            ) {
                androidx.compose.material3.Icon(
                    imageVector = Icons.Outlined.Security,
                    contentDescription = null,
                    tint = StatusWarning
                )
            }

            Column(
                modifier = Modifier.weight(1f)
            ) {
                Text(
                    text = "Approval required",
                    style = MaterialTheme.typography.titleMedium,
                    color = TextPrimary
                )

                Text(
                    text = when (approval.gate) {
                        "patch_review" -> "Patch review is waiting."
                        "merge" -> "Merge authorization is waiting."
                        else -> "Sandbox provisioning is waiting."
                    },
                    style = MaterialTheme.typography.bodySmall,
                    color = TextSecondary
                )
            }
        }

        Text(
            text = runLabel,
            style = MaterialTheme.typography.headlineMedium,
            color = StatusWarning
        )

        Text(
            text = approval.repository,
            style = MaterialTheme.typography.titleSmall,
            color = TextPrimary
        )

        Text(
            text = "Gate: ${approval.gate.replace('_', ' ')}",
            style = MaterialTheme.typography.bodySmall,
            color = TextSecondary
        )

        approval.expiresAt?.let {
            Text(
                text = "Approval expires soon",
                style = MaterialTheme.typography.labelSmall,
                color = StatusWarning
            )
        }

        approval.diff?.let { patch ->
            Text(
                text = "Proposed diff",
                style = MaterialTheme.typography.labelMedium,
                color = TextSecondary
            )
            com.mahify.autopatch.ui.components.UnifiedDiffViewer(
                diff = patch,
                modifier = Modifier
                    .fillMaxWidth()
                    .height(280.dp)
            )
        }

        OutlinedTextField(
            value = otpCode,
            onValueChange = { value ->
                otpCode = value.filter { it.isDigit() }.take(6)
            },
            modifier = Modifier.fillMaxWidth(),
            singleLine = true,
            enabled = !loading,
            label = {
                Text("6-digit OTP for $runLabel")
            },
            placeholder = {
                Text("000000")
            },
            keyboardOptions = KeyboardOptions(
                keyboardType = KeyboardType.NumberPassword
            )
        )

        if (!error.isNullOrBlank()) {
            Text(
                text = error,
                style = MaterialTheme.typography.bodySmall,
                color = StatusError
            )
        }

        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            OutlinedButton(
                onClick = onRefresh,
                enabled = !loading,
                modifier = Modifier.weight(1f)
            ) {
                Text("Refresh")
            }

            OutlinedButton(
                onClick = { onReject(otpCode) },
                enabled = !loading && otpValid,
                modifier = Modifier.weight(1f)
            ) {
                Text("Reject $runLabel")
            }
        }

        Button(
            onClick = { onApprove(otpCode) },
            enabled = !loading && otpValid,
            modifier = Modifier.fillMaxWidth(),
            colors = ButtonDefaults.buttonColors(
                containerColor = StatusOnline
            )
        ) {
            if (loading) {
                CircularProgressIndicator(
                    modifier = Modifier.height(18.dp),
                    strokeWidth = 2.dp,
                    color = Color.White
                )
            } else {
                Text("Approve $runLabel")
            }
        }

        Button(
            onClick = onBiometric,
            enabled = !loading,
            modifier = Modifier.fillMaxWidth()
        ) {
            Text("Approve $runLabel with biometrics")
        }
    }
}


@Composable
private fun SystemStatusGrid(
    backendOnline: Boolean,
    postgresOnline: Boolean,
    redisOnline: Boolean,
    firebaseOnline: Boolean
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
                    statusLabel = if (firebaseOnline) {
                        "Connected"
                    } else {
                        "Disconnected"
                    },
                    description = if (firebaseOnline) {
                        "FCM token available"
                    } else {
                        "FCM unavailable"
                    },
                    health = if (firebaseOnline) {
                        HealthState.ONLINE
                    } else {
                        HealthState.OFFLINE
                    },
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

private fun requestBiometricApproval(
    context: android.content.Context,
    onSuccess: () -> Unit,
    onError: (String) -> Unit
) {
    val activity = context as? androidx.fragment.app.FragmentActivity
    if (activity == null) {
        onError("Biometrics require a FragmentActivity host")
        return
    }
    val executor = androidx.core.content.ContextCompat.getMainExecutor(context)
    val prompt = androidx.biometric.BiometricPrompt(
        activity,
        executor,
        object : androidx.biometric.BiometricPrompt.AuthenticationCallback() {
            override fun onAuthenticationSucceeded(
                result: androidx.biometric.BiometricPrompt.AuthenticationResult
            ) {
                onSuccess()
            }

            override fun onAuthenticationError(errorCode: Int, errString: CharSequence) {
                onError(errString.toString())
            }

            override fun onAuthenticationFailed() {
                onError("Biometric authentication failed")
            }
        }
    )
    prompt.authenticate(
        androidx.biometric.BiometricPrompt.PromptInfo.Builder()
            .setTitle("Approve AutoPatch gate")
            .setSubtitle("Confirm with fingerprint or face unlock")
            .setNegativeButtonText("Cancel")
            .build()
    )
}