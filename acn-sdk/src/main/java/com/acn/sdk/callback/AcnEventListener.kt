package com.acn.sdk.callback

import kotlinx.serialization.json.JsonObject

interface AcnEventListener {
    fun onTaskCollaborationRequest(payload: JsonObject) {}
    fun onDiscoverResult(payload: JsonObject) {}
    fun onTaskAssigned(payload: JsonObject) {}
    fun onStartTask(payload: JsonObject) {}
    fun onTaskTermination(payload: JsonObject) {}
    fun onSubscribeTrack(payload: JsonObject) {}
    fun onMoqMessage(namespace: String, track: String, payload: ByteArray) {}
    fun onRawEvent(type: String, payload: JsonObject) {}
    fun onError(error: Throwable) {}
}
