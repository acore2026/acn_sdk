package com.acn.sdk.light

/** Only the Gateway address belongs on Android; all ACN business parameters live in YAML on Gateway. */
data class GatewayConfig(
    val baseUrl: String,
    val apiPrefix: String = "/sdk",
    val connectTimeoutMillis: Long = 10_000,
    val readTimeoutMillis: Long = 30_000,
) {
    init {
        require(baseUrl.startsWith("http://") || baseUrl.startsWith("https://")) {
            "baseUrl must start with http:// or https://"
        }
        require(connectTimeoutMillis > 0 && readTimeoutMillis > 0) {
            "Timeouts must be positive"
        }
        require(connectTimeoutMillis <= Int.MAX_VALUE && readTimeoutMillis <= Int.MAX_VALUE) {
            "Connect and read timeouts must fit in an Android Int"
        }
    }

    internal val normalizedBaseUrl: String = baseUrl.trimEnd('/')
    internal val normalizedApiPrefix: String = apiPrefix.trim('/').let {
        if (it.isEmpty()) "" else "/$it"
    }
}
