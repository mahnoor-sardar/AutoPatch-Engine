package com.mahify.autopatch.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.ui.platform.LocalContext
import com.mahify.autopatch.HomeViewModel
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import com.mahify.autopatch.ApiClient
import com.mahify.autopatch.SandboxRun
import com.mahify.autopatch.model.PatchActivity
import com.mahify.autopatch.model.PatchStatus
import com.mahify.autopatch.ui.components.ActivityItem
import com.mahify.autopatch.ui.components.NoActivityYet
import com.mahify.autopatch.ui.theme.AccentPrimary
import com.mahify.autopatch.ui.theme.AccentPrimaryMuted
import com.mahify.autopatch.ui.theme.SurfaceElevation1
import com.mahify.autopatch.ui.theme.SurfaceElevation2
import com.mahify.autopatch.ui.theme.TextPrimary
import com.mahify.autopatch.ui.theme.TextSecondary
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import java.time.Duration
import java.time.Instant


enum class ActivityFilter {
    ALL,
    RUNNING,
    COMPLETED,
    FAILED
}


data class ActivityUiState(
    val runs: List<SandboxRun> = emptyList(),
    val isLoading: Boolean = true,
    val error: String? = null,
    val selectedRunId: Int? = null,
    val diagnosis: String? = null,
    val diagnosisLoading: Boolean = false,
    val diagnosisError: String? = null
)


class ActivityViewModel : ViewModel() {

    private val _uiState = MutableStateFlow(ActivityUiState())

    val uiState: StateFlow<ActivityUiState> =
        _uiState.asStateFlow()

    init {
        loadActivity()
    }

    fun loadActivity() {
        viewModelScope.launch {

            _uiState.value = _uiState.value.copy(
                isLoading = true,
                error = null
            )

            try {
                val result = ApiClient.getSandboxRuns()

                _uiState.value = _uiState.value.copy(
                    runs = result.runs,
                    isLoading = false,
                    error = null
                )

            } catch (e: Exception) {

                _uiState.value = ActivityUiState(
                    runs = emptyList(),
                    isLoading = false,
                    error = e.message
                        ?: "Unable to load activity"
                )
            }
        }
    }

    fun selectRun(runId: Int) {
        if (_uiState.value.selectedRunId == runId) {
            _uiState.value = _uiState.value.copy(
                selectedRunId = null,
                diagnosis = null,
                diagnosisLoading = false,
                diagnosisError = null
            )
            return
        }
        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(
                selectedRunId = runId,
                diagnosis = null,
                diagnosisLoading = true,
                diagnosisError = null
            )
            try {
                val result = ApiClient.getRunDiagnosis(runId)
                if (_uiState.value.selectedRunId != runId) {
                    return@launch
                }
                _uiState.value = _uiState.value.copy(
                    diagnosis = result.diagnosis,
                    diagnosisLoading = false,
                    diagnosisError = null
                )
            } catch (e: Exception) {
                if (_uiState.value.selectedRunId != runId) {
                    return@launch
                }
                _uiState.value = _uiState.value.copy(
                    diagnosis = null,
                    diagnosisLoading = false,
                    diagnosisError = e.message
                        ?: "Unable to load diagnosis"
                )
            }
        }
    }
}


private fun formatTimeAgo(timestamp: String?): String {

    if (timestamp.isNullOrBlank()) {
        return "Unknown time"
    }

    return try {

        val instant = try {
            Instant.parse(timestamp)
        } catch (_: Exception) {
            java.time.OffsetDateTime.parse(timestamp).toInstant()
        }
        val now = Instant.now()

        val seconds = Duration.between(
            instant,
            now
        ).seconds.coerceAtLeast(0)

        when {

            seconds < 60 ->
                "Just now"

            seconds < 3600 ->
                "${seconds / 60} min ago"

            seconds < 86400 ->
                "${seconds / 3600} hr ago"

            seconds < 172800 ->
                "Yesterday"

            else ->
                "${seconds / 86400} days ago"
        }

    } catch (e: Exception) {

        "Unknown time"
    }
}


