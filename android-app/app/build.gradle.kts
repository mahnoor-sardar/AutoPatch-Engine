import java.util.Properties

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.compose)
    id("com.google.gms.google-services")
}

val localProperties = Properties()
val localPropertiesFile = rootProject.file("local.properties")

if (localPropertiesFile.exists()) {
    localPropertiesFile.inputStream().use {
        localProperties.load(it)
    }
}

fun clientProperty(name: String): String {
    val fromFile = localProperties.getProperty(name)?.trim().orEmpty()
    if (fromFile.isNotEmpty()) {
        return fromFile
    }
    return System.getenv(name)?.trim().orEmpty()
}

fun javaStringLiteral(value: String): String {
    return "\"" +
        value.replace("\\", "\\\\").replace("\"", "\\\"") +
        "\""
}

fun isForbiddenDevSecret(value: String, vararg developmentDefaults: String): Boolean {
    val trimmed = value.trim()
    if (trimmed.isEmpty()) {
        return true
    }
    return developmentDefaults.any { it.equals(trimmed, ignoreCase = true) }
}

fun requireReleaseClientSecrets() {
    val apiKey = clientProperty("AUTOPATCH_RELEASE_API_KEY")
    val enrollment = clientProperty("AUTOPATCH_RELEASE_DEVICE_ENROLLMENT_SECRET")
    if (isForbiddenDevSecret(apiKey, "dev-local-key")) {
        throw GradleException(
            "Release builds require AUTOPATCH_RELEASE_API_KEY in local.properties " +
                "or the environment. Do not ship development keys such as " +
                "dev-local-key."
        )
    }
    if (isForbiddenDevSecret(enrollment, "dev-enrollment-secret")) {
        throw GradleException(
            "Release builds require AUTOPATCH_RELEASE_DEVICE_ENROLLMENT_SECRET " +
                "in local.properties or the environment. Do not ship development " +
                "enrollment secrets."
        )
    }
}

val githubInstallationId = clientProperty("AUTOPATCH_GITHUB_INSTALLATION_ID")
val autoPatchBaseUrl = clientProperty("AUTOPATCH_BASE_URL")
val debugApiKey = clientProperty("AUTOPATCH_API_KEY")
val debugEnrollmentSecret = clientProperty("AUTOPATCH_DEVICE_ENROLLMENT_SECRET")
val releaseApiKey = clientProperty("AUTOPATCH_RELEASE_API_KEY")
val releaseEnrollmentSecret = clientProperty("AUTOPATCH_RELEASE_DEVICE_ENROLLMENT_SECRET")

android {
    namespace = "com.mahify.autopatch"

    compileSdk {
        version = release(37)
    }

    defaultConfig {
        applicationId = "com.mahify.autopatch"
        minSdk = 24
        targetSdk = 37
        versionCode = 2
        versionName = "1.0.1"

        testInstrumentationRunner =
            "androidx.test.runner.AndroidJUnitRunner"

        buildConfigField(
            "String",
            "GITHUB_INSTALLATION_ID",
            javaStringLiteral(githubInstallationId)
        )

        buildConfigField(
            "String",
            "AUTOPATCH_BASE_URL",
            javaStringLiteral(autoPatchBaseUrl)
        )
    }

    buildTypes {
        debug {
            buildConfigField(
                "String",
                "AUTOPATCH_API_KEY",
                javaStringLiteral(debugApiKey)
            )
            buildConfigField(
                "String",
                "AUTOPATCH_DEVICE_ENROLLMENT_SECRET",
                javaStringLiteral(debugEnrollmentSecret)
            )
        }
        release {
            optimization {
                enable = false
            }
            buildConfigField(
                "String",
                "AUTOPATCH_API_KEY",
                javaStringLiteral(releaseApiKey)
            )
            buildConfigField(
                "String",
                "AUTOPATCH_DEVICE_ENROLLMENT_SECRET",
                javaStringLiteral(releaseEnrollmentSecret)
            )
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }
}

kotlin {
    compilerOptions {
        jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_11)
    }
}

dependencies {
    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.compose.material3)
    implementation("androidx.compose.material:material-icons-extended")
    implementation(libs.androidx.compose.ui)
    implementation(libs.androidx.compose.ui.graphics)
    implementation(libs.androidx.compose.ui.tooling.preview)
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.lifecycle.runtime.ktx)

    implementation(
        "androidx.lifecycle:lifecycle-viewmodel-compose:2.9.2"
    )
    implementation(
        "androidx.lifecycle:lifecycle-viewmodel-ktx:2.9.2"
    )

    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("com.google.firebase:firebase-messaging:24.1.2")
    implementation("androidx.biometric:biometric:1.1.0")
    implementation("androidx.work:work-runtime-ktx:2.9.1")
    implementation("androidx.security:security-crypto:1.1.0-alpha06")
    implementation("androidx.fragment:fragment-ktx:1.8.5")

    testImplementation(libs.junit)
    testImplementation("org.json:json:20250107")

    androidTestImplementation(
        platform(libs.androidx.compose.bom)
    )

    androidTestImplementation(
        libs.androidx.compose.ui.test.junit4
    )

    androidTestImplementation(
        libs.androidx.espresso.core
    )

    androidTestImplementation(
        libs.androidx.junit
    )

    debugImplementation(
        libs.androidx.compose.ui.test.manifest
    )

    debugImplementation(
        libs.androidx.compose.ui.tooling
    )
}

gradle.taskGraph.whenReady {
    val assemblingRelease = gradle.taskGraph.allTasks.any { task ->
        val name = task.name
        name.contains("Release") && (
            name.contains("assemble") ||
                name.contains("bundle") ||
                name.contains("generateReleaseBuildConfig") ||
                name.contains("packageRelease")
        )
    }
    if (assemblingRelease) {
        requireReleaseClientSecrets()
    }
}