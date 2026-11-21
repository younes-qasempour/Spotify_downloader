package com.flacify.android.network

import android.content.Context
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import android.net.wifi.WifiManager
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import java.net.Inet4Address
import java.nio.charset.StandardCharsets
import java.util.ArrayDeque

data class DiscoveredPc(
    val serviceName: String,
    val displayName: String,
    val host: String,
    val port: Int,
    val version: String,
) {
    val baseUrl: String
        get() {
            val formattedHost = if (host.contains(':') && !host.startsWith("[")) "[$host]" else host
            return "http://$formattedHost:$port"
        }
}

class MdnsDiscoveryManager(context: Context) {
    private val appContext = context.applicationContext
    private val nsdManager: NsdManager? =
        appContext.getSystemService(Context.NSD_SERVICE) as? NsdManager
    private val wifiManager: WifiManager? =
        appContext.getSystemService(Context.WIFI_SERVICE) as? WifiManager

    private val lock = Any()
    private var multicastLock: WifiManager.MulticastLock? = null
    private var discoveryListener: NsdManager.DiscoveryListener? = null
    private val resolveQueue = ArrayDeque<NsdServiceInfo>()
    private var resolving = false

    private val _discoveredPcs = MutableStateFlow<List<DiscoveredPc>>(emptyList())
    val discoveredPcs: StateFlow<List<DiscoveredPc>> = _discoveredPcs.asStateFlow()

    private val _isScanning = MutableStateFlow(false)
    val isScanning: StateFlow<Boolean> = _isScanning.asStateFlow()

    private val _errorMessage = MutableStateFlow<String?>(null)
    val errorMessage: StateFlow<String?> = _errorMessage.asStateFlow()

    fun startDiscovery() {
        val manager = nsdManager
        if (manager == null) {
            _errorMessage.value = "Network Service Discovery is unavailable on this device."
            return
        }

        synchronized(lock) {
            if (discoveryListener != null) return
            _errorMessage.value = null
            _discoveredPcs.value = emptyList()
            resolveQueue.clear()
            resolving = false

            acquireMulticastLock()

            val listener = object : NsdManager.DiscoveryListener {
                override fun onDiscoveryStarted(regType: String) {
                    _isScanning.value = true
                }

                override fun onServiceFound(serviceInfo: NsdServiceInfo) {
                    if (!serviceInfo.serviceType.contains("_flacify._tcp")) return
                    enqueueResolve(serviceInfo)
                }

                override fun onServiceLost(serviceInfo: NsdServiceInfo) {
                    _discoveredPcs.value = _discoveredPcs.value.filterNot {
                        it.serviceName == serviceInfo.serviceName
                    }
                }

                override fun onDiscoveryStopped(serviceType: String) {
                    synchronized(lock) {
                        discoveryListener = null
                        resolveQueue.clear()
                        resolving = false
                        releaseMulticastLock()
                    }
                    _isScanning.value = false
                }

                override fun onStartDiscoveryFailed(serviceType: String, errorCode: Int) {
                    synchronized(lock) {
                        discoveryListener = null
                        releaseMulticastLock()
                    }
                    _isScanning.value = false
                    _errorMessage.value = "Could not start Wi-Fi discovery (code $errorCode)."
                }

                override fun onStopDiscoveryFailed(serviceType: String, errorCode: Int) {
                    synchronized(lock) {
                        discoveryListener = null
                        releaseMulticastLock()
                    }
                    _isScanning.value = false
                }
            }

            discoveryListener = listener
            try {
                manager.discoverServices(SERVICE_TYPE, NsdManager.PROTOCOL_DNS_SD, listener)
            } catch (ex: Exception) {
                discoveryListener = null
                releaseMulticastLock()
                _isScanning.value = false
                _errorMessage.value = ex.message ?: "Failed to start mDNS discovery."
            }
        }
    }

    fun stopDiscovery() {
        val listenerToStop: NsdManager.DiscoveryListener?
        synchronized(lock) {
            listenerToStop = discoveryListener
            discoveryListener = null
            resolveQueue.clear()
            resolving = false
            releaseMulticastLock()
        }
        _isScanning.value = false
        if (listenerToStop != null) {
            try {
                nsdManager?.stopServiceDiscovery(listenerToStop)
            } catch (_: Exception) {
            }
        }
    }

    private fun enqueueResolve(serviceInfo: NsdServiceInfo) {
        synchronized(lock) {
            if (discoveryListener == null) return
            resolveQueue.addLast(serviceInfo)
            if (!resolving) {
                resolveNextLocked()
            }
        }
    }

    @Suppress("DEPRECATION")
    private fun resolveNextLocked() {
        if (discoveryListener == null || resolveQueue.isEmpty()) {
            resolving = false
            return
        }
        val manager = nsdManager ?: run {
            resolving = false
            return
        }
        resolving = true
        val next = resolveQueue.removeFirst()

        try {
            manager.resolveService(
                next,
                object : NsdManager.ResolveListener {
                    override fun onResolveFailed(info: NsdServiceInfo, errorCode: Int) {
                        synchronized(lock) {
                            resolveNextLocked()
                        }
                    }

                    override fun onServiceResolved(resolved: NsdServiceInfo) {
                        handleResolvedService(resolved)
                        synchronized(lock) {
                            resolveNextLocked()
                        }
                    }
                },
            )
        } catch (_: Exception) {
            resolving = false
        }
    }

    @Suppress("DEPRECATION")
    private fun handleResolvedService(resolved: NsdServiceInfo) {
        val hostAddrObj = resolved.host ?: return
        val rawHost = hostAddrObj.hostAddress?.trim().orEmpty()
        if (rawHost.isEmpty()) return

        // Strip any IPv6 scope interface suffix (e.g. %wlan0) if present
        val cleanHost = if (hostAddrObj !is Inet4Address && rawHost.contains('%')) {
            rawHost.substringBefore('%')
        } else {
            rawHost
        }
        val port = resolved.port
        if (port !in 1..65535) return

        val attrs = resolved.attributes
        val nameAttr = attrs["name"]?.toString(StandardCharsets.UTF_8)?.trim().orEmpty()
        val versionAttr = attrs["version"]?.toString(StandardCharsets.UTF_8)?.trim().orEmpty()
        val fallbackName = resolved.serviceName
            .removePrefix("Flacify (")
            .removeSuffix(")")
            .ifBlank { cleanHost }

        val entry = DiscoveredPc(
            serviceName = resolved.serviceName,
            displayName = nameAttr.ifBlank { fallbackName },
            host = cleanHost,
            port = port,
            version = versionAttr,
        )

        val current = _discoveredPcs.value.toMutableList()
        val existingIdx = current.indexOfFirst { it.serviceName == entry.serviceName || it.baseUrl == entry.baseUrl }
        if (existingIdx >= 0) {
            current[existingIdx] = entry
        } else {
            current.add(entry)
        }
        _discoveredPcs.value = current
    }

    private fun acquireMulticastLock() {
        try {
            if (multicastLock == null) {
                multicastLock = wifiManager?.createMulticastLock("flacify_mdns_lock")?.apply {
                    setReferenceCounted(false)
                }
            }
            if (multicastLock?.isHeld == false) {
                multicastLock?.acquire()
            }
        } catch (_: Exception) {
        }
    }

    private fun releaseMulticastLock() {
        try {
            if (multicastLock?.isHeld == true) {
                multicastLock?.release()
            }
        } catch (_: Exception) {
        }
    }

    private companion object {
        const val SERVICE_TYPE = "_flacify._tcp."
    }
}
