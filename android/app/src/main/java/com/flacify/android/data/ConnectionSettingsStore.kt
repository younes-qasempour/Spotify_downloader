package com.flacify.android.data

import android.content.Context
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.emptyPreferences
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import com.flacify.android.network.PairingUriParser
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.flow.map
import java.io.IOException

private val Context.connectionDataStore by preferencesDataStore(name = "flacify_connection")

data class ConnectionConfig(
    val activeUrl: String = "",
    val candidateUrls: List<String> = emptyList(),
    val pairToken: String = "",
    val deviceName: String = "",
    val serverVersion: String = "",
    val preferUsb: Boolean = true,
) {
    val isPaired: Boolean
        get() = (activeUrl.isNotBlank() || preferUsb) && pairToken.isNotBlank() &&
            (activeUrl.isNotBlank() || candidateUrls.isNotEmpty())

    fun preferredPort(): Int =
        PairingUriParser.extractPort(activeUrl)
            ?: candidateUrls.firstNotNullOfOrNull { PairingUriParser.extractPort(it) }
            ?: PairingUriParser.DEFAULT_PORT

    val usbTunnelUrl: String
        get() = PairingUriParser.usbLoopbackUrl(preferredPort())

    fun orderedCandidateUrls(): List<String> =
        PairingUriParser.buildOrderedCandidates(
            activeUrl = activeUrl,
            candidateUrls = candidateUrls,
            preferUsb = preferUsb,
        )
}

class ConnectionSettingsStore(private val context: Context) {

    val configFlow: Flow<ConnectionConfig> = context.connectionDataStore.data
        .catch { err ->
            if (err is IOException) emit(emptyPreferences()) else throw err
        }
        .map { prefs ->
            val rawCandidates = prefs[KEY_CANDIDATE_URLS].orEmpty()
            val parsedCandidates = if (rawCandidates.isBlank()) {
                emptyList()
            } else {
                rawCandidates.split('\n').mapNotNull { PairingUriParser.normalizeBaseUrl(it) }.distinct()
            }
            val active = PairingUriParser.normalizeBaseUrl(prefs[KEY_ACTIVE_URL].orEmpty()).orEmpty()
            ConnectionConfig(
                activeUrl = active,
                candidateUrls = PairingUriParser.mergeCandidateUrls(active, parsedCandidates),
                pairToken = prefs[KEY_PAIR_TOKEN].orEmpty(),
                deviceName = prefs[KEY_DEVICE_NAME].orEmpty(),
                serverVersion = prefs[KEY_SERVER_VERSION].orEmpty(),
                preferUsb = prefs[KEY_PREFER_USB] ?: true,
            )
        }

    suspend fun saveConnection(
        activeUrl: String,
        candidateUrls: List<String>,
        pairToken: String,
        deviceName: String,
        serverVersion: String,
    ) {
        val cleanActive = PairingUriParser.normalizeBaseUrl(activeUrl).orEmpty()
        val merged = PairingUriParser.mergeCandidateUrls(cleanActive, candidateUrls)
        context.connectionDataStore.edit { prefs ->
            prefs[KEY_ACTIVE_URL] = cleanActive
            prefs[KEY_CANDIDATE_URLS] = merged.joinToString("\n")
            prefs[KEY_PAIR_TOKEN] = pairToken.trim()
            prefs[KEY_DEVICE_NAME] = deviceName.trim()
            prefs[KEY_SERVER_VERSION] = serverVersion.trim()
        }
    }

    suspend fun setPreferUsb(enabled: Boolean) {
        context.connectionDataStore.edit { prefs ->
            prefs[KEY_PREFER_USB] = enabled
        }
    }

    suspend fun updateActiveUrl(activeUrl: String, extraUrls: List<String> = emptyList()) {
        val cleanActive = PairingUriParser.normalizeBaseUrl(activeUrl) ?: return
        context.connectionDataStore.edit { prefs ->
            val existingActive = PairingUriParser.normalizeBaseUrl(prefs[KEY_ACTIVE_URL].orEmpty()).orEmpty()
            val keepExistingWifi = PairingUriParser.isUsbLoopbackUrl(cleanActive) &&
                existingActive.isNotBlank() &&
                !PairingUriParser.isUsbLoopbackUrl(existingActive)
            val resolvedActive = if (keepExistingWifi) existingActive else cleanActive
            val current = prefs[KEY_CANDIDATE_URLS].orEmpty()
                .split('\n')
                .mapNotNull { PairingUriParser.normalizeBaseUrl(it) }
            val filteredExtras = extraUrls
                .mapNotNull { PairingUriParser.normalizeBaseUrl(it) }
                .filterNot { keepExistingWifi && PairingUriParser.isUsbLoopbackUrl(it) }
            val merged = PairingUriParser.mergeCandidateUrls(resolvedActive, current + filteredExtras)
            prefs[KEY_ACTIVE_URL] = resolvedActive
            prefs[KEY_CANDIDATE_URLS] = merged.joinToString("\n")
        }
    }

    suspend fun clearConnection() {
        context.connectionDataStore.edit { prefs ->
            prefs.remove(KEY_ACTIVE_URL)
            prefs.remove(KEY_CANDIDATE_URLS)
            prefs.remove(KEY_PAIR_TOKEN)
            prefs.remove(KEY_DEVICE_NAME)
            prefs.remove(KEY_SERVER_VERSION)
        }
    }

    private companion object {
        val KEY_ACTIVE_URL = stringPreferencesKey("active_url")
        val KEY_CANDIDATE_URLS = stringPreferencesKey("candidate_urls")
        val KEY_PAIR_TOKEN = stringPreferencesKey("pair_token")
        val KEY_DEVICE_NAME = stringPreferencesKey("device_name")
        val KEY_SERVER_VERSION = stringPreferencesKey("server_version")
        val KEY_PREFER_USB = booleanPreferencesKey("prefer_usb")
    }
}
