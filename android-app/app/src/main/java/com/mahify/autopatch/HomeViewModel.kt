package com.mahify.autopatch

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.google.firebase.messaging.FirebaseMessaging
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

data class HomeUiState(
    val backendOnline: Boolean = false,
    val postgresOnline: Boolean = false,
    val redisOnline: Boolean = false,
    val firebaseOnline: Boolean = false,

    val totalRuns: Int = 0,
    val successfulRuns: Int = 0,
    val runningRuns: Int = 0,
    val failedRuns: Int = 0,

    val recentRuns: List<SandboxRun> = emptyList(),

    val isLoading: Boolean = true,
    val error: String? = null
)

class HomeViewModel : ViewModel() {

    private val _uiState = MutableStateFlow(HomeUiState())

    val uiState: StateFlow<HomeUiState> =
        _uiState.asStateFlow()

    init {
        refresh()
        checkFirebase()
    }

    fun refresh() {
        viewModelScope.launch {

            _uiState.value = _uiState.value.copy(
                isLoading = true,
                error = null
            )

            try {
                val health = ApiClient.getHealth()
                val sandbox = ApiClient.getSandboxRuns()

                _uiState.value = _uiState.value.copy(
                    backendOnline = health.ok,
                    postgresOnline = health.postgres,
                    redisOnline = health.redis,

                    totalRuns = sandbox.stats.total,
                    successfulRuns = sandbox.stats.successful,
                    runningRuns = sandbox.stats.running,
                    failedRuns = sandbox.stats.failed,

                    recentRuns = sandbox.runs,

                    isLoading = false,
                    error = null
                )

                checkFirebase()

            } catch (e: Exception) {

                _uiState.value = _uiState.value.copy(
                    backendOnline = false,
                    postgresOnline = false,
                    redisOnline = false,
                    isLoading = false,
                    error = e.message
                        ?: "Unable to connect to backend"
                )

                checkFirebase()
            }
        }
    }

    private fun checkFirebase() {
        FirebaseMessaging.getInstance()
            .token
            .addOnCompleteListener { task ->

                _uiState.value = _uiState.value.copy(
                    firebaseOnline = task.isSuccessful &&
                        !task.result.isNullOrBlank()
                )
            }
    }

    fun refreshHealth() {
        refresh()
    }
}