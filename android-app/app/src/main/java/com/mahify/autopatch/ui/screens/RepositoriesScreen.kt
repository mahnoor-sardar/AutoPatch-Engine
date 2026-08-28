package com.mahify.autopatch.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material.icons.outlined.Storage
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import com.mahify.autopatch.ApiClient
import com.mahify.autopatch.GitHubRepository
import com.mahify.autopatch.ui.theme.AccentPrimary
import com.mahify.autopatch.ui.theme.AccentPrimaryMuted
import com.mahify.autopatch.ui.theme.BorderSubtle
import com.mahify.autopatch.ui.theme.SurfaceElevation1
import com.mahify.autopatch.ui.theme.TextPrimary
import com.mahify.autopatch.ui.theme.TextSecondary
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

data class RepositoriesUiState(
    val repositories: List<GitHubRepository> = emptyList(),
    val isLoading: Boolean = true,
    val error: String? = null,
    val notice: String? = null
)

class RepositoriesViewModel : ViewModel() {

    private val _uiState = MutableStateFlow(RepositoriesUiState())
    val uiState: StateFlow<RepositoriesUiState> =
        _uiState.asStateFlow()

    init {
        loadRepositories()
    }

    fun loadRepositories() {
        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(
                isLoading = true,
                error = null
            )

            try {
                val repositories = ApiClient.getRepositories()

                _uiState.value = RepositoriesUiState(
                    repositories = repositories,
                    isLoading = false
                )
            } catch (e: Exception) {
                _uiState.value = RepositoriesUiState(
                    isLoading = false,
                    error = e.message
                        ?: "Unable to load repositories"
                )
            }
        }
    }

    fun queueRun(repo: GitHubRepository) {
        viewModelScope.launch {
            try {
                ApiClient.createSandboxRun(repo.fullName, repo.defaultBranch)
                _uiState.value = _uiState.value.copy(
                    notice = "Queued run for ${repo.fullName}"
                )
            } catch (e: Exception) {
                _uiState.value = _uiState.value.copy(
                    error = e.message ?: "Unable to queue run"
                )
            }
        }
    }
}

@Composable
fun RepositoriesScreen(
    modifier: Modifier = Modifier,
    repositoriesViewModel: RepositoriesViewModel = viewModel()
) {
    val uiState by repositoriesViewModel.uiState.collectAsState()

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
                text = "Repositories",
                style = MaterialTheme.typography.headlineSmall,
                color = TextPrimary
            )

            Spacer(Modifier.height(4.dp))

            Text(
                text = "Repositories AutoPatch Engine is watching.",
                style = MaterialTheme.typography.bodySmall,
                color = TextSecondary
            )
        }

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
                ErrorState(
                    message = uiState.error,
                    onRetry = repositoriesViewModel::loadRepositories,
                    modifier = Modifier.weight(1f)
                )
            }

            uiState.repositories.isEmpty() -> {
                EmptyState(
                    modifier = Modifier.weight(1f)
                )
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
                        uiState.repositories.distinctBy { it.fullName },
                        key = { it.fullName }
                    ) { repo ->
                        RepoCard(
                            repo = repo,
                            onQueue = { repositoriesViewModel.queueRun(repo) }
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
private fun RepoCard(
    repo: GitHubRepository,
    onQueue: () -> Unit
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .background(
                SurfaceElevation1,
                MaterialTheme.shapes.medium
            )
            .border(
                1.dp,
                BorderSubtle,
                MaterialTheme.shapes.medium
            )
            .padding(14.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Box(
            modifier = Modifier
                .size(36.dp)
                .background(
                    AccentPrimaryMuted,
                    CircleShape
                ),
            contentAlignment = Alignment.Center
        ) {
            Icon(
                imageVector = Icons.Outlined.Storage,
                contentDescription = null,
                tint = AccentPrimary,
                modifier = Modifier.size(18.dp)
            )
        }

        Spacer(Modifier.width(12.dp))

        Column(
            modifier = Modifier.weight(1f)
        ) {
            Text(
                text = repo.fullName,
                style = MaterialTheme.typography.titleSmall,
                color = TextPrimary
            )

            Spacer(Modifier.height(2.dp))

            Text(
                text = "Default branch: ${repo.defaultBranch}",
                style = MaterialTheme.typography.labelSmall,
                color = TextSecondary
            )
        }

        Button(onClick = onQueue) {
            Text("Queue")
        }
    }
}

@Composable
private fun ErrorState(
    message: String?,
    onRetry: () -> Unit,
    modifier: Modifier = Modifier
) {
    Column(
        modifier = modifier
            .fillMaxWidth()
            .padding(20.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center
    ) {
        Text(
            text = "Unable to load repositories",
            style = MaterialTheme.typography.titleMedium,
            color = TextPrimary
        )

        Spacer(Modifier.height(6.dp))

        Text(
            text = message ?: "Unknown error",
            style = MaterialTheme.typography.bodySmall,
            color = TextSecondary
        )

        Spacer(Modifier.height(16.dp))

        Button(
            onClick = onRetry
        ) {
            Icon(
                imageVector = Icons.Outlined.Refresh,
                contentDescription = null
            )

            Spacer(Modifier.width(8.dp))

            Text("Retry")
        }
    }
}

@Composable
private fun EmptyState(
    modifier: Modifier = Modifier
) {
    Column(
        modifier = modifier
            .fillMaxWidth()
            .padding(20.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center
    ) {
        Text(
            text = "No repositories found",
            style = MaterialTheme.typography.titleMedium,
            color = TextPrimary
        )

        Spacer(Modifier.height(6.dp))

        Text(
            text = "Install the AutoPatch GitHub App on a repository to see it here.",
            style = MaterialTheme.typography.bodySmall,
            color = TextSecondary
        )
    }
}