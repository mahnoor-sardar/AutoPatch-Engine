package com.mahify.autopatch

import android.content.Context
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec
import kotlin.math.pow

object Totp {
    fun currentCode(secret: String, nowMs: Long = System.currentTimeMillis()): String {
        val key = decodeBase32(secret)
        val counter = nowMs / 1000L / 30L
        val data = ByteArray(8)
        var value = counter
        for (i in 7 downTo 0) {
            data[i] = (value and 0xff).toByte()
            value = value ushr 8
        }
        val mac = Mac.getInstance("HmacSHA1")
        mac.init(SecretKeySpec(key, "HmacSHA1"))
        val hash = mac.doFinal(data)
        val offset = hash.last().toInt() and 0x0f
        val binary =
            ((hash[offset].toInt() and 0x7f) shl 24) or
                ((hash[offset + 1].toInt() and 0xff) shl 16) or
                ((hash[offset + 2].toInt() and 0xff) shl 8) or
                (hash[offset + 3].toInt() and 0xff)
        val otp = binary % 10.0.pow(6).toInt()
        return otp.toString().padStart(6, '0')
    }

    fun verify(
        secret: String,
        otpCode: String,
        nowMs: Long = System.currentTimeMillis()
    ): Boolean {
        if (secret.isBlank() || otpCode.isBlank()) {
            return false
        }
        val stepMs = 30_000L
        for (offset in -1..1) {
            if (currentCode(secret, nowMs + offset * stepMs) == otpCode) {
                return true
            }
        }
        return false
    }

    fun approvalToken(secret: String, payload: String, tokenTs: Long): String {
        val mac = Mac.getInstance("HmacSHA256")
        mac.init(SecretKeySpec(secret.toByteArray(Charsets.UTF_8), "HmacSHA256"))
        val digest = mac.doFinal("$payload|$tokenTs".toByteArray(Charsets.UTF_8))
        return digest.joinToString("") { "%02x".format(it) }
    }

    private fun decodeBase32(secret: String): ByteArray {
        val alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
        val clean = secret.trim().uppercase().replace("=", "")
        var buffer = 0
        var bits = 0
        val out = ArrayList<Byte>()
        for (ch in clean) {
            val value = alphabet.indexOf(ch)
            if (value < 0) continue
            buffer = (buffer shl 5) or value
            bits += 5
            if (bits >= 8) {
                bits -= 8
                out.add(((buffer shr bits) and 0xff).toByte())
            }
        }
        return out.toByteArray()
    }
}

object DevicePrefs {
    private const val PREFS = "autopatch"
    private const val SECURE_PREFS = "autopatch_secure"
    private const val KEY_SECRET = "totp_secret"
    private const val KEY_DEVICE = "device_id"

    private fun encrypted(context: Context) =
        androidx.security.crypto.EncryptedSharedPreferences.create(
            context,
            SECURE_PREFS,
            androidx.security.crypto.MasterKey.Builder(context)
                .setKeyScheme(androidx.security.crypto.MasterKey.KeyScheme.AES256_GCM)
                .build(),
            androidx.security.crypto.EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            androidx.security.crypto.EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
        )

    private fun plaintext(context: Context) =
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    fun save(context: Context, deviceId: String, totpSecret: String) {
        encrypted(context)
            .edit()
            .putString(KEY_DEVICE, deviceId)
            .putString(KEY_SECRET, totpSecret)
            .apply()
        plaintext(context)
            .edit()
            .remove(KEY_SECRET)
            .putString(KEY_DEVICE, deviceId)
            .apply()
    }

    fun totpSecret(context: Context): String? {
        val secure = encrypted(context).getString(KEY_SECRET, null)
        if (!secure.isNullOrBlank()) {
            return secure
        }
        val legacy = plaintext(context).getString(KEY_SECRET, null)
        if (!legacy.isNullOrBlank()) {
            val deviceId = deviceId(context) ?: return legacy
            save(context, deviceId, legacy)
            return legacy
        }
        return null
    }

    fun deviceId(context: Context): String? {
        return encrypted(context).getString(KEY_DEVICE, null)
            ?: plaintext(context).getString(KEY_DEVICE, null)
    }
}
