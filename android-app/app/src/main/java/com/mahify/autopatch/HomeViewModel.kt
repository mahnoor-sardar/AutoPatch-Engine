package com.mahify.autopatch

import android.app.Application
import android.content.Context
import android.provider.Settings
import android.util.Log
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.google.firebase.messaging.FirebaseMessaging
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

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

class HomeViewModel(application: Application) : AndroidViewModel(application) {

    private val _uiState = MutableStateFlow(HomeUiState())

    val uiState: StateFlow<HomeUiState> =
        _uiState.asStateFlow()

    private val refreshMutex = Mutex()
    private var lastHealthAtMs = 0L
    private var refreshInFlight = false
    private var approvalSubmitInFlight = false

    init {
        refresh()
        checkFirebase()
    }

    fun refresh() {
        viewModelScope.launch {
            refreshInternal(
                showLoading = _uiState.value.recentRuns.isEmpty(),
                includeHealth = true
            )
        }
    }

    fun pollForUpdates() {
        viewModelScope.launch {
            refreshInternal(showLoading = false, includeHealth = false)
        }
    }

    private suspend fun refreshInternal(
        showLoading: Boolean,
        includeHealth: Boolean,
        waitForLock: Boolean = false
    ) {
        if (waitForLock) {
            refreshMutex.lock()
        } else if (refreshInFlight || !refreshMutex.tryLock()) {
            Log.i(LOG_TAG, "skip refresh stacking inFlight=$refreshInFlight")
            return
        }
        refreshInFlight = true
        try {
            if (showLoading) {
                _uiState.value = _uiState.value.copy(
                    isLoading = true,
                    error = null
                )
            }

            loadPendingApprovalInternal(getApplication())

            try {
                val now = System.currentTimeMillis()
                val shouldCheckHealth =
                    includeHealth || now - lastHealthAtMs > 60_000L

                val health = if (shouldCheckHealth) {
                    lastHealthAtMs = now
                    ApiClient.getHealth()
                } else {
                    null
                }
                val sandbox = ApiClient.getSandboxRuns()

                _uiState.value = _uiState.value.copy(
                    backendOnline = health?.ok ?: _uiState.value.backendOnline,
                    postgresOnline = health?.postgres ?: _uiState.value.postgresOnline,
                    redisOnline = health?.redis ?: _uiState.value.redisOnline,
                    totalRuns = sandbox.stats.total,
                    successfulRuns = sandbox.stats.successful,
                    runningRuns = sandbox.stats.running,
                    failedRuns = sandbox.stats.failed,
                    recentRuns = sandbox.runs,
                    isLoading = false,
                    error = null
                )

                if (shouldCheckHealth) {
                    checkFirebase()
                }
            } catch (e: Exception) {
                _uiState.value = _uiState.value.copy(
                    backendOnline = if (includeHealth) false else _uiState.value.backendOnline,
                    postgresOnline = if (includeHealth) false else _uiState.value.postgresOnline,
                    redisOnline = if (includeHealth) false else _uiState.value.redisOnline,
                    isLoading = false,
                    error = e.message ?: "Unable to connect to backend"
                )
                if (includeHealth) {
                    checkFirebase()
                }
            }
        } finally {
            refreshInFlight = false
            refreshMutex.unlock()
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
            refreshMutex.withLock {
                loadPendingApprovalInternal(context)
            }
        }
    }

