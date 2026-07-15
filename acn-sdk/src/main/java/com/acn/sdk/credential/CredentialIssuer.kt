package com.acn.sdk.credential

import com.acn.sdk.util.utcTimestamp
import kotlinx.serialization.json.add
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

class CredentialIssuer {
    fun fetchCapabilityVcs(
        agentId: String,
        capabilities: List<String>,
        agentName: String,
    ): List<JsonObject> {
        return capabilities.mapIndexed { index, capability ->
            buildJsonObject {
                put("context", buildJsonArray { add("3gpp-ts-33.xxx-v20.0.0") })
                put("id", "android/credentials/${System.currentTimeMillis()}-$index")
                put("type", buildJsonArray {
                    add("VerifiableCredential")
                    add("BindingSIMCredential")
                })
                put("issuer", issuerFor(capability))
                put("valid_from", utcTimestamp())
                put("claims", buildJsonObject {
                    put("agent_name", agentName)
                    put("agent_id", agentId)
                    put("agent_attribute", capability)
                    put("authorization_mode", "Mode2")
                })
                put("proof", buildJsonObject {
                    put("creator", "${issuerFor(capability)}#keys-1")
                    put("signature_value", "android-native-placeholder-proof")
                })
            }
        }
    }

    private fun issuerFor(capability: String): String {
        return if (capability == "可疑人员识别" || capability == "目标跟踪") {
            "did:huaweiissuer@6gc.mnc015.mcc234.3gppnetwork"
        } else {
            "did:robotfactoryissuer@6gc.mnc015.mcc234.3gppnetwork"
        }
    }
}
