package com.mahify.autopatch

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

data class HomeUiState(
    val backendOnline: Boolean = false,
    val postgresOnline: Boolean = false,
    val redisOnline: Boolean = false,
    val isLoading: Boolean = true,
    val error: String? = null
)

class HomeViewModel : ViewModel() {

    private val _uiState = MutableStateFlow(HomeUiState())
    val uiState: StateFlow<HomeUiState> = _uiState.asStateFlow()

    init {
        refreshHealth()
    }

    fun refreshHealth() {
        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(
                isLoading = true,
                error = null
            )

            try {
                val health = ApiClient.getHealth()

                _uiState.value = HomeUiState(
                    backendOnline = health.ok,
                    postgresOnline = health.postgres,
                    redisOnline = health.redis,
                    isLoading = false
                )
            } catch (e: Exception) {
                _uiState.value = HomeUiState(
                    backendOnline = false,
                    postgresOnline = false,
                    redisOnline = false,
                    isLoading = false,
                    error = e.message ?: "Unable to connect to backend"
                )
            }
        }
    }
}