package com.mahify.autopatch.ui.navigation

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Scaffold
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.lifecycle.viewmodel.compose.viewModel
import com.mahify.autopatch.HomeViewModel
import com.mahify.autopatch.model.HealthState
import com.mahify.autopatch.ui.components.AppBottomNav
import com.mahify.autopatch.ui.components.AppDestination
import com.mahify.autopatch.ui.components.AppTopBar
import com.mahify.autopatch.ui.screens.ActivityScreen
import com.mahify.autopatch.ui.screens.HomeScreen
import com.mahify.autopatch.ui.screens.RepositoriesScreen
import com.mahify.autopatch.ui.screens.SettingsScreen

@Composable
fun AutoPatchApp(homeViewModel: HomeViewModel = viewModel()) {

    var currentDestination by remember {
        mutableStateOf(AppDestination.HOME)
    }

    Scaffold(

        topBar = {
            AppTopBar(
                connectionHealth = HealthState.ONLINE,
                hasUnreadNotifications = true,
                onNotificationsClick = {
                    // TODO: Open notifications
                },
                onSettingsClick = {
                    currentDestination = AppDestination.SETTINGS
                }
            )
        },

        bottomBar = {
            Box(
                modifier = Modifier.navigationBarsPadding()
            ) {
                AppBottomNav(
                    current = currentDestination,
                    onSelect = {
                        currentDestination = it
                    }
                )
            }
        }

    ) { innerPadding ->

        when (currentDestination) {

            AppDestination.HOME -> {
                HomeScreen(
                    onViewAllActivity = {
                        currentDestination = AppDestination.ACTIVITY
                    },
                    onViewRepositories = {
                        currentDestination = AppDestination.REPOSITORIES
                    },
                    onOpenNotifications = {
                        // TODO: Open notifications
                    },
                    modifier = Modifier.padding(innerPadding),
                    homeViewModel = homeViewModel
                )
            }

            AppDestination.ACTIVITY -> {
                ActivityScreen(
                    modifier = Modifier.padding(innerPadding)
                )
            }

            AppDestination.REPOSITORIES -> {
                RepositoriesScreen(
                    modifier = Modifier.padding(innerPadding)
                )
            }

            AppDestination.SETTINGS -> {
                SettingsScreen(
                    modifier = Modifier.padding(innerPadding),
                    homeViewModel = homeViewModel
                )
            }
        }
    }
}