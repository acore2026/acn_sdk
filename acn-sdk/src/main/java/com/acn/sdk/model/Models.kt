package com.acn.sdk.model

import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject

@Serializable
data class AgentInfo(
    val name: String,
    val owner: String,
    val description: String,
    val priority: Int = 1,
    val metadata: JsonObject = JsonObject(emptyMap()),
)

@Serializable
data class StoredIdentity(
    val agentId: String,
    val vc0: JsonObject,
    val agentName: String,
    val owner: String,
    val priority: Int,
    val metadata: JsonObject = JsonObject(emptyMap()),
    val capabilityVcs: List<JsonObject> = emptyList(),
)

@Serializable
data class SdkResult(
    val result: Boolean,
    val message: String = "",
)

@Serializable
data class WebSocketMessage(
    val type: String,
    val timestamp: String,
    val payload: JsonObject,
)

@Serializable
data class TaskExecutionRequest(
    val agent_id: String,
    val task_id: String,
    val description: String,
    val timestamp: String,
)

@Serializable
data class TaskTerminationRequest(
    val agent_id: String,
    val task_id: String,
    val reason: String,
    val timestamp: String,
    val force: Boolean = false,
)

@Serializable
data class AgentDiscoveryRequest(
    val task_id: String,
    val agent_id: String,
    val required_capabilities: List<String>,
    val timestamp: String,
)

@Serializable
data class AgentInfoQueryRequest(
    val agent_id: String,
)

@Serializable
data class OwnerAgentsQueryRequest(
    val owner: String,
)

@Serializable
data class AgentCardRequest(
    val agent_id: String,
    val priority: Int,
    val timestamp: String,
    val signature: String,
    val signature_encoding: String = "base64",
    val vc_list: List<JsonObject>,
)

typealias JsonMap = Map<String, JsonElement>
