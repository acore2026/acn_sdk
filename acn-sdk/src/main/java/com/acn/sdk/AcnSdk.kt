package com.acn.sdk

import android.content.Context
import com.acn.sdk.callback.AcnEventListener
import com.acn.sdk.config.AcnConfig
import com.acn.sdk.credential.CredentialIssuer
import com.acn.sdk.crypto.CredentialSigner
import com.acn.sdk.identity.IdentityManager
import com.acn.sdk.model.AgentCardRequest
import com.acn.sdk.model.AgentDiscoveryRequest
import com.acn.sdk.model.AgentInfo
import com.acn.sdk.model.AgentInfoQueryRequest
import com.acn.sdk.model.OwnerAgentsQueryRequest
import com.acn.sdk.model.TaskExecutionRequest
import com.acn.sdk.model.TaskTerminationRequest
import com.acn.sdk.network.AcnHttpClient
import com.acn.sdk.network.AcnWebSocketClient
import com.acn.sdk.network.MoqClient
import com.acn.sdk.network.MoqNotImplementedException
import com.acn.sdk.util.generateTaskId
import com.acn.sdk.util.utcTimestamp
import com.acn.sdk.util.wsMessage
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.add
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put

class AcnSdk(
    context: Context,
    private val agentName: String,
    private val config: AcnConfig,
    private val eventListener: AcnEventListener? = null,
    private val moqPublisher: MoqClient? = null,
    private val moqSubscriber: MoqClient? = null,
) {
    private val identityManager = IdentityManager(context.applicationContext)
    private val signer = CredentialSigner()
    private val credentialIssuer = CredentialIssuer()
    private val httpClient = AcnHttpClient(config)
    private var webSocketClient: AcnWebSocketClient? = null
    private var networkStatus: NetworkStatus = NetworkStatus.OFFLINE
    private val publishedTracks = mutableSetOf<String>()
    private val subscribedTracks = mutableSetOf<String>()

    suspend fun registerAgentInfo(agentInfo: AgentInfo): String {
        signer.ensureKeyPair()
        val timestamp = utcTimestamp()
        val payload = buildJsonObject {
            put("owner", agentInfo.owner)
            put("name", agentInfo.name)
            put("public_key", signer.publicKeyPem())
            put("description", agentInfo.description)
            put("timestamp", timestamp)
            put("signature", signer.signTimestamp(timestamp))
            put("signature_encoding", "base64")
            put("metadata", agentInfo.metadata)
        }

        val response = httpClient.registerAgentInfo(payload)
        val agentId = response["agent_id"]?.jsonPrimitive?.content
            ?: error("registerAgentInfo response missing agent_id.")
        val vc0 = response["vc0"]?.jsonObject
            ?: error("registerAgentInfo response missing vc0.")

        identityManager.setIdentity(
            agentId = agentId,
            vc0 = vc0,
            agentName = agentInfo.name,
            owner = agentInfo.owner,
            priority = agentInfo.priority,
            metadata = agentInfo.metadata,
        )
        return agentId
    }

    suspend fun registerAgentAttribute(agentId: String, capabilities: List<String>): JsonObject {
        val identity = identityManager.requireAgent(agentId)
        val capabilityVcs = credentialIssuer.fetchCapabilityVcs(
            agentId = agentId,
            capabilities = capabilities,
            agentName = identity.agentName.ifBlank { agentName },
        )
        identityManager.setCapabilityVcs(capabilityVcs)

        val timestamp = utcTimestamp()
        val request = AgentCardRequest(
            agent_id = agentId,
            priority = identity.priority,
            timestamp = timestamp,
            signature = signer.signTimestamp(timestamp),
            vc_list = listOf(identity.vc0) + capabilityVcs,
        )
        return httpClient.registerAgentAttribute(request)
    }

    fun queryAgentId(agentName: String, owner: String): String? {
        val identity = identityManager.getIdentity() ?: return null
        return if (identity.agentName == agentName && identity.owner == owner) {
            identity.agentId
        } else {
            null
        }
    }

    suspend fun queryAgentInfo(agentId: String): JsonObject {
        val identity = identityManager.getIdentity()
        if (identity?.agentId == agentId) {
            return buildJsonObject {
                put("agent_id", identity.agentId)
                put("agent_name", identity.agentName)
                put("agent_status", networkStatus.value)
                put("priority", identity.priority)
            }
        }
        return httpClient.queryAgentInfo(AgentInfoQueryRequest(agent_id = agentId))
    }

    suspend fun queryAgentList(owner: String): JsonObject {
        return httpClient.queryAgentList(OwnerAgentsQueryRequest(owner = owner))
    }

    suspend fun joinNetwork(agentId: String, connectMoq: Boolean = false) {
        identityManager.requireAgent(agentId)
        require(networkStatus == NetworkStatus.OFFLINE) { "Agent is already online." }

        val ws = AcnWebSocketClient(config, eventListener)
        ws.connect(agentId)
        webSocketClient = ws

        if (connectMoq) {
            val publisher = moqPublisher
                ?: throw MoqNotImplementedException("MoQ publisher is not attached.")
            val subscriber = moqSubscriber
                ?: throw MoqNotImplementedException("MoQ subscriber is not attached.")
            publisher.connect()
            subscriber.connect()
        }

        networkStatus = NetworkStatus.ONLINE
    }

    fun queryNetworkStatus(agentId: String): NetworkStatus {
        identityManager.requireAgent(agentId)
        return networkStatus
    }

    suspend fun logoutNetwork(agentId: String) {
        identityManager.requireAgent(agentId)
        webSocketClient?.disconnect(agentId)
        webSocketClient = null
        runCatching { moqPublisher?.disconnect() }
        runCatching { moqSubscriber?.disconnect() }
        publishedTracks.clear()
        subscribedTracks.clear()
        networkStatus = NetworkStatus.OFFLINE
    }

    suspend fun deregisterAgent(agentId: String, reason: String): JsonObject {
        identityManager.requireAgent(agentId)
        if (networkStatus == NetworkStatus.ONLINE) {
            logoutNetwork(agentId)
        }

        val timestamp = utcTimestamp()
        val payload = buildJsonObject {
            put("agent_id", agentId)
            put("reason", reason)
            put("timestamp", timestamp)
            put("signature", signer.signTimestamp(timestamp))
            put("signature_encoding", "base64")
        }
        val response = httpClient.deregisterAgent(payload)
        identityManager.clear()
        return response
    }

    suspend fun requestTaskExecution(
        agentId: String,
        taskInfo: String,
        taskId: String = generateTaskId(),
    ): String {
        requireOnlineAgent(agentId)
        val request = TaskExecutionRequest(
            agent_id = agentId,
            task_id = taskId,
            description = taskInfo,
            timestamp = utcTimestamp(),
        )
        httpClient.requestTaskExecution(request)
        return taskId
    }

    suspend fun requestTaskCollaboration(
        agentId: String,
        taskId: String,
        requiredCapabilities: List<String>,
    ): JsonObject {
        requireOnlineAgent(agentId)
        return httpClient.requestTaskCollaboration(
            AgentDiscoveryRequest(
                task_id = taskId,
                agent_id = agentId,
                required_capabilities = requiredCapabilities,
                timestamp = utcTimestamp(),
            ),
        )
    }

    fun acceptTaskCollaboration(agentId: String, taskId: String, dstAgentId: String) {
        requireOnlineAgent(agentId)
        requireWebSocket().send(
            wsMessage(
                "TASK_ACCEPT_COLLABORATION",
                buildJsonObject {
                    put("src_agent_id", agentId)
                    put("dst_agent_id", dstAgentId)
                    put("task_id", taskId)
                    put("result", "OK")
                },
            ),
        )
    }

    fun startTaskCollaboration(
        agentId: String,
        dstAgentId: String,
        taskId: String,
        taskDescription: String,
    ) {
        requireOnlineAgent(agentId)
        requireWebSocket().send(
            wsMessage(
                "START_TASK",
                buildJsonObject {
                    put("src_agent_id", agentId)
                    put("dst_agent_id", dstAgentId)
                    put("task_id", taskId)
                    put("task_description", taskDescription)
                },
            ),
        )
    }

    suspend fun taskInfoReport(
        agentId: String,
        taskId: String,
        topic: String,
        payload: ByteArray,
    ) {
        requireOnlineAgent(agentId)
        val publisher = moqPublisher
            ?: throw MoqNotImplementedException("MoQ publisher is not attached.")
        val namespace = "/$taskId/$agentId"
        val trackKey = "$namespace::$topic"

        if (trackKey !in publishedTracks) {
            publisher.publish(namespace, topic)
            requireWebSocket().send(
                wsMessage(
                    "PUBLISH_TRACK",
                    buildJsonObject {
                        put("src_agent_id", agentId)
                        put("task_id", taskId)
                        put(
                            "track_list",
                            kotlinx.serialization.json.buildJsonArray {
                                add(
                                    buildJsonObject {
                                        put("namespace", namespace)
                                        put("track", topic)
                                    },
                                )
                            },
                        )
                    },
                ),
            )
            publishedTracks.add(trackKey)
        }
        publisher.sendObject(namespace, topic, payload)
    }

    suspend fun requestTerminateTask(
        agentId: String,
        taskId: String,
        reason: String = "",
        force: Boolean = false,
    ): JsonObject {
        requireOnlineAgent(agentId)
        return httpClient.requestTerminateTask(
            TaskTerminationRequest(
                agent_id = agentId,
                task_id = taskId,
                reason = reason,
                timestamp = utcTimestamp(),
                force = force,
            ),
        )
    }

    suspend fun disconnectAll() {
        val agentId = identityManager.getIdentity()?.agentId
        if (agentId != null && networkStatus == NetworkStatus.ONLINE) {
            logoutNetwork(agentId)
        }
        webSocketClient = null
        publishedTracks.clear()
        subscribedTracks.clear()
        networkStatus = NetworkStatus.OFFLINE
    }

    fun clearAll() {
        identityManager.clear()
        publishedTracks.clear()
        subscribedTracks.clear()
        networkStatus = NetworkStatus.OFFLINE
    }

    private fun requireOnlineAgent(agentId: String) {
        identityManager.requireAgent(agentId)
        require(networkStatus == NetworkStatus.ONLINE) { "Agent is not online." }
    }

    private fun requireWebSocket(): AcnWebSocketClient {
        return webSocketClient ?: error("WebSocket is not connected. Call joinNetwork() first.")
    }
}

enum class NetworkStatus(val value: String) {
    OFFLINE("offline"),
    ONLINE("online"),
}
