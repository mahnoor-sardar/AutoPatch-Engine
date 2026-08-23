package com.mahify.autopatch

import android.os.Bundle
import android.provider.Settings
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.google.firebase.messaging.FirebaseMessaging
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody

class MainActivity : ComponentActivity() {
    private val http = OkHttpClient()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val deviceId = Settings.Secure.getString(contentResolver, Settings.Secure.ANDROID_ID) ?: "unknown"
        setContent {
            MaterialTheme {
                Surface(modifier = Modifier.fillMaxSize()) {
                    val scope = rememberCoroutineScope()
                    var backend by remember { mutableStateOf("http://10.0.2.2:8000") }
                    var label by remember { mutableStateOf("dev-device") }
                    var apiKey by remember { mutableStateOf("dev-local-key") }
                    var fcmToken by remember { mutableStateOf("") }
                    var status by remember { mutableStateOf("Waiting for FCM token…") }

                    LaunchedEffect(Unit) {
                        FirebaseMessaging.getInstance().token.addOnCompleteListener { task ->
                            fcmToken = if (task.isSuccessful) task.result else ""
                            status = if (task.isSuccessful) "FCM token ready" else (task.exception?.message ?: "FCM failed")
                        }
                    }

                    Column(
                        modifier = Modifier.padding(16.dp),
                        verticalArrangement = Arrangement.spacedBy(12.dp),
                    ) {
                        Text("AutoPatch companion", style = MaterialTheme.typography.headlineSmall)
                        Text("Device ID: $deviceId")
                        OutlinedTextField(backend, { backend = it }, label = { Text("Backend URL") }, modifier = Modifier.fillMaxWidth())
                        OutlinedTextField(label, { label = it }, label = { Text("Device label") }, modifier = Modifier.fillMaxWidth())
                        OutlinedTextField(apiKey, { apiKey = it }, label = { Text("API key") }, modifier = Modifier.fillMaxWidth())
                        Button(onClick = {
                            status = "Registering…"
                            val url = "$backend/v1/devices/register"
                            val payload = JSONObject()
                                .put("device_id", deviceId)
                                .put("fcm_token", fcmToken)
                                .put("label", label)
                                .toString()
                            scope.launch {
                                status = withContext(Dispatchers.IO) { postJson(url, payload) }
                            }
                        }) { Text("Register device") }
                        Button(onClick = {
                            status = "Sending test push…"
                            val url = "$backend/v1/devices/$deviceId/test-push"
                            val key = apiKey
                            scope.launch {
                                status = withContext(Dispatchers.IO) { postJson(url, "{}", key) }
                            }
                        }) { Text("Send test push") }
                        Text(status)
                        Text("Last FCM payload: ${PushService.lastPayload}")
                    }
                }
            }
        }
    }

    private fun postJson(url: String, json: String, apiKey: String? = null): String {
        return try {
            val req = Request.Builder()
                .url(url)
                .post(json.toRequestBody("application/json".toMediaType()))
                .apply { if (apiKey != null) addHeader("X-API-Key", apiKey) }
                .build()
            http.newCall(req).execute().use { resp ->
                "${resp.code} ${resp.body?.string()}"
            }
        } catch (e: Exception) {
            e.message ?: "request failed"
        }
    }
}