    private suspend fun loadPendingApprovalInternal(context: Context) {
        try {
            val deviceId = getDeviceId(context)
            Log.i(LOG_TAG, "loadPending deviceId=$deviceId")
            if (deviceId.isBlank()) {
                _uiState.value = _uiState.value.copy(
                    approvalError = "Unable to determine Android device ID"
                )
                return
            }
            val approvals = ApprovalSubmit.newestRunFirst(
                ApiClient.getPendingApprovals(deviceId)
            )
            Log.i(
                LOG_TAG,
                "HomeUiState pendingApprovals=${approvals.size} runIds=${approvals.map { it.runId }}"
            )
            _uiState.value = _uiState.value.copy(
                pendingApprovals = approvals,
                approvalError = null
            )
        } catch (e: Exception) {
            val message = e.message ?: "Unable to load pending approvals"
            Log.e(LOG_TAG, "HomeUiState approvalError=$message", e)
            _uiState.value = _uiState.value.copy(
                approvalError = message,
                pendingApprovals = _uiState.value.pendingApprovals
            )
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
        if (approvalSubmitInFlight || _uiState.value.approvalLoading) {
            return
        }
        viewModelScope.launch {
            if (approvalSubmitInFlight) return@launch
            approvalSubmitInFlight = true
            _uiState.value = _uiState.value.copy(approvalLoading = true)
            try {
                refreshMutex.withLock {
                    ApiClient.rejectSandbox(
                        submitRunId,
                        getDeviceId(context),
                        trimmedOtp
                    )
                    _uiState.value = _uiState.value.copy(
                        pendingApprovals = _uiState.value.pendingApprovals
                            .filterNot {
                                ApprovalSubmit.itemKey(it) ==
                                    ApprovalSubmit.itemKey(displayed)
                            },
                        approvalLoading = false
                    )
                }
                refreshInternal(
                    showLoading = false,
                    includeHealth = false,
                    waitForLock = true
                )
            } catch (e: Exception) {
                _uiState.value = _uiState.value.copy(
                    approvalLoading = false,
                    approvalError = e.message ?: "Reject failed"
                )
            } finally {
                approvalSubmitInFlight = false
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
        if (approvalSubmitInFlight || _uiState.value.approvalLoading) {
            return
        }
        viewModelScope.launch {
            if (approvalSubmitInFlight) return@launch
            approvalSubmitInFlight = true
            _uiState.value = _uiState.value.copy(approvalLoading = true)
            try {
                val ts = System.currentTimeMillis() / 1000L
                val payload = "$deviceId|$submitRunId|$gate"
                refreshMutex.withLock {
                    ApiClient.approveWithToken(
                        submitRunId,
                        deviceId,
                        Totp.approvalToken(secret, payload, ts),
                        ts
                    )
                    _uiState.value = _uiState.value.copy(
                        pendingApprovals = _uiState.value.pendingApprovals
                            .filterNot {
                                ApprovalSubmit.itemKey(it) ==
                                    ApprovalSubmit.itemKey(displayed)
                            },
                        approvalLoading = false
                    )
                }
                refreshInternal(
                    showLoading = false,
                    includeHealth = false,
                    waitForLock = true
                )
            } catch (e: Exception) {
                _uiState.value = _uiState.value.copy(
                    approvalLoading = false,
                    approvalError = e.message ?: "Approval failed"
                )
            } finally {
                approvalSubmitInFlight = false
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

        if (approvalSubmitInFlight || _uiState.value.approvalLoading) {
            return
        }

        viewModelScope.launch {
            if (approvalSubmitInFlight) return@launch
            approvalSubmitInFlight = true
            _uiState.value = _uiState.value.copy(
                approvalLoading = true,
                approvalError = null
            )

            try {
                val deviceId = getDeviceId(context)
                refreshMutex.withLock {
                    ApiClient.approveSandbox(
                        runId = submitRunId,
                        deviceId = deviceId,
                        otpCode = trimmedOtp
                    )
                    _uiState.value = _uiState.value.copy(
                        pendingApprovals = _uiState.value.pendingApprovals
                            .filterNot {
                                ApprovalSubmit.itemKey(it) ==
                                    ApprovalSubmit.itemKey(displayed)
                            },
                        approvalLoading = false,
                        approvalError = null
                    )
                }
                refreshInternal(
                    showLoading = false,
                    includeHealth = false,
                    waitForLock = true
                )
            } catch (e: Exception) {
                _uiState.value = _uiState.value.copy(
                    approvalLoading = false,
                    approvalError =
                        e.message ?: "Approval failed"
                )
            } finally {
                approvalSubmitInFlight = false
            }
        }
    }

    fun refreshHealth() {
        refresh()
    }

    fun setApprovalError(message: String) {
        _uiState.value = _uiState.value.copy(approvalError = message)
    }

    companion object {
        private const val LOG_TAG = "AutoPatchApproval"
    }
}
