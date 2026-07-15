package com.acn.sdk.network

class MoqNotImplementedException(
    message: String = "Android native MoQ/QUIC transport is not implemented. Attach a Rust/NDK MoQ transport before using data-plane APIs.",
) : UnsupportedOperationException(message)

interface MoqClient {
    suspend fun connect()
    suspend fun publish(namespace: String, track: String)
    suspend fun unpublish(namespace: String, track: String)
    suspend fun sendObject(namespace: String, track: String, payload: ByteArray)
    suspend fun subscribe(namespace: String, track: String, subscriberId: String)
    suspend fun unsubscribe(namespace: String, track: String, subscriberId: String? = null)
    suspend fun disconnect()
}

class NativeMoqClientPlaceholder(
    private val host: String,
    private val port: Int,
    private val role: String,
) : MoqClient {
    override suspend fun connect() {
        throw MoqNotImplementedException("MoQ connect is not implemented. host=$host port=$port role=$role")
    }

    override suspend fun publish(namespace: String, track: String) {
        throw MoqNotImplementedException()
    }

    override suspend fun unpublish(namespace: String, track: String) {
        throw MoqNotImplementedException()
    }

    override suspend fun sendObject(namespace: String, track: String, payload: ByteArray) {
        throw MoqNotImplementedException()
    }

    override suspend fun subscribe(namespace: String, track: String, subscriberId: String) {
        throw MoqNotImplementedException()
    }

    override suspend fun unsubscribe(namespace: String, track: String, subscriberId: String?) {
        throw MoqNotImplementedException()
    }

    override suspend fun disconnect() {
        // No-op until native transport is attached.
    }
}
