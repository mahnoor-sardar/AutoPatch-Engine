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

val autoPatchApiKey =
    localProperties.getProperty("AUTOPATCH_API_KEY") ?: ""

val githubInstallationId =
    localProperties.getProperty("AUTOPATCH_GITHUB_INSTALLATION_ID") ?: ""

val autoPatchBaseUrl =
    localProperties.getProperty("AUTOPATCH_BASE_URL")
        ?: ""

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
            "AUTOPATCH_API_KEY",
            "\"$autoPatchApiKey\""
        )

        buildConfigField(
            "String",
            "GITHUB_INSTALLATION_ID",
            "\"$githubInstallationId\""
        )

        buildConfigField(
            "String",
            "AUTOPATCH_BASE_URL",
            "\"$autoPatchBaseUrl\""
        )
    }

    buildTypes {
        release {
            optimization {
                enable = false
            }
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