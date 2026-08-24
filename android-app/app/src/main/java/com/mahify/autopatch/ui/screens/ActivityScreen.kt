package com.mahify.autopatch.ui.screens

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.mahify.autopatch.model.MockData
import com.mahify.autopatch.model.PatchStatus
import com.mahify.autopatch.ui.components.ActivityItem
import com.mahify.autopatch.ui.components.NoActivityYet
import com.mahify.autopatch.ui.theme.AccentPrimary
import com.mahify.autopatch.ui.theme.AccentPrimaryMuted
import com.mahify.autopatch.ui.theme.SurfaceElevation1
import com.mahify.autopatch.ui.theme.TextPrimary
import com.mahify.autopatch.ui.theme.TextSecondary

@Composable
fun ActivityScreen(modifier: Modifier = Modifier) {
    var selectedFilter by remember { mutableStateOf<PatchStatus?>(null) }

    val filtered = remember(selectedFilter) {
        if (selectedFilter == null) MockData.recentActivity
        else MockData.recentActivity.filter { it.status == selectedFilter }
    }

    Column(modifier = modifier.fillMaxSize()) {
        Column(modifier = Modifier.padding(horizontal = 20.dp, vertical = 16.dp)) {
            Text(text = "Activity", style = MaterialTheme.typography.headlineSmall, color = TextPrimary)
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
            FilterOption("All", selectedFilter == null) { selectedFilter = null }
            FilterOption("Running", selectedFilter == PatchStatus.RUNNING) { selectedFilter = PatchStatus.RUNNING }
            FilterOption("Completed", selectedFilter == PatchStatus.COMPLETED) { selectedFilter = PatchStatus.COMPLETED }
            FilterOption("Failed", selectedFilter == PatchStatus.FAILED) { selectedFilter = PatchStatus.FAILED }
        }

        Spacer(Modifier.height(14.dp))

        if (filtered.isEmpty()) {
            NoActivityYet()
        } else {
            LazyColumn(
                contentPadding = PaddingValues(horizontal = 20.dp, vertical = 4.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp)
            ) {
                items(filtered) { activity ->
                    ActivityItem(activity = activity)
                }
                item { Spacer(Modifier.height(12.dp)) }
            }
        }
    }
}

@Composable
private fun FilterOption(label: String, selected: Boolean, onClick: () -> Unit) {
    FilterChip(
        selected = selected,
        onClick = onClick,
        label = { Text(label, style = MaterialTheme.typography.labelMedium) },
        colors = FilterChipDefaults.filterChipColors(
            containerColor = SurfaceElevation1,
            labelColor = TextSecondary,
            selectedContainerColor = AccentPrimaryMuted,
            selectedLabelColor = AccentPrimary
        )
    )
}

