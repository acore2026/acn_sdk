package com.acn.sdk.crypto

import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyPairGenerator
import java.security.KeyStore
import java.security.PrivateKey
import java.security.PublicKey
import java.security.Signature
import java.security.spec.ECGenParameterSpec

class CredentialSigner(
    private val alias: String = DEFAULT_ALIAS,
) {
    fun ensureKeyPair() {
        val keyStore = loadKeyStore()
        if (keyStore.containsAlias(alias)) {
            return
        }

        val generator = KeyPairGenerator.getInstance(
            KeyProperties.KEY_ALGORITHM_EC,
            "AndroidKeyStore",
        )
        val spec = KeyGenParameterSpec.Builder(
            alias,
            KeyProperties.PURPOSE_SIGN or KeyProperties.PURPOSE_VERIFY,
        )
            .setAlgorithmParameterSpec(ECGenParameterSpec("secp256r1"))
            .setDigests(KeyProperties.DIGEST_SHA256)
            .setUserAuthenticationRequired(false)
            .build()
        generator.initialize(spec)
        generator.generateKeyPair()
    }

    fun signTimestamp(timestamp: String): String {
        ensureKeyPair()
        val signature = Signature.getInstance("SHA256withECDSA")
        signature.initSign(privateKey())
        signature.update(timestamp.toByteArray(Charsets.UTF_8))
        return Base64.encodeToString(signature.sign(), Base64.NO_WRAP)
    }

    fun publicKeyPem(): String {
        ensureKeyPair()
        val publicKey = publicKey()
        val encoded = Base64.encodeToString(publicKey.encoded, Base64.NO_WRAP)
        val body = encoded.chunked(64).joinToString("\n")
        return "-----BEGIN PUBLIC KEY-----\n$body\n-----END PUBLIC KEY-----"
    }

    private fun privateKey(): PrivateKey {
        val entry = loadKeyStore().getEntry(alias, null) as KeyStore.PrivateKeyEntry
        return entry.privateKey
    }

    private fun publicKey(): PublicKey {
        val entry = loadKeyStore().getEntry(alias, null) as KeyStore.PrivateKeyEntry
        return entry.certificate.publicKey
    }

    private fun loadKeyStore(): KeyStore {
        return KeyStore.getInstance("AndroidKeyStore").apply {
            load(null)
        }
    }

    companion object {
        const val DEFAULT_ALIAS = "acn_sdk_ec_key"
    }
}
