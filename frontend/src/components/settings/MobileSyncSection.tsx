import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Check,
  Copy,
  Download,
  Eye,
  EyeOff,
  Loader2,
  Plug,
  QrCode,
  RefreshCw,
  Save,
  ShieldCheck,
  Smartphone,
  Usb,
  Wifi,
  Zap,
} from "lucide-react";
import { toast } from "sonner";
import { apiUrl } from "@/api/client";
import { api } from "@/api/endpoints";
import type { SettingsResponse, UsbSyncStatus } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

const USB_AUTO_ENABLE_KEY = "flacify.usbAutoEnable";

function readUsbAutoEnablePref(): boolean {
  try {
    const raw = window.localStorage.getItem(USB_AUTO_ENABLE_KEY);
    return raw === null ? true : raw === "true";
  } catch {
    return true;
  }
}

interface MobileSyncSectionProps {
  settings: SettingsResponse;
  onPatch: (values: Record<string, unknown>, toastMsg?: string) => Promise<void>;
  patching: boolean;
}

export function MobileSyncSection({
  settings,
  onPatch,
  patching,
}: MobileSyncSectionProps) {
  const queryClient = useQueryClient();
  const mobile = settings.config.mobile;

  const [deviceName, setDeviceName] = useState(mobile?.device_name || "");
  const [showToken, setShowToken] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const [copiedKey, setCopiedKey] = useState<string | null>(null);
  const [qrVersion, setQrVersion] = useState<number>(() => Date.now());
  const [qrError, setQrError] = useState(false);

  const [autoEnableUsb, setAutoEnableUsb] = useState<boolean>(readUsbAutoEnablePref);
  const [usbBusySerial, setUsbBusySerial] = useState<string | null>(null);
  const [installingAdb, setInstallingAdb] = useState(false);
  const autoAttemptedSerialsRef = useRef<Set<string>>(new Set());
  const manuallyDisabledSerialsRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    setDeviceName(mobile?.device_name || "");
  }, [mobile?.device_name]);

  const { data: syncInfo, isLoading, isFetching, refetch } = useQuery({
    queryKey: ["sync-info"],
    queryFn: () => api.sync.info(),
  });

  const {
    data: usbStatus,
    isLoading: usbLoading,
    isFetching: usbFetching,
    refetch: refetchUsb,
  } = useQuery({
    queryKey: ["sync-usb-status"],
    queryFn: () => api.sync.usbStatus(),
    refetchInterval: 4000,
  });

  const handleToggleAutoEnableUsb = (checked: boolean) => {
    setAutoEnableUsb(checked);
    try {
      window.localStorage.setItem(USB_AUTO_ENABLE_KEY, String(checked));
    } catch {
      // Ignore storage failures in restricted webviews.
    }
    if (checked) {
      autoAttemptedSerialsRef.current.clear();
      manuallyDisabledSerialsRef.current.clear();
    }
  };

  const handleEnableUsb = async (
    serial?: string,
    opts?: { silent?: boolean }
  ) => {
    if (serial) {
      manuallyDisabledSerialsRef.current.delete(serial);
    } else {
      manuallyDisabledSerialsRef.current.clear();
    }
    setUsbBusySerial(serial ?? "__all__");
    try {
      const res = await api.sync.usbEnable(serial);
      queryClient.setQueryData<UsbSyncStatus>(["sync-usb-status"], res);
      if (res.success) {
        toast.success("USB Cable Sync enabled", {
          description: `Phone can reach this PC at ${res.usb_url}`,
        });
      } else if (!opts?.silent) {
        toast.error(res.errors[0] || "Could not enable USB Cable Sync");
      }
    } catch (err) {
      if (!opts?.silent) {
        toast.error("Could not enable USB Cable Sync", {
          description: err instanceof Error ? err.message : undefined,
        });
      }
    } finally {
      setUsbBusySerial(null);
    }
  };

  const handleDisableUsb = async (serial?: string) => {
    if (serial) {
      manuallyDisabledSerialsRef.current.add(serial);
    } else {
      for (const dev of usbStatus?.devices ?? []) {
        if (dev.reverse_active) {
          manuallyDisabledSerialsRef.current.add(dev.serial);
        }
      }
    }
    setUsbBusySerial(serial ?? "__all__");
    try {
      const res = await api.sync.usbDisable(serial);
      queryClient.setQueryData<UsbSyncStatus>(["sync-usb-status"], res);
      if (res.success) {
        toast.success("USB Cable Sync disabled");
      } else {
        toast.error(res.errors[0] || "Could not disable USB Cable Sync");
      }
    } catch (err) {
      toast.error("Could not disable USB Cable Sync", {
        description: err instanceof Error ? err.message : undefined,
      });
    } finally {
      setUsbBusySerial(null);
    }
  };

  const handleInstallAdb = async () => {
    if (installingAdb) return;
    setInstallingAdb(true);
    try {
      const res = await api.sync.installAdb();
      toast.success(res.message || "Android Platform-Tools installed", {
        description: res.adb_path,
      });
      autoAttemptedSerialsRef.current.clear();
      await refetchUsb();
    } catch (err) {
      toast.error("Failed to install ADB (Platform-Tools)", {
        description: err instanceof Error ? err.message : undefined,
      });
    } finally {
      setInstallingAdb(false);
    }
  };

  useEffect(() => {
    if (!usbStatus) return;

    const readySerials = new Set(
      usbStatus.devices
        .filter((d) => d.state === "device")
        .map((d) => d.serial)
    );

    for (const s of Array.from(autoAttemptedSerialsRef.current)) {
      if (!readySerials.has(s)) {
        autoAttemptedSerialsRef.current.delete(s);
      }
    }
    for (const s of Array.from(manuallyDisabledSerialsRef.current)) {
      if (!readySerials.has(s)) {
        manuallyDisabledSerialsRef.current.delete(s);
      }
    }

    if (
      !autoEnableUsb ||
      !usbStatus.adb_available ||
      usbBusySerial ||
      installingAdb
    ) {
      return;
    }

    const targets = usbStatus.devices.filter(
      (d) =>
        d.state === "device" &&
        !d.reverse_active &&
        !autoAttemptedSerialsRef.current.has(d.serial) &&
        !manuallyDisabledSerialsRef.current.has(d.serial)
    );

    if (targets.length === 0) return;

    for (const target of targets) {
      autoAttemptedSerialsRef.current.add(target.serial);
    }

    void handleEnableUsb(
      targets.length === 1 ? targets[0].serial : undefined,
      { silent: true }
    );
  }, [usbStatus, autoEnableUsb, usbBusySerial, installingAdb]);

  const handleRefreshAddresses = () => {
    setQrError(false);
    setQrVersion(Date.now());
    void refetch();
  };

  const handleCopy = async (label: string, key: string, value: string) => {
    try {
      await navigator.clipboard.writeText(value);
      setCopiedKey(key);
      toast.success(`${label} copied`);
      window.setTimeout(() => {
        setCopiedKey((cur) => (cur === key ? null : cur));
      }, 1500);
    } catch {
      toast.error("Could not copy to clipboard");
    }
  };

  const handleRegenerateToken = async () => {
    if (regenerating) return;
    setRegenerating(true);
    try {
      const updated = await api.sync.regenerateToken();
      queryClient.setQueryData(["sync-info"], updated);
      setQrError(false);
      setQrVersion(Date.now());
      toast.success("Pairing token rotated", {
        description: "Scan the updated QR code on your phone to reconnect.",
      });
    } catch (err) {
      toast.error("Failed to regenerate pairing token", {
        description: err instanceof Error ? err.message : undefined,
      });
    } finally {
      setRegenerating(false);
    }
  };

  const port = syncInfo?.port || 8765;
  const firewallCmd = `New-NetFirewallRule -DisplayName "Flacify LAN Sync" -Direction Inbound -Protocol TCP -LocalPort ${port} -Action Allow`;
  const qrSrc = syncInfo?.qr_svg_url
    ? apiUrl(`${syncInfo.qr_svg_url}?v=${qrVersion}`)
    : "";

  return (
    <div className="space-y-5">
      {/* Server Toggle & Device Identity */}
      <div className="glass-panel rounded-2xl p-6 space-y-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <Smartphone className="h-4 w-4 text-emerald-bright" />
            <div>
              <h2 className="text-base font-semibold text-white">
                Android & Mobile Wi-Fi Sync Server
              </h2>
              <p className="text-xs text-zinc-400 mt-0.5">
                Sync lossless FLAC playlists over Wi-Fi or Tailscale and send Spotify
                links from Android Share directly to your PC queue.
              </p>
            </div>
          </div>

          <Badge
            variant={
              (mobile?.lan_enabled ?? true) && syncInfo?.restart_required
                ? "gold"
                : mobile?.lan_enabled ?? true
                  ? "emerald"
                  : "default"
            }
            className="gap-1.5"
          >
            <Wifi className="h-3 w-3" />
            {(mobile?.lan_enabled ?? true) && syncInfo?.restart_required
              ? "Restart Required"
              : mobile?.lan_enabled ?? true
                ? "LAN Sync Ready"
                : "Localhost Only"}
          </Badge>
        </div>

        <label className="flex items-center justify-between gap-4 rounded-xl border border-white/[0.08] bg-white/[0.025] px-4 py-3 text-xs text-zinc-200 cursor-pointer">
          <div>
            <div className="font-medium text-white">
              Allow Connections from Phone on Wi-Fi / Tailscale (0.0.0.0:{port})
            </div>
            <div className="text-[11px] text-zinc-400 mt-0.5">
              Requires pairing token for every non-local device. Restart app if
              changing from Disabled to Enabled.
            </div>
          </div>
          <input
            type="checkbox"
            checked={mobile?.lan_enabled ?? true}
            disabled={patching}
            onChange={(e) => {
              void onPatch(
                { "mobile.lan_enabled": e.target.checked },
                e.target.checked
                  ? "Wi-Fi LAN sync enabled"
                  : "Restricted backend to localhost only"
              ).then(() => {
                void queryClient.invalidateQueries({ queryKey: ["sync-info"] });
              });
            }}
            className="h-4 w-4 shrink-0 accent-emerald-500"
          />
        </label>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            void onPatch(
              { "mobile.device_name": deviceName.trim() },
              "PC device name updated"
            ).then(() => {
              setQrError(false);
              setQrVersion(Date.now());
              void queryClient.invalidateQueries({ queryKey: ["sync-info"] });
            });
          }}
          className="flex flex-wrap items-end gap-3"
        >
          <div className="flex-1 min-w-[220px] space-y-1.5">
            <label className="text-xs font-medium text-zinc-300">
              PC Display Name (shown on phone during pairing)
            </label>
            <Input
              value={deviceName}
              onChange={(e) => setDeviceName(e.target.value)}
              placeholder={syncInfo?.device_name || "Flacify PC"}
              className="text-xs"
            />
          </div>
          <Button type="submit" size="sm" disabled={patching}>
            <Save className="h-3.5 w-3.5" />
            Save Name
          </Button>
        </form>
      </div>

      {/* USB Cable Sync (High Speed) */}
      <div className="glass-panel rounded-2xl p-6 space-y-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <Usb className="h-4 w-4 text-emerald-bright" />
            <div>
              <h3 className="text-base font-semibold text-white">
                USB Cable Sync (High Speed)
              </h3>
              <p className="text-xs text-zinc-400 mt-0.5">
                Transfer lossless FLAC libraries directly over USB via{" "}
                <code className="font-mono text-zinc-300">adb reverse</code> — bypasses
                Wi-Fi routers and automatically falls back to Wi-Fi when unplugged.
              </p>
            </div>
          </div>

          <Badge
            variant={
              usbLoading
                ? "default"
                : !usbStatus?.adb_available
                  ? "gold"
                  : usbStatus.reverse_active
                    ? "emerald"
                    : usbStatus.unauthorized_count > 0
                      ? "gold"
                      : usbStatus.ready_count > 0
                        ? "sky"
                        : "default"
            }
            className="gap-1.5"
          >
            {usbStatus?.reverse_active ? (
              <Zap className="h-3 w-3" />
            ) : (
              <Usb className="h-3 w-3" />
            )}
            {usbLoading
              ? "Checking USB..."
              : !usbStatus?.adb_available
                ? "ADB Not Installed"
                : usbStatus.reverse_active
                  ? `USB Bridge Active (${usbStatus.active_count})`
                  : usbStatus.unauthorized_count > 0
                    ? "Tap Allow on Phone"
                    : usbStatus.ready_count > 0
                      ? `${usbStatus.ready_count} Phone Ready`
                      : "No USB Phone"}
          </Badge>
        </div>

        {!usbLoading && usbStatus && !usbStatus.adb_available ? (
          <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-4 space-y-3">
            <div className="flex items-start gap-2.5 text-xs text-amber-200">
              <AlertTriangle className="h-4 w-4 shrink-0 text-amber-300 mt-0.5" />
              <div className="space-y-1">
                <div className="font-medium text-amber-100">
                  Android Platform-Tools (adb) not found on this PC
                </div>
                <p className="text-[11px] text-amber-200/80">
                  Flacify uses Google&apos;s official{" "}
                  <code className="font-mono">adb.exe</code> to open the high-speed USB
                  tunnel. Click below to download it into your local Flacify folder.
                </p>
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Button
                type="button"
                size="sm"
                disabled={installingAdb}
                onClick={() => void handleInstallAdb()}
              >
                {installingAdb ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Download className="h-3.5 w-3.5" />
                )}
                {installingAdb
                  ? "Installing Platform-Tools..."
                  : "Install ADB (Platform-Tools)"}
              </Button>
              <Button
                type="button"
                size="sm"
                variant="secondary"
                disabled={usbFetching || installingAdb}
                onClick={() => void refetchUsb()}
              >
                <RefreshCw
                  className={cn("h-3.5 w-3.5", usbFetching && "animate-spin")}
                />
                Recheck
              </Button>
            </div>
          </div>
        ) : (
          <>
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-white/[0.08] bg-white/[0.025] px-4 py-3">
              <label className="flex items-center gap-3 text-xs text-zinc-200 cursor-pointer flex-1 min-w-[220px]">
                <input
                  type="checkbox"
                  checked={autoEnableUsb}
                  onChange={(e) => handleToggleAutoEnableUsb(e.target.checked)}
                  className="h-4 w-4 shrink-0 accent-emerald-500"
                />
                <div>
                  <div className="font-medium text-white">
                    Auto-enable USB bridge when phone is plugged in
                  </div>
                  <div className="text-[11px] text-zinc-400 mt-0.5">
                    Checks every 4 seconds and opens{" "}
                    <code className="font-mono">adb reverse tcp:{usbStatus?.port || port}</code>{" "}
                    automatically.
                  </div>
                </div>
              </label>

              <div className="flex flex-wrap items-center gap-2">
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  disabled={usbFetching || Boolean(usbBusySerial)}
                  onClick={() => void refetchUsb()}
                >
                  <RefreshCw
                    className={cn("h-3.5 w-3.5", usbFetching && "animate-spin")}
                  />
                  Refresh
                </Button>
                {usbStatus &&
                  usbStatus.ready_count > 0 &&
                  usbStatus.active_count < usbStatus.ready_count && (
                    <Button
                      type="button"
                      size="sm"
                      disabled={Boolean(usbBusySerial)}
                      onClick={() => void handleEnableUsb()}
                    >
                      {usbBusySerial === "__all__" ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <Plug className="h-3.5 w-3.5" />
                      )}
                      Enable USB Sync
                    </Button>
                  )}
                {usbStatus && usbStatus.active_count > 0 && (
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    disabled={Boolean(usbBusySerial)}
                    onClick={() => void handleDisableUsb()}
                  >
                    Disable All
                  </Button>
                )}
              </div>
            </div>

            {usbStatus?.error && (
              <div className="rounded-xl border border-red-500/30 bg-red-500/10 px-3.5 py-2.5 text-xs text-red-200">
                {usbStatus.error}
              </div>
            )}

            {usbStatus && usbStatus.unauthorized_count > 0 && (
              <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 px-3.5 py-2.5 text-xs text-amber-200">
                Phone detected over USB but waiting for authorization — unlock your
                phone and tap <strong>Allow</strong> on the &ldquo;Allow USB
                debugging?&rdquo; prompt.
              </div>
            )}

            {usbStatus && usbStatus.devices.length > 0 ? (
              <div className="space-y-2">
                {usbStatus.devices.map((dev) => {
                  const isReady = dev.state === "device";
                  const isBusy =
                    usbBusySerial === dev.serial || usbBusySerial === "__all__";
                  return (
                    <div
                      key={dev.serial}
                      className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-white/[0.07] bg-black/30 px-3.5 py-2.5"
                    >
                      <div className="min-w-0 space-y-0.5">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-xs font-medium text-white truncate">
                            {dev.model || dev.device || dev.serial}
                          </span>
                          {dev.is_emulator && (
                            <Badge variant="violet" className="text-[10px]">
                              Emulator
                            </Badge>
                          )}
                          <Badge
                            variant={
                              dev.reverse_active
                                ? "emerald"
                                : isReady
                                  ? "sky"
                                  : dev.state === "unauthorized"
                                    ? "gold"
                                    : "default"
                            }
                            className="text-[10px]"
                          >
                            {dev.reverse_active
                              ? "USB Bridge Active"
                              : isReady
                                ? "Ready"
                                : dev.state === "unauthorized"
                                  ? "Unauthorized"
                                  : dev.state}
                          </Badge>
                        </div>
                        <div className="font-mono text-[11px] text-zinc-400 truncate">
                          {dev.serial}
                          {dev.product ? ` · ${dev.product}` : ""}
                        </div>
                      </div>

                      {isReady && (
                        <Button
                          type="button"
                          size="sm"
                          variant={dev.reverse_active ? "outline" : "default"}
                          disabled={isBusy}
                          onClick={() =>
                            void (dev.reverse_active
                              ? handleDisableUsb(dev.serial)
                              : handleEnableUsb(dev.serial))
                          }
                        >
                          {isBusy ? (
                            <Loader2 className="h-3.5 w-3.5 animate-spin" />
                          ) : dev.reverse_active ? null : (
                            <Plug className="h-3.5 w-3.5" />
                          )}
                          {dev.reverse_active ? "Disable" : "Enable USB Sync"}
                        </Button>
                      )}
                    </div>
                  );
                })}
              </div>
            ) : !usbLoading ? (
              <div className="rounded-xl border border-dashed border-white/[0.08] bg-black/20 px-4 py-3 text-xs text-zinc-400">
                No Android phone detected over USB. Plug in a USB data cable with USB
                Debugging enabled — Flacify checks every 4 seconds.
              </div>
            ) : null}

            <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-3 space-y-2">
              <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
                <div className="flex items-center gap-2 min-w-0">
                  <span className="text-zinc-400 shrink-0">USB Tunnel Endpoint:</span>
                  <code className="font-mono text-emerald-300 truncate">
                    {usbStatus?.usb_url || `http://127.0.0.1:${port}`}
                  </code>
                </div>
                <button
                  type="button"
                  onClick={() =>
                    void handleCopy(
                      "USB Tunnel URL",
                      "usb-url",
                      usbStatus?.usb_url || `http://127.0.0.1:${port}`
                    )
                  }
                  className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-[11px] text-zinc-300 hover:bg-white/10 cursor-pointer shrink-0"
                >
                  {copiedKey === "usb-url" ? (
                    <Check className="h-3.5 w-3.5 text-emerald-400" />
                  ) : (
                    <Copy className="h-3.5 w-3.5" />
                  )}
                  Copy
                </button>
              </div>
              {usbStatus?.adb_path && (
                <div className="font-mono text-[10px] text-zinc-500 truncate">
                  ADB: {usbStatus.adb_path}
                </div>
              )}
              <div className="text-[11px] text-zinc-400">
                Android tip: Settings → About phone → tap Build number 7× → Developer
                options → enable USB debugging → tap Allow when prompted on PC.
              </div>
            </div>
          </>
        )}
      </div>

      {/* Pairing QR Code, LAN URLs & Token */}
      <div className="glass-panel rounded-2xl p-6 space-y-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <QrCode className="h-4 w-4 text-sky-400" />
            <h3 className="text-sm font-semibold text-white">
              Pair Your Android Device
            </h3>
          </div>
          {syncInfo && (
            <div className="text-xs font-mono text-zinc-400">
              <span className="text-emerald-300 font-semibold">
                {syncInfo.library_stats.total_tracks.toLocaleString()}
              </span>{" "}
              unique lossless tracks ·{" "}
              <span className="text-zinc-200">{syncInfo.library_stats.size_str}</span>{" "}
              ·{" "}
              <span className="text-zinc-200">
                {syncInfo.saved_playlists_count}
              </span>{" "}
              playlists
            </div>
          )}
        </div>

        {(mobile?.lan_enabled === false || syncInfo?.lan_enabled === false) && (
          <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 px-3.5 py-2.5 text-xs text-amber-200">
            Wi-Fi / LAN access is currently disabled — toggle &ldquo;Allow Connections
            from Phone&rdquo; on above for wireless sync (USB Cable Sync still works
            over localhost).
          </div>
        )}

        {(mobile?.lan_enabled ?? true) && syncInfo?.restart_required && (
          <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 px-3.5 py-2.5 text-xs text-amber-200">
            Backend started in Localhost-Only mode ({syncInfo.bind_host}). Restart
            Flacify so the server binds to <code className="font-mono">0.0.0.0:{port}</code>{" "}
            and begins advertising over mDNS.
          </div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-[220px_1fr] gap-6 items-start">
          {/* QR Box */}
          <div className="flex flex-col items-center gap-2.5 rounded-2xl border border-white/10 bg-white/[0.03] p-4">
            <div className="h-44 w-44 rounded-xl bg-white p-2.5 flex flex-col items-center justify-center overflow-hidden shadow-inner">
              {qrSrc && !qrError ? (
                <img
                  src={qrSrc}
                  alt="Flacify Android Pairing QR Code"
                  onLoad={() => setQrError(false)}
                  onError={() => setQrError(true)}
                  className="h-full w-full object-contain"
                />
              ) : (
                <>
                  <QrCode className="h-12 w-12 text-zinc-400" />
                  {qrError && (
                    <span className="mt-1 text-[10px] text-zinc-500">
                      QR preview unavailable
                    </span>
                  )}
                </>
              )}
            </div>
            <span className="text-[11px] text-zinc-400 text-center">
              Scan in Flacify Android to auto-fill host IP & token
            </span>
            {syncInfo?.pair_uri && (
              <Button
                type="button"
                size="sm"
                variant="secondary"
                className="w-full text-[11px]"
                onClick={() =>
                  void handleCopy("Pairing URI", "pair-uri", syncInfo.pair_uri!)
                }
              >
                {copiedKey === "pair-uri" ? (
                  <Check className="h-3 w-3 text-emerald-400" />
                ) : (
                  <Copy className="h-3 w-3" />
                )}
                Copy Pairing URI
              </Button>
            )}
          </div>

          {/* Connection Details */}
          <div className="space-y-4 min-w-0">
            <div className="space-y-1.5">
              <div className="flex items-center justify-between gap-2">
                <div className="text-xs font-medium text-zinc-300">
                  Detected PC Addresses
                </div>
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  disabled={isFetching}
                  onClick={handleRefreshAddresses}
                  className="h-7 px-2.5 text-[11px]"
                >
                  <RefreshCw
                    className={cn("h-3 w-3", isFetching && "animate-spin")}
                  />
                  Refresh
                </Button>
              </div>
              {isLoading ? (
                <div className="text-xs text-zinc-500">Detecting network adapters...</div>
              ) : syncInfo?.urls.length ? (
                <div className="space-y-1.5">
                  {syncInfo.urls.map((u, idx) => (
                    <div
                      key={u}
                      className="flex items-center justify-between gap-2 rounded-xl border border-white/[0.07] bg-black/30 px-3 py-2"
                    >
                      <div className="flex items-center gap-2 min-w-0">
                        <span className="font-mono text-xs text-emerald-300 truncate">
                          {u}
                        </span>
                        {idx === 0 && (
                          <Badge variant="emerald" className="text-[10px]">
                            Primary
                          </Badge>
                        )}
                      </div>
                      <button
                        type="button"
                        onClick={() => void handleCopy("Server URL", `url-${u}`, u)}
                        className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-[11px] text-zinc-300 hover:bg-white/10 cursor-pointer shrink-0"
                      >
                        {copiedKey === `url-${u}` ? (
                          <Check className="h-3.5 w-3.5 text-emerald-400" />
                        ) : (
                          <Copy className="h-3.5 w-3.5" />
                        )}
                        Copy
                      </button>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-xs text-amber-300">
                  No active LAN/Wi-Fi IPv4 address detected. Connect to Wi-Fi or Tailscale.
                </div>
              )}
            </div>

            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-zinc-300 flex items-center gap-1.5">
                  <ShieldCheck className="h-3.5 w-3.5 text-emerald-400" />
                  Device Pairing Token
                </span>
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  disabled={regenerating}
                  onClick={() => void handleRegenerateToken()}
                >
                  <RefreshCw
                    className={cn("h-3 w-3", regenerating && "animate-spin")}
                  />
                  Regenerate Token
                </Button>
              </div>
              <div className="flex items-center gap-2 rounded-xl border border-white/[0.07] bg-black/30 px-3 py-2">
                <code className="flex-1 truncate font-mono text-xs text-zinc-200">
                  {syncInfo?.pair_token
                    ? showToken
                      ? syncInfo.pair_token
                      : "•".repeat(24)
                    : "Generating..."}
                </code>
                <button
                  type="button"
                  onClick={() => setShowToken((v) => !v)}
                  className="p-1 text-zinc-400 hover:text-white cursor-pointer"
                  title={showToken ? "Hide token" : "Reveal token"}
                >
                  {showToken ? (
                    <EyeOff className="h-3.5 w-3.5" />
                  ) : (
                    <Eye className="h-3.5 w-3.5" />
                  )}
                </button>
                {syncInfo?.pair_token && (
                  <button
                    type="button"
                    onClick={() =>
                      void handleCopy("Pairing token", "token", syncInfo.pair_token!)
                    }
                    className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-[11px] text-zinc-300 hover:bg-white/10 cursor-pointer shrink-0"
                  >
                    {copiedKey === "token" ? (
                      <Check className="h-3.5 w-3.5 text-emerald-400" />
                    ) : (
                      <Copy className="h-3.5 w-3.5" />
                    )}
                    Copy
                  </button>
                )}
              </div>
            </div>

            {/* Windows Firewall hint */}
            <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-3 space-y-1.5">
              <div className="flex items-center justify-between gap-2 text-[11px] text-zinc-300">
                <span className="font-medium">
                  Windows Firewall Tip (if phone cannot reach PC over Wi-Fi):
                </span>
                <button
                  type="button"
                  onClick={() =>
                    void handleCopy("Firewall command", "fw", firewallCmd)
                  }
                  className="inline-flex items-center gap-1 text-sky-300 hover:text-sky-200 cursor-pointer"
                >
                  {copiedKey === "fw" ? (
                    <Check className="h-3 w-3 text-emerald-400" />
                  ) : (
                    <Copy className="h-3 w-3" />
                  )}
                  Copy Admin PowerShell Command
                </button>
              </div>
              <div className="font-mono text-[10px] text-zinc-400 break-all">
                {firewallCmd}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
