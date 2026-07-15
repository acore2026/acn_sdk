package com.acn.sdk.identity

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import com.acn.sdk.model.StoredIdentity
import com.acn.sdk.util.AcnJson
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.JsonObject

class IdentityManager(
    context: Context,
    storageName: String = "acn_sdk_identity",
) {
    private val preferences: SharedPreferences

    init {
        val masterKey = MasterKey.Builder(context)
            .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
            .build()

        preferences = EncryptedSharedPreferences.create(
            context,
            storageName,
            masterKey,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
        )
    }

    fun getIdentity(): StoredIdentity? {
        val raw = preferences.getString(KEY_IDENTITY, null) ?: return null
        return AcnJson.decodeFromString<StoredIdentity>(raw)
    }

    fun setIdentity(
        agentId: String,
        vc0: JsonObject,
        agentName: String,
        owner: String,
        priority: Int,
        metadata: JsonObject,
    ) {
        val identity = StoredIdentity(
            agentId = agentId,
            vc0 = vc0,
            agentName = agentName,
            owner = owner,
            priority = priority,
            metadata = metadata,
        )
        preferences.edit()
            .putString(KEY_IDENTITY, AcnJson.encodeToString(identity))
            .apply()
    }

    fun setCapabilityVcs(capabilityVcs: List<JsonObject>) {
        val current = getIdentity() ?: error("Agent identity is not registered.")
        preferences.edit()
            .putString(KEY_IDENTITY, AcnJson.encodeToString(current.copy(capabilityVcs = capabilityVcs)))
            .apply()
    }

    fun clear() {
        preferences.edit().clear().apply()
    }

    fun requireAgent(agentId: String): StoredIdentity {
        val identity = getIdentity() ?: error("Agent identity is not registered.")
        require(identity.agentId == agentId) {
            "The supplied agent_id does not match this device."
        }
        return identity
    }

    companion object {
        private const val KEY_IDENTITY = "identity"
    }
}
