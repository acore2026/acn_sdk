package com.acn.sdk.network

import com.acn.sdk.config.AcnConfig
import com.acn.sdk.model.AgentCardRequest
import com.acn.sdk.model.AgentDiscoveryRequest
import com.acn.sdk.model.AgentInfoQueryRequest
import com.acn.sdk.model.OwnerAgentsQueryRequest
import com.acn.sdk.model.TaskExecutionRequest
import com.acn.sdk.model.TaskTerminationRequest
import com.acn.sdk.util.AcnJson
import java.io.IOException
import java.util.concurrent.TimeUnit
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.JsonObject
import okhttp3.Call
import okhttp3.Callback
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response

class AcnHttpClient(
    private val config: AcnConfig,
    okHttpClient: OkHttpClient? = null,
) {
    private val client = okHttpClient ?: OkHttpClient.Builder()
        .connectTimeout(config.connectTimeoutSeconds, TimeUnit.SECONDS)
        .readTimeout(config.readTimeoutSeconds, TimeUnit.SECONDS)
        .build()

    suspend fun registerAgentInfo(payload: JsonObject): JsonObject {
        return post(config.acnAgentBaseUrl, "/idm/v1/identity-applications", payload)
    }

    suspend fun registerAgentAttribute(payload: AgentCardRequest): JsonObject {
        return post(config.acnAgentBaseUrl, "/arf/v1/agent-cards", AcnJson.encodeToString(payload))
    }

    suspend fun deregisterAgent(payload: JsonObject): JsonObject {
        return post(config.acnAgentBaseUrl, "/acn-agent/v1/agent-deletions", payload)
    }

    suspend fun requestTaskExecution(payload: TaskExecutionRequest): JsonObject {
        return post(config.acnAgentBaseUrl, "/acn-agent/v1/task-executions", AcnJson.encodeToString(payload))
    }

    suspend fun requestTerminateTask(payload: TaskTerminationRequest): JsonObject {
        return post(config.acnAgentBaseUrl, "/acn-agent/v1/task-execution-terminations", AcnJson.encodeToString(payload))
    }

    suspend fun requestTaskCollaboration(payload: AgentDiscoveryRequest): JsonObject {
        return post(config.arfBaseUrl, "/arf/v1/agent-discoveries", AcnJson.encodeToString(payload))
    }

    suspend fun queryAgentInfo(payload: AgentInfoQueryRequest): JsonObject {
        return post(config.arfBaseUrl, "/arf/v1/agent-info", AcnJson.encodeToString(payload))
    }

    suspend fun queryAgentList(payload: OwnerAgentsQueryRequest): JsonObject {
        return post(config.acnAgentBaseUrl, "/acn-agent/v1/owner-agents", AcnJson.encodeToString(payload))
    }

    private suspend fun post(baseUrl: String, path: String, body: JsonObject): JsonObject {
        return post(baseUrl, path, body.toString())
    }

    private suspend fun post(baseUrl: String, path: String, body: String): JsonObject {
        val request = Request.Builder()
            .url(baseUrl.trimEnd('/') + path)
            .post(body.toRequestBody(JSON_MEDIA_TYPE))
            .header("Content-Type", "application/json")
            .build()

        return suspendCancellableCoroutine { continuation ->
            val call = client.newCall(request)
            continuation.invokeOnCancellation {
                call.cancel()
            }
            call.enqueue(object : Callback {
                override fun onFailure(call: Call, e: IOException) {
                    if (!continuation.isCancelled) {
                        continuation.resumeWithException(e)
                    }
                }

                override fun onResponse(call: Call, response: Response) {
                    response.use {
                        val responseBody = it.body?.string().orEmpty()
                        if (!it.isSuccessful) {
                            continuation.resumeWithException(
                                IllegalStateException("HTTP request failed: ${it.code}, $responseBody"),
                            )
                            return
                        }
                        val json = if (responseBody.isBlank()) {
                            JsonObject(emptyMap())
                        } else {
                            AcnJson.decodeFromString<JsonObject>(responseBody)
                        }
                        continuation.resume(json)
                    }
                }
            })
        }
    }

    companion object {
        private val JSON_MEDIA_TYPE = "application/json; charset=utf-8".toMediaType()
    }
}
