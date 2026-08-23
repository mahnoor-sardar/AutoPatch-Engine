package com.mahify.autopatch

import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage

class PushService : FirebaseMessagingService() {
    override fun onMessageReceived(message: RemoteMessage) {
        lastPayload = message.notification?.title
            ?: message.data["title"]
            ?: message.data.toString()
    }

    companion object {
        @Volatile
        var lastPayload: String = "(none)"
    }
}
