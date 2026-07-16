package com.acn.sdk.light.model

import org.json.JSONObject

data class GatewayState(
    val agentId: String? = null,
    val currentTaskId: String? = null,
    val identityRegistered: Boolean = false,
    val capabilitiesRegistered: Boolean = false,
    val networkStatus: String = "offline",
    val taskStatus: String = "idle",
    val lastError: String = "",
    val moqMessagesReceived: Long = 0,
)

data class GatewayResult(
    val result: Boolean,
    val message: String = "",
    val data: Map<String, String> = emptyMap(),
    val state: GatewayState = GatewayState(),
) {
    val isSuccess: Boolean get() = result

    fun requireSuccess(): GatewayResult {
        check(result) { message.ifBlank { "Gateway operation failed" } }
        return this
    }

    companion object {
        internal fun fromJson(content: String): GatewayResult {
            val root = JSONObject(content)
            val dataJson = root.optJSONObject("data") ?: JSONObject()
            val stateJson = root.optJSONObject("state") ?: JSONObject()
            val data = buildMap {
                val keys = dataJson.keys()
                while (keys.hasNext()) {
                    val key = keys.next()
                    put(key, dataJson.opt(key)?.toString().orEmpty())
                }
            }
            return GatewayResult(
                result = root.optBoolean("result", false),
                message = root.optString("message", ""),
                data = data,
                state = GatewayState(
                    agentId = stateJson.optionalString("agent_id"),
                    currentTaskId = stateJson.optionalString("current_task_id"),
                    identityRegistered = stateJson.optBoolean("identity_registered", false),
                    capabilitiesRegistered = stateJson.optBoolean("capabilities_registered", false),
                    networkStatus = stateJson.optString("network_status", "offline"),
                    taskStatus = stateJson.optString("task_status", "idle"),
                    lastError = stateJson.optString("last_error", ""),
                    moqMessagesReceived = stateJson.optLong("moq_messages_received", 0),
                ),
            )
        }

        private fun JSONObject.optionalString(key: String): String? =
            if (isNull(key) || !has(key)) null else optString(key).takeIf { it.isNotEmpty() }
    }
}
