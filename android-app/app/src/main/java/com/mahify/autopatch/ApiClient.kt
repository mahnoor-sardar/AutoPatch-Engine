package com.mahify.autopatch

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request

data class BackendHealth(
    val ok: Boolean,
    val postgres: Boolean,
    val redis: Boolean
)

object ApiClient {

    private const val BASE_URL = "http://192.168.18.36:8000"

    private val client = OkHttpClient()

    suspend fun getHealth(): BackendHealth = withContext(Dispatchers.IO) {
        val request = Request.Builder()
            .url("$BASE_URL/health")
            .get()
            .build()

        client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) {
                throw Exception("Backend returned HTTP ${response.code}")
            }

            val body = response.body?.string()
                ?: throw Exception("Empty backend response")

            val ok = Regex("\"ok\"\\s*:\\s*(true|false)")
                .find(body)
                ?.groupValues
                ?.get(1)
                ?.toBoolean()
                ?: false

            val postgres = Regex("\"postgres\"\\s*:\\s*(true|false)")
                .find(body)
                ?.groupValues
                ?.get(1)
                ?.toBoolean()
                ?: false

            val redis = Regex("\"redis\"\\s*:\\s*(true|false)")
                .find(body)
                ?.groupValues
                ?.get(1)
                ?.toBoolean()
                ?: false

            BackendHealth(
                ok = ok,
                postgres = postgres,
                redis = redis
            )
        }
    }
}