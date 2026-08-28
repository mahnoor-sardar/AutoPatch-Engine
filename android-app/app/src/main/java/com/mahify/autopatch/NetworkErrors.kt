package com.mahify.autopatch

import java.io.IOException
import java.net.ConnectException
import java.net.SocketTimeoutException
import java.net.UnknownHostException

object NetworkErrors {
    fun describe(error: Throwable, url: String, operation: String): String {
        val chain = generateSequence(error) { it.cause }
            .distinct()
            .joinToString(" | ") { throwable ->
                val name = throwable.javaClass.simpleName
                val message = throwable.message?.trim().orEmpty()
                if (message.isBlank()) name else "$name: $message"
            }
        return when (error) {
            is SocketTimeoutException ->
                "$operation timed out contacting $url ($chain)"
            is UnknownHostException ->
                "$operation cannot resolve host for $url ($chain)"
            is ConnectException ->
                "$operation cannot connect to $url ($chain)"
            is IOException ->
                "$operation network error for $url ($chain)"
            else ->
                "$operation failed for $url ($chain)"
        }
    }
}
