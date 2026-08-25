package com.mahify.autopatch

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONArray
import org.json.JSONObject
import android.content.Context
import android.os.Build
import android.provider.Settings
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody

data class BackendHealth(
    val ok: Boolean,
    val postgres: Boolean,
    val redis: Boolean
)

data class GitHubRepository(
    val fullName: String,
    val defaultBranch: String,
    val private: Boolean,
    val htmlUrl: String?
)

data class SandboxRun(
    val id: Int,
    val repo: String,
    val ref: String,
    val status: String,
    val durationMs: Int?,
    val error: String?,
    val startedAt: String?,
    val finishedAt: String?,
    val symbolCount: Int
)

data class SandboxStats(
    val total: Int,
    val successful: Int,
    val running: Int,
    val failed: Int
)

data class SandboxRunsResponse(
    val stats: SandboxStats,
    val runs: List<SandboxRun>
)

object ApiClient {

suspend fun registerDevice(
    context: Context,
    fcmToken: String
) = withContext(Dispatchers.IO) {

    val deviceId =
        Settings.Secure.getString(
            context.contentResolver,
            Settings.Secure.ANDROID_ID
        ) ?: throw Exception("Unable to determine Android device ID")

    val label = Build.MODEL

    val json = JSONObject().apply {
        put("device_id", deviceId)
        put("fcm_token", fcmToken)
        put("label", label)
    }

    val body = json.toString()
        .toRequestBody("application/json".toMediaType())

    val request = Request.Builder()
        .url("$BASE_URL/v1/devices/register")
        .addHeader("X-API-Key", apiKey())
        .post(body)
        .build()

    client.newCall(request).execute().use { response ->

        if (!response.isSuccessful) {
            throw Exception(
                "Device registration failed: HTTP ${response.code}"
            )
        }
    }
}

    private val BASE_URL = BuildConfig.AUTOPATCH_BASE_URL

    private val client = OkHttpClient()

    private fun apiKey(): String {
        return BuildConfig.AUTOPATCH_API_KEY
    }

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

            val root = JSONObject(body)

            BackendHealth(
                ok = root.optBoolean("ok", false),
                postgres = root.optBoolean("postgres", false),
                redis = root.optBoolean("redis", false)
            )
        }
    }

    suspend fun getRepositories(): List<GitHubRepository> =
        withContext(Dispatchers.IO) {

            val installationId = BuildConfig.GITHUB_INSTALLATION_ID

            if (installationId.isBlank()) {
                throw Exception("GitHub installation ID is not configured")
            }

            val request = Request.Builder()
                .url(
                    "$BASE_URL/v1/github/repos" +
                            "?installation_id=$installationId"
                )
                .addHeader("X-API-Key", apiKey())
                .get()
                .build()

            client.newCall(request).execute().use { response ->

                if (!response.isSuccessful) {
                    throw Exception(
                        "Backend returned HTTP ${response.code}"
                    )
                }

                val body = response.body?.string()
                    ?: throw Exception("Empty backend response")

                val root = JSONObject(body)

                val repositories = root.optJSONArray("repositories")
                    ?: JSONArray()

                buildList {
                    for (i in 0 until repositories.length()) {
                        val repo = repositories.getJSONObject(i)

                        add(
                            GitHubRepository(
                                fullName = repo.optString("full_name"),
                                defaultBranch = repo.optString(
                                    "default_branch",
                                    "main"
                                ),
                                private = repo.optBoolean(
                                    "private",
                                    false
                                ),
                                htmlUrl = repo.optString("html_url")
                                    .takeIf { it.isNotBlank() }
                            )
                        )
                    }
                }
            }
        }

    suspend fun getSandboxRuns(
        limit: Int = 20
    ): SandboxRunsResponse = withContext(Dispatchers.IO) {

        val request = Request.Builder()
            .url("$BASE_URL/v1/sandbox/runs?limit=$limit")
            .addHeader("X-API-Key", apiKey())
            .get()
            .build()

        client.newCall(request).execute().use { response ->

            if (!response.isSuccessful) {
                throw Exception(
                    "Backend returned HTTP ${response.code}"
                )
            }

            val body = response.body?.string()
                ?: throw Exception("Empty backend response")

            val root = JSONObject(body)

            val statsJson = root.optJSONObject("stats")
                ?: JSONObject()

            val stats = SandboxStats(
                total = statsJson.optInt("total", 0),
                successful = statsJson.optInt("successful", 0),
                running = statsJson.optInt("running", 0),
                failed = statsJson.optInt("failed", 0)
            )

            val runsJson = root.optJSONArray("runs")
                ?: JSONArray()

            val runs = buildList {
                for (i in 0 until runsJson.length()) {
                    val run = runsJson.getJSONObject(i)

                    add(
                        SandboxRun(
                            id = run.optInt("id"),
                            repo = run.optString("repo"),
                            ref = run.optString("ref", "main"),
                            status = run.optString(
                                "status",
                                "unknown"
                            ),
                            durationMs = if (
                                run.has("duration_ms") &&
                                !run.isNull("duration_ms")
                            ) {
                                run.optInt("duration_ms")
                            } else {
                                null
                            },
                            error = run.optString("error")
                                .takeIf { it.isNotBlank() },
                            startedAt = run.optString("started_at")
                                .takeIf { it.isNotBlank() },
                            finishedAt = run.optString("finished_at")
                                .takeIf { it.isNotBlank() },
                            symbolCount = run.optInt(
                                "symbol_count",
                                0
                            )
                        )
                    )
                }
            }

            SandboxRunsResponse(
                stats = stats,
                runs = runs
            )
        }
    }
}