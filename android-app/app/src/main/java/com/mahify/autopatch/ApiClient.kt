package com.mahify.autopatch

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONArray

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

object ApiClient {

    private const val BASE_URL = "http://192.168.18.36:8000"

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

                val root = org.json.JSONObject(body)
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
}