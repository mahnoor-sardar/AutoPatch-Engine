package com.mahify.autopatch

import android.app.NotificationChannel
import android.app.NotificationManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage

class PushService : FirebaseMessagingService() {

    override fun onMessageReceived(message: RemoteMessage) {
        val title =
            message.notification?.title
                ?: message.data["title"]
                ?: "AutoPatch Engine"

        val body =
            message.notification?.body
                ?: message.data["body"]
                ?: "New AutoPatch notification"

        lastPayload = title

        createNotificationChannel()

        val notification = NotificationCompat.Builder(
            this,
            CHANNEL_ID
        )
            .setSmallIcon(com.mahify.autopatch.R.mipmap.ic_launcher)
            .setContentTitle(title)
            .setContentText(body)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setAutoCancel(true)
            .build()

        NotificationManagerCompat.from(this).notify(
            NOTIFICATION_ID,
            notification
        )
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "AutoPatch Notifications",
                NotificationManager.IMPORTANCE_HIGH
            ).apply {
                description = "AutoPatch Engine notifications"
            }

            val manager = getSystemService(
                NotificationManager::class.java
            )

            manager.createNotificationChannel(channel)
        }
    }

    companion object {
        private const val CHANNEL_ID = "autopatch_notifications"
        private const val NOTIFICATION_ID = 1001

        @Volatile
        var lastPayload: String = "(none)"
    }
}