private fun SandboxRun.toPatchActivity(): PatchActivity {

    val patchStatus = when (status.lowercase()) {

        "completed" ->
            PatchStatus.COMPLETED

        "running" ->
            PatchStatus.RUNNING

        "failed", "killed", "rejected" ->
            PatchStatus.FAILED

        "queued", "paused", "awaiting_patch_review", "awaiting_merge" ->
            PatchStatus.QUEUED

        else ->
            PatchStatus.QUEUED
    }

    return PatchActivity(
        id = id.toString(),
        patchNumber = "#$id",
        repository = repo,
        status = patchStatus,
        timeAgo = formatTimeAgo(
            finishedAt ?: startedAt
        )
    )
}


@Composable
fun ActivityScreen(
    modifier: Modifier = Modifier,
    activityViewModel: ActivityViewModel = viewModel(),
    homeViewModel: HomeViewModel = viewModel()
) {

    val uiState by activityViewModel.uiState.collectAsState()
    val context = LocalContext.current
    var otpCode by remember { mutableStateOf("") }

    var selectedFilter by remember {
        mutableStateOf(ActivityFilter.ALL)
    }

    val filteredRuns = remember(
        uiState.runs,
        selectedFilter
    ) {

        when (selectedFilter) {

            ActivityFilter.ALL ->
                uiState.runs

            ActivityFilter.RUNNING ->
                uiState.runs.filter {
                    it.status.equals("running", ignoreCase = true) ||
                        it.status.equals("queued", ignoreCase = true) ||
                        it.status.equals("paused", ignoreCase = true) ||
                        it.status.equals("awaiting_patch_review", ignoreCase = true) ||
                        it.status.equals("awaiting_merge", ignoreCase = true)
                }

            ActivityFilter.COMPLETED ->
                uiState.runs.filter {
                    it.status.equals(
                        "completed",
                        ignoreCase = true
                    )
                }

            ActivityFilter.FAILED ->
                uiState.runs.filter {
                    it.status.equals("failed", ignoreCase = true) ||
                        it.status.equals("killed", ignoreCase = true) ||
                        it.status.equals("rejected", ignoreCase = true)
                }
        }
    }

    Column(
        modifier = modifier.fillMaxSize()
    ) {

        /*
         * Activity header + Refresh button
         */
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(
                    horizontal = 20.dp,
                    vertical = 16.dp
                ),
            horizontalArrangement =
                Arrangement.SpaceBetween,
            verticalAlignment =
                Alignment.CenterVertically
        ) {

            Column {

                Text(
                    text = "Activity",
                    style =
                        MaterialTheme.typography.headlineSmall,
                    color = TextPrimary
                )

                Spacer(
                    modifier = Modifier.height(4.dp)
                )

                Text(
                    text =
                        "All patch runs across your repositories.",
                    style =
                        MaterialTheme.typography.bodySmall,
                    color = TextSecondary
                )
            }

            TextButton(
                onClick = {
                    activityViewModel.loadActivity()
                },
                enabled = !uiState.isLoading
            ) {

                Text(
                    text = "Refresh",
                    color = AccentPrimary
                )
            }
        }

        val running = uiState.runs.firstOrNull {
            it.status.equals("running", true) ||
                it.status.equals("paused", true) ||
                it.controlState.equals("paused", true)
        }
        if (running != null) {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 20.dp, vertical = 8.dp)
            ) {
                Text(
                    text = "Remote control #${running.id}",
                    color = TextPrimary,
                    style = MaterialTheme.typography.titleSmall
                )
                OutlinedTextField(
                    value = otpCode,
                    onValueChange = { otpCode = it.filter { ch -> ch.isDigit() }.take(6) },
                    label = { Text("OTP") },
                    singleLine = true
                )
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    TextButton(onClick = {
                        homeViewModel.controlRun(context, running.id, "pause", otpCode)
                    }) { Text("Pause") }
                    TextButton(onClick = {
                        homeViewModel.controlRun(context, running.id, "resume", otpCode)
                    }) { Text("Resume") }
                    TextButton(onClick = {
                        homeViewModel.controlRun(context, running.id, "kill", otpCode)
                    }) { Text("Kill") }
                }
            }
        }

        /*
         * Filters
         */
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 20.dp),
            horizontalArrangement =
                Arrangement.spacedBy(8.dp)
        ) {

            FilterOption(
                label = "All",
                selected =
                    selectedFilter == ActivityFilter.ALL
            ) {
                selectedFilter =
                    ActivityFilter.ALL
            }

            FilterOption(
                label = "Running",
                selected =
                    selectedFilter == ActivityFilter.RUNNING
            ) {
                selectedFilter =
                    ActivityFilter.RUNNING
            }

            FilterOption(
                label = "Completed",
                selected =
                    selectedFilter == ActivityFilter.COMPLETED
            ) {
                selectedFilter =
                    ActivityFilter.COMPLETED
            }

            FilterOption(
                label = "Failed",
                selected =
                    selectedFilter == ActivityFilter.FAILED
            ) {
                selectedFilter =
                    ActivityFilter.FAILED
            }
        }


        Spacer(
            modifier = Modifier.height(14.dp)
        )


        /*
         * Content states
         */
        when {

            uiState.isLoading -> {

                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .weight(1f),
                    contentAlignment =
                        Alignment.Center
                ) {

                    CircularProgressIndicator(
                        color = AccentPrimary
                    )
                }
            }


            uiState.error != null -> {

                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .weight(1f)
                        .padding(20.dp),
                    horizontalAlignment =
                        Alignment.CenterHorizontally,
                    verticalArrangement =
                        Arrangement.Center
                ) {

                    Text(
                        text = "Unable to load activity",
                        style =
                            MaterialTheme.typography.titleMedium,
                        color = TextPrimary
                    )

                    Spacer(
                        modifier = Modifier.height(6.dp)
                    )

                    Text(
                        text =
                            uiState.error
                                ?: "Unknown error",
                        style =
                            MaterialTheme.typography.bodySmall,
                        color = TextSecondary
                    )
                }
            }


            filteredRuns.isEmpty() -> {

                NoActivityYet()
            }


            else -> {

                LazyColumn(
                    modifier = Modifier.weight(1f),

                    contentPadding =
                        PaddingValues(
                            horizontal = 20.dp,
                            vertical = 4.dp
                        ),

                    verticalArrangement =
                        Arrangement.spacedBy(10.dp)
                ) {

                    items(
                        items = filteredRuns.distinctBy { it.id },
                        key = { it.id }
                    ) { run ->

                        Column(
                            verticalArrangement =
                                Arrangement.spacedBy(8.dp)
                        ) {
                            ActivityItem(
                                activity =
                                    run.toPatchActivity(),
                                onClick = {
                                    activityViewModel.selectRun(run.id)
                                }
                            )
                            if (uiState.selectedRunId == run.id) {
                                DiagnosisPanel(
                                    loading = uiState.diagnosisLoading,
                                    diagnosis = uiState.diagnosis,
                                    error = uiState.diagnosisError
                                )
                            }
                        }
                    }

                    item {

                        Spacer(
                            modifier =
                                Modifier.height(12.dp)
                        )
                    }
                }
            }
        }
    }
}


