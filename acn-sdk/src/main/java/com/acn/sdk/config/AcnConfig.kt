package com.acn.sdk.config

data class AcnConfig(
    val networkIp: String,
    val acnAgentPort: Int = 9010,
    val arfPort: Int = 9001,
    val agentGwWsPort: Int = 9002,
    val agentGwMoqPort: Int = 9003,
    val webUiPort: Int = 9005,
    val wsPath: String = "/ws",
    val connectTimeoutSeconds: Long = 10,
    val readTimeoutSeconds: Long = 30,
) {
    val acnAgentBaseUrl: String
        get() = "http://$networkIp:$acnAgentPort"

    val arfBaseUrl: String
        get() = "http://$networkIp:$arfPort"

    val agentGwWsUrl: String
        get() = "ws://$networkIp:$agentGwWsPort$wsPath"

    val agentGwMoqHost: String
        get() = networkIp
}
