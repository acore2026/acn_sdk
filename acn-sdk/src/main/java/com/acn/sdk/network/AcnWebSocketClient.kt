package com.acn.sdk.network

import com.acn.sdk.callback.AcnEventListener
import com.acn.sdk.config.AcnConfig
import com.acn.sdk.util.AcnJson
import com.acn.sdk.util.wsMessage
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.withTimeout
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import kotlinx.serialization.json.buildJsonObject
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener

class AcnWebSocketClient(
    private val config: AcnConfig,
    private val listener: AcnEventListener? = null,
    okHttpClient: OkHttpClient? = null,
) {
    private val client = okHttpClient ?: OkHttpClient.Builder()
        .pingInterval(20, TimeUnit.SECONDS)
        .build()

    private var webSocket: WebSocket? = null
    private var openResult: CompletableDeferred<Unit>? = null
    private var setupResult: CompletableDeferred<Unit>? = null

    suspend fun connect(agentId: String, timeoutMs: Long = 10_000) {
        require(webSocket == null) { "WebSocket is already connected." }
        openResult = CompletableDeferred()
        setupResult = CompletableDeferred()

        val request = Request.Builder()
            .url(config.agentGwWsUrl)
            .build()
        webSocket = client.newWebSocket(request, InternalListener())

        withTimeout(timeoutMs) {
            openResult?.await()
            send(
                wsMessage(
                    "SETUP",
                    buildJsonObject {
                        put("src_agent_id", agentId)
                    },
                ),
            )
            setupResult?.await()
        }
    }

    fun send(message: JsonObject) {
        val socket = webSocket ?: error("WebSocket is not connected.")
        socket.send(message.toString())
    }

    fun disconnect(agentId: String? = null) {
        if (agentId != null) {
            runCatching {
                send(
                    wsMessage(
                        "DISCONNECTION",
                        buildJsonObject {
                            put("src_agent_id", agentId)
                        },
                    ),
                )
            }
        }
        webSocket?.close(1000, "normal")
        webSocket = null
        setupResult = null
        openResult = null
    }

    private inner class InternalListener : WebSocketListener() {
        override fun onOpen(webSocket: WebSocket, response: Response) {
            openResult?.complete(Unit)
        }

        override fun onMessage(webSocket: WebSocket, text: String) {
            runCatching {
                val message = AcnJson.decodeFromString<JsonObject>(text)
                val type = message["type"]?.jsonPrimitive?.content.orEmpty()
                val payload = message["payload"]?.jsonObject ?: JsonObject(emptyMap())
                handleMessage(type, payload)
            }.onFailure {
                listener?.onError(it)
            }
        }

        override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
            openResult?.completeExceptionally(t)
            setupResult?.completeExceptionally(t)
            listener?.onError(t)
        }
    }

    private fun handleMessage(type: String, payload: JsonObject) {
        if (type == "SETUP" && payload["status"]?.jsonPrimitive?.content == "OK") {
            setupResult?.complete(Unit)
            return
        }

        listener?.onRawEvent(type, payload)
        when (type) {
            "TASK_REQUEST_COLLABORATION" -> listener?.onTaskCollaborationRequest(payload)
            "DISCOVER_RESULT" -> listener?.onDiscoverResult(payload)
            "TASK_ASSIGNED" -> listener?.onTaskAssigned(payload)
            "START_TASK" -> listener?.onStartTask(payload)
            "TASK_TERMINATION" -> listener?.onTaskTermination(payload)
            "SUBSCRIBE_TRACK" -> listener?.onSubscribeTrack(payload)
        }
    }
}
