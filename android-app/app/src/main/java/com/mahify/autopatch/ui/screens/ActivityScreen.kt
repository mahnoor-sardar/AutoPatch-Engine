package com.mahify.autopatch.ui.screens
import com.mahify.autopatch.model.PatchActivity
import com.mahify.autopatch.model.PatchStatus

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import com.mahify.autopatch.ApiClient
import com.mahify.autopatch.SandboxRun
import com.mahify.autopatch.ui.components.ActivityItem
import com.mahify.autopatch.ui.components.NoActivityYet
import com.mahify.autopatch.ui.theme.AccentPrimary
import com.mahify.autopatch.ui.theme.AccentPrimaryMuted
import com.mahify.autopatch.ui.theme.SurfaceElevation1
import com.mahify.autopatch.ui.theme.TextPrimary
import com.mahify.autopatch.ui.theme.TextSecondary
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

enum class ActivityFilter {
    ALL,
    RUNNING,
    COMPLETED,
    FAILED
}

data class ActivityUiState(
    val runs: List<SandboxRun> = emptyList(),
    val isLoading: Boolean = true,
    val error: String? = null
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

                _uiState.value = ActivityUiState(
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
}

private fun SandboxRun.toPatchActivity(): PatchActivity {
    val patchStatus = when (status.lowercase()) {
        "completed" -> PatchStatus.COMPLETED
        "running" -> PatchStatus.RUNNING
        "failed" -> PatchStatus.FAILED
        "queued" -> PatchStatus.QUEUED
        else -> PatchStatus.QUEUED
    }

    return PatchActivity(
        id = id.toString(),
        patchNumber = "#$id",
        repository = repo,
        status = patchStatus,
        timeAgo = finishedAt
            ?: startedAt
            ?: "No timestamp"
    )
}

@Composable
fun ActivityScreen(
    modifier: Modifier = Modifier,
    activityViewModel: ActivityViewModel = viewModel()
) {
    val uiState by activityViewModel.uiState.collectAsState()

    var selectedFilter by remember {
        mutableStateOf(ActivityFilter.ALL)
    }

    val filteredRuns = remember(
        uiState.runs,
        selectedFilter
    ) {
        when (selectedFilter) {
            ActivityFilter.ALL -> uiState.runs

            ActivityFilter.RUNNING -> uiState.runs.filter {
                it.status.equals("running", ignoreCase = true) ||
                    it.status.equals("queued", ignoreCase = true)
            }

            ActivityFilter.COMPLETED -> uiState.runs.filter {
                it.status.equals("completed", ignoreCase = true)
            }

            ActivityFilter.FAILED -> uiState.runs.filter {
                it.status.equals("failed", ignoreCase = true)
            }
        }
    }

    Column(
        modifier = modifier.fillMaxSize()
    ) {
        Column(
            modifier = Modifier.padding(
                horizontal = 20.dp,
                vertical = 16.dp
            )
        ) {
            Text(
                text = "Activity",
                style = MaterialTheme.typography.headlineSmall,
                color = TextPrimary
            )

            Spacer(Modifier.height(4.dp))

            Text(
                text = "All patch runs across your repositories.",
                style = MaterialTheme.typography.bodySmall,
                color = TextSecondary
            )
        }

        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 20.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            FilterOption(
                label = "All",
                selected = selectedFilter == ActivityFilter.ALL
            ) {
                selectedFilter = ActivityFilter.ALL
            }

            FilterOption(
                label = "Running",
                selected = selectedFilter == ActivityFilter.RUNNING
            ) {
                selectedFilter = ActivityFilter.RUNNING
            }

            FilterOption(
                label = "Completed",
                selected = selectedFilter == ActivityFilter.COMPLETED
            ) {
                selectedFilter = ActivityFilter.COMPLETED
            }

            FilterOption(
                label = "Failed",
                selected = selectedFilter == ActivityFilter.FAILED
            ) {
                selectedFilter = ActivityFilter.FAILED
            }
        }

        Spacer(Modifier.height(14.dp))

        when {
            uiState.isLoading -> {
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .weight(1f),
                    contentAlignment = Alignment.Center
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
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.Center
                ) {
                    Text(
                        text = "Unable to load activity",
                        style = MaterialTheme.typography.titleMedium,
                        color = TextPrimary
                    )

                    Spacer(Modifier.height(6.dp))

                    Text(
                        text = uiState.error ?: "Unknown error",
                        style = MaterialTheme.typography.bodySmall,
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
                    contentPadding = PaddingValues(
                        horizontal = 20.dp,
                        vertical = 4.dp
                    ),
                    verticalArrangement = Arrangement.spacedBy(10.dp)
                ) {
                    items(
                        items = filteredRuns,
                        key = { it.id }
                    ) { run ->
                        ActivityItem(
                            activity = run.toPatchActivity()
                        )
                    }

                    item {
                        Spacer(Modifier.height(12.dp))
                    }
                }
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
                label,
                style = MaterialTheme.typography.labelMedium
            )
        },
        colors = FilterChipDefaults.filterChipColors(
            containerColor = SurfaceElevation1,
            labelColor = TextSecondary,
            selectedContainerColor = AccentPrimaryMuted,
            selectedLabelColor = AccentPrimary
        )
    )
}