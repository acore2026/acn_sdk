package com.acn.sdk.light.network

import com.acn.sdk.light.GatewayConfig
import com.acn.sdk.light.model.GatewayResult
import java.io.Closeable
import java.net.HttpURLConnection
import java.net.URL
import java.nio.charset.StandardCharsets
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import kotlin.coroutines.resume
import kotlin.coroutines.suspendCoroutine

internal class GatewayHttpClient(
    private val config: GatewayConfig,
) : Closeable {
    private val executor: ExecutorService = Executors.newCachedThreadPool()

    suspend fun post(path: String): GatewayResult = suspendCoroutine { continuation ->
        executor.execute {
            continuation.resume(executePost(path))
        }
    }

    private fun executePost(path: String): GatewayResult {
        var connection: HttpURLConnection? = null
        return try {
            connection = URL("${config.normalizedBaseUrl}${normalizePath(path)}")
                .openConnection() as HttpURLConnection
            connection.requestMethod = "POST"
            connection.connectTimeout = config.connectTimeoutMillis.toInt()
            connection.readTimeout = config.readTimeoutMillis.toInt()
            connection.doOutput = true
            connection.setRequestProperty("Content-Type", "application/json; charset=utf-8")
            connection.setRequestProperty("Accept", "application/json")
            connection.outputStream.use { output ->
                output.write(EMPTY_JSON.toByteArray(StandardCharsets.UTF_8))
            }
            val statusCode = connection.responseCode
            val stream = if (statusCode in 200..299) connection.inputStream else connection.errorStream
            val content = stream?.bufferedReader(StandardCharsets.UTF_8)?.use { it.readText() }.orEmpty()
            val parsed = GatewayResult.fromJson(content)
            if (statusCode in 200..299) parsed else parsed.copy(result = false)
        } catch (error: Exception) {
            GatewayResult(result = false, message = error.message ?: "Gateway request failed")
        } finally {
            connection?.disconnect()
        }
    }

    override fun close() {
        executor.shutdownNow()
    }

    private fun normalizePath(path: String): String = "/" + path.trimStart('/')

    private companion object {
        const val EMPTY_JSON = "{}"
    }
}
