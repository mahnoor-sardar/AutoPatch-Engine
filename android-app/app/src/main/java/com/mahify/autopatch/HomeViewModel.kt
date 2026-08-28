package com.mahify.autopatch

import android.content.Context
import android.os.Build
import android.provider.Settings
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

    val pendingApprovals: List<com.mahify.autopatch.model.ApprovalRequest> = emptyList(),
    val approvalLoading: Boolean = false,
    val approvalError: String? = null,

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

            // Approval loading is triggered by HomeScreen
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

    private fun getDeviceId(context: Context): String {
        return Settings.Secure.getString(
            context.contentResolver,
            Settings.Secure.ANDROID_ID
        ) ?: ""
    }

    fun loadPendingApproval(context: Context) {
        viewModelScope.launch {

            try {
                val deviceId = getDeviceId(context)

                if (deviceId.isBlank()) {
                    return@launch
                }

                val approvals = ApprovalSubmit.newestRunFirst(
                    ApiClient.getPendingApprovals(deviceId)
                )

                _uiState.value = _uiState.value.copy(
                    pendingApprovals = approvals,
                    approvalError = null
                )

            } catch (e: Exception) {

                _uiState.value = _uiState.value.copy(
                    approvalError =
                        e.message ?: "Unable to load approval"
                )
            }
        }
    }

    fun approvePendingApproval(
        context: Context,
        displayed: com.mahify.autopatch.model.ApprovalRequest,
        otpCode: String
    ) {
        submitApproval(context, displayed = displayed, otpCode = otpCode)
    }

    fun rejectPendingApproval(
        context: Context,
        displayed: com.mahify.autopatch.model.ApprovalRequest,
        otpCode: String
    ) {
        val submitRunId = ApprovalSubmit.runIdForDisplayedRequest(displayed)
        val trimmedOtp = otpCode.trim()
        if (!trimmedOtp.matches(Regex("^\\d{6}$"))) {
            _uiState.value = _uiState.value.copy(
                approvalError = "Enter a valid 6-digit OTP"
            )
            return
        }
        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(approvalLoading = true)
            try {
                ApiClient.rejectSandbox(
                    submitRunId,
                    getDeviceId(context),
                    trimmedOtp
                )
                _uiState.value = _uiState.value.copy(
                    pendingApprovals = _uiState.value.pendingApprovals
                        .filterNot { it.runId == submitRunId },
                    approvalLoading = false
                )
                refresh()
                loadPendingApproval(context)
            } catch (e: Exception) {
                _uiState.value = _uiState.value.copy(
                    approvalLoading = false,
                    approvalError = e.message ?: "Reject failed"
                )
            }
        }
    }

    fun approveWithStoredSecret(
        context: Context,
        displayed: com.mahify.autopatch.model.ApprovalRequest
    ) {
        val secret = DevicePrefs.totpSecret(context)
        if (secret.isNullOrBlank()) {
            _uiState.value = _uiState.value.copy(
                approvalError = "TOTP secret is not stored on this device"
            )
            return
        }
        submitApproval(
            context,
            displayed = displayed,
            otpCode = Totp.currentCode(secret)
        )
    }

    fun approveWithSignedToken(
        context: Context,
        displayed: com.mahify.autopatch.model.ApprovalRequest
    ) {
        val submitRunId = ApprovalSubmit.runIdForDisplayedRequest(displayed)
        val gate = displayed.gate
        val secret = DevicePrefs.totpSecret(context)
        val deviceId = getDeviceId(context)
        if (secret.isNullOrBlank()) {
            _uiState.value = _uiState.value.copy(
                approvalError = "TOTP secret is not stored on this device"
            )
            return
        }
        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(approvalLoading = true)
            try {
                val ts = System.currentTimeMillis() / 1000L
                val payload = "$deviceId|$submitRunId|$gate"
                ApiClient.approveWithToken(
                    submitRunId,
                    deviceId,
                    Totp.approvalToken(secret, payload, ts),
                    ts
                )
                _uiState.value = _uiState.value.copy(
                    pendingApprovals = _uiState.value.pendingApprovals
                        .filterNot { it.runId == submitRunId },
                    approvalLoading = false
                )
                refresh()
                loadPendingApproval(context)
            } catch (e: Exception) {
                _uiState.value = _uiState.value.copy(
                    approvalLoading = false,
                    approvalError = e.message ?: "Approval failed"
                )
            }
        }
    }

    fun controlRun(context: Context, runId: Int, action: String, otpCode: String) {
        viewModelScope.launch {
            try {
                ApiClient.controlRun(
                    runId,
                    action,
                    getDeviceId(context),
                    otpCode.trim()
                )
                refresh()
                loadPendingApproval(context)
            } catch (e: Exception) {
                _uiState.value = _uiState.value.copy(
                    error = e.message ?: "Control failed"
                )
            }
        }
    }

    private fun submitApproval(
        context: Context,
        displayed: com.mahify.autopatch.model.ApprovalRequest,
        otpCode: String
    ) {
        val submitRunId = ApprovalSubmit.runIdForDisplayedRequest(displayed)

        val trimmedOtp = otpCode.trim()

        if (!trimmedOtp.matches(Regex("^\\d{6}$"))) {
            _uiState.value = _uiState.value.copy(
                approvalError = "Enter a valid 6-digit OTP"
            )
            return
        }

        viewModelScope.launch {

            _uiState.value = _uiState.value.copy(
                approvalLoading = true,
                approvalError = null
            )

            try {
                val deviceId = getDeviceId(context)

                ApiClient.approveSandbox(
                    runId = submitRunId,
                    deviceId = deviceId,
                    otpCode = trimmedOtp
                )

                _uiState.value = _uiState.value.copy(
                    pendingApprovals = _uiState.value.pendingApprovals
                        .filterNot { it.runId == submitRunId },
                    approvalLoading = false,
                    approvalError = null
                )

                refresh()
                loadPendingApproval(context)

            } catch (e: Exception) {

                _uiState.value = _uiState.value.copy(
                    approvalLoading = false,
                    approvalError =
                        e.message ?: "Approval failed"
                )
            }
        }
    }

    fun refreshHealth() {
        refresh()
    }

    fun setApprovalError(message: String) {
        _uiState.value = _uiState.value.copy(approvalError = message)
    }
}