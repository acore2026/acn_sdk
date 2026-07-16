package com.acn.sdk.light

import com.acn.sdk.light.model.GatewayResult
import com.acn.sdk.light.network.GatewayHttpClient
import java.io.Closeable

/**
 * Lightweight Android trigger client.
 *
 * It deliberately contains no ACN WebSocket, MoQ, identity keys, task state machine, or business
 * parameters. Those responsibilities are owned by the Python Gateway.
 */
class AcnSdk(private val config: GatewayConfig) : Closeable {
    private val gateway = GatewayHttpClient(config)
    private val prefix = config.normalizedApiPrefix

    suspend fun registerIdentity(): GatewayResult = gateway.post("$prefix/register-identity")

    suspend fun registerCapabilities(): GatewayResult = gateway.post("$prefix/register-capabilities")

    suspend fun joinNetwork(): GatewayResult = gateway.post("$prefix/join-network")

    suspend fun executeTask(): GatewayResult = gateway.post("$prefix/execute-task")

    suspend fun broadcastTerminateTask(): GatewayResult =
        gateway.post("$prefix/broadcast-terminate-task")

    suspend fun logoutNetwork(): GatewayResult = gateway.post("$prefix/logout-network")

    suspend fun deregister(): GatewayResult = gateway.post("$prefix/deregister")

    override fun close() = gateway.close()
}
