package com.mahify.autopatch

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import com.google.firebase.messaging.FirebaseMessaging
import com.mahify.autopatch.ui.navigation.AutoPatchApp
import com.mahify.autopatch.ui.theme.AutoPatchControlTheme
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch

class MainActivity : ComponentActivity() {

    companion object {
        private const val NOTIFICATION_PERMISSION_REQUEST_CODE = 1001
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        enableEdgeToEdge()

        requestNotificationPermission()
        registerForPushNotifications()

        setContent {
            AutoPatchControlTheme {
                AutoPatchApp()
            }
        }
    }

    private fun requestNotificationPermission() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            if (
                ContextCompat.checkSelfPermission(
                    this,
                    Manifest.permission.POST_NOTIFICATIONS
                ) != PackageManager.PERMISSION_GRANTED
            ) {
                ActivityCompat.requestPermissions(
                    this,
                    arrayOf(Manifest.permission.POST_NOTIFICATIONS),
                    NOTIFICATION_PERMISSION_REQUEST_CODE
                )
            }
        }
    }

    private fun registerForPushNotifications() {
        FirebaseMessaging.getInstance().token
            .addOnCompleteListener { task ->

                if (!task.isSuccessful) {
                    Toast.makeText(
                        this,
                        "Unable to get Firebase token",
                        Toast.LENGTH_SHORT
                    ).show()
                    return@addOnCompleteListener
                }

                val token = task.result

                CoroutineScope(Dispatchers.Main).launch {
                    try {
                        ApiClient.registerDevice(
                            context = this@MainActivity,
                            fcmToken = token
                        )

                        Toast.makeText(
                            this@MainActivity,
                            "Device registered",
                            Toast.LENGTH_SHORT
                        ).show()

                    } catch (e: Exception) {
                        Toast.makeText(
                            this@MainActivity,
                            "Device registration failed",
                            Toast.LENGTH_SHORT
                        ).show()
                    }
                }
            }
    }
}