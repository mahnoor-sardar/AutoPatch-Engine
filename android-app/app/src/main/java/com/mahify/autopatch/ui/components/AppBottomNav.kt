package com.mahify.autopatch.ui.components

import androidx.compose.foundation.layout.height
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.List
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Storage
import androidx.compose.material.icons.outlined.Home
import androidx.compose.material.icons.outlined.List
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.material.icons.outlined.Storage
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.unit.dp
import com.mahify.autopatch.ui.theme.AccentPrimary
import com.mahify.autopatch.ui.theme.SurfaceElevation1
import com.mahify.autopatch.ui.theme.TextTertiary

enum class AppDestination(
    val label: String,
    val filledIcon: ImageVector,
    val outlinedIcon: ImageVector
) {
    HOME("Home", Icons.Filled.Home, Icons.Outlined.Home),
    ACTIVITY("Activity", Icons.Filled.List, Icons.Outlined.List),
    REPOSITORIES("Repos", Icons.Filled.Storage, Icons.Outlined.Storage),
    SETTINGS("Settings", Icons.Filled.Settings, Icons.Outlined.Settings)
}

@Composable
fun AppBottomNav(
    current: AppDestination,
    onSelect: (AppDestination) -> Unit,
    modifier: Modifier = Modifier
) {
    NavigationBar(
        modifier = modifier.height(64.dp),
        containerColor = SurfaceElevation1,
        tonalElevation = 0.dp
    ) {
        AppDestination.entries.forEach { destination ->
            val selected = destination == current
            NavigationBarItem(
                selected = selected,
                onClick = { onSelect(destination) },
                icon = {
                    Icon(
                        imageVector = if (selected) destination.filledIcon else destination.outlinedIcon,
                        contentDescription = destination.label
                    )
                },
                label = { Text(destination.label) },
                colors = NavigationBarItemDefaults.colors(
                    selectedIconColor = AccentPrimary,
                    selectedTextColor = AccentPrimary,
                    unselectedIconColor = TextTertiary,
                    unselectedTextColor = TextTertiary,
                    indicatorColor = SurfaceElevation1
                )
            )
        }
    }
}

