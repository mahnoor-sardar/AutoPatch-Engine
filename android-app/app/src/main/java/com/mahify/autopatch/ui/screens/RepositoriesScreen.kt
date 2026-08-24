package com.mahify.autopatch.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Storage
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.mahify.autopatch.model.MockData
import com.mahify.autopatch.model.PatchStatus
import com.mahify.autopatch.ui.components.StatusBadge
import com.mahify.autopatch.model.HealthState
import com.mahify.autopatch.ui.theme.AccentPrimaryMuted
import com.mahify.autopatch.ui.theme.AccentPrimary
import com.mahify.autopatch.ui.theme.BorderSubtle
import com.mahify.autopatch.ui.theme.SurfaceElevation1
import com.mahify.autopatch.ui.theme.TextPrimary
import com.mahify.autopatch.ui.theme.TextSecondary

private data class RepoSummary(
    val name: String,
    val lastRun: String,
    val patchCount: Int,
    val health: HealthState
)

@Composable
fun RepositoriesScreen(modifier: Modifier = Modifier) {
    // Derived from mock activity — grouped by repository name.
    val repos = deriveRepoSummaries()

    Column(modifier = modifier.fillMaxSize()) {
        Column(modifier = Modifier.padding(horizontal = 20.dp, vertical = 16.dp)) {
            Text(text = "Repositories", style = MaterialTheme.typography.headlineSmall, color = TextPrimary)
            Spacer(Modifier.height(4.dp))
            Text(
                text = "Repositories AutoPatch Engine is watching.",
                style = MaterialTheme.typography.bodySmall,
                color = TextSecondary
            )
        }

        LazyColumn(
            contentPadding = PaddingValues(horizontal = 20.dp, vertical = 4.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            items(repos) { repo ->
                RepoCard(repo)
            }
            item { Spacer(Modifier.height(12.dp)) }
        }
    }
}

@Composable
private fun RepoCard(repo: RepoSummary) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .background(SurfaceElevation1, MaterialTheme.shapes.medium)
            .border(1.dp, BorderSubtle, MaterialTheme.shapes.medium)
            .padding(14.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Box(
            modifier = Modifier
                .size(36.dp)
                .background(AccentPrimaryMuted, CircleShape),
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
        Column(modifier = Modifier.weight(1f)) {
            Text(text = repo.name, style = MaterialTheme.typography.titleSmall, color = TextPrimary)
            Spacer(Modifier.height(2.dp))
            Text(
                text = "${repo.patchCount} patch${if (repo.patchCount == 1) "" else "es"} · last run ${repo.lastRun}",
                style = MaterialTheme.typography.labelSmall,
                color = TextSecondary
            )
        }
        StatusBadge(
            label = when (repo.health) {
                HealthState.ONLINE -> "Healthy"
                HealthState.DEGRADED -> "Running"
                HealthState.OFFLINE -> "Failing"
                HealthState.UNKNOWN -> "Unknown"
            },
            health = repo.health
        )
    }
}

private fun deriveRepoSummaries(): List<RepoSummary> {
    val grouped = MockData.recentActivity.groupBy { it.repository }
    return grouped.map { (name, runs) ->
        val newest = runs.first()
        val health = when (newest.status) {
            PatchStatus.COMPLETED -> HealthState.ONLINE
            PatchStatus.RUNNING -> HealthState.DEGRADED
            PatchStatus.FAILED -> HealthState.OFFLINE
            PatchStatus.QUEUED -> HealthState.UNKNOWN
        }
        RepoSummary(
            name = name,
            lastRun = newest.timeAgo,
            patchCount = runs.size,
            health = health
        )
    }
}

