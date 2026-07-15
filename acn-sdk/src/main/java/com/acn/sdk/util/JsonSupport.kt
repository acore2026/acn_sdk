package com.acn.sdk.util

import java.time.Instant
import java.util.UUID
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

internal val AcnJson = Json {
    ignoreUnknownKeys = true
    encodeDefaults = true
    explicitNulls = false
}

internal fun utcTimestamp(): String = Instant.now().toString()

internal fun generateTaskId(): String = "task-${UUID.randomUUID()}"

internal fun wsMessage(type: String, payload: JsonObject): JsonObject = buildJsonObject {
    put("type", type)
    put("timestamp", utcTimestamp())
    put("payload", payload)
}