@Composable
private fun DiagnosisPanel(
    loading: Boolean,
    diagnosis: String?,
    error: String?
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .background(
                SurfaceElevation2,
                MaterialTheme.shapes.medium
            )
            .padding(14.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        Text(
            text = "Gemini diagnosis",
            style = MaterialTheme.typography.labelMedium,
            color = AccentPrimary
        )
        when {
            loading -> {
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(10.dp)
                ) {
                    CircularProgressIndicator(
                        modifier = Modifier.size(18.dp),
                        strokeWidth = 2.dp,
                        color = AccentPrimary
                    )
                    Text(
                        text = "Loading diagnosis…",
                        style = MaterialTheme.typography.bodySmall,
                        color = TextSecondary
                    )
                }
            }
            error != null -> {
                Text(
                    text = error,
                    style = MaterialTheme.typography.bodySmall,
                    color = TextSecondary
                )
            }
            diagnosis.isNullOrBlank() -> {
                Text(
                    text = "No diagnosis yet for this run.",
                    style = MaterialTheme.typography.bodySmall,
                    color = TextSecondary
                )
            }
            else -> {
                Text(
                    text = diagnosis,
                    style = MaterialTheme.typography.bodySmall,
                    color = TextPrimary
                )
            }
        }
    }
}


@Composable
private fun FilterOption(
    label: String,
    selected: Boolean,
    onClick: () -> Unit
) {

    FilterChip(
        selected = selected,
        onClick = onClick,

        label = {

            Text(
                text = label,
                style =
                    MaterialTheme.typography.labelMedium
            )
        },

        colors =
            FilterChipDefaults.filterChipColors(

                containerColor =
                    SurfaceElevation1,

                labelColor =
                    TextSecondary,

                selectedContainerColor =
                    AccentPrimaryMuted,

                selectedLabelColor =
                    AccentPrimary
            )
    )
}