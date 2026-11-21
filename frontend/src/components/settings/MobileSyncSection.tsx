import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Check,
  Copy,
  Eye,
  EyeOff,
  QrCode,
  RefreshCw,
  Save,
  ShieldCheck,
  Smartphone,
  Wifi,
} from "lucide-react";
import { toast } from "sonner";
import { api } from "@/api/endpoints";
import type { SettingsResponse } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

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

  const { data: syncInfo, isLoading } = useQuery({
    queryKey: ["sync-info"],
    queryFn: () => api.sync.info(),
  });

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
            variant={mobile?.lan_enabled ?? true ? "emerald" : "default"}
            className="gap-1.5"
          >
            <Wifi className="h-3 w-3" />
            {mobile?.lan_enabled ?? true ? "LAN Sync Ready" : "Localhost Only"}
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

        <div className="grid grid-cols-1 lg:grid-cols-[220px_1fr] gap-6 items-start">
          {/* QR Box */}
          <div className="flex flex-col items-center gap-2.5 rounded-2xl border border-white/10 bg-white/[0.03] p-4">
            <div className="h-44 w-44 rounded-xl bg-white p-2.5 flex items-center justify-center overflow-hidden shadow-inner">
              {syncInfo?.qr_svg_url ? (
                <img
                  src={`${syncInfo.qr_svg_url}?v=${qrVersion}`}
                  alt="Flacify Android Pairing QR Code"
                  className="h-full w-full object-contain"
                />
              ) : (
                <QrCode className="h-12 w-12 text-zinc-400" />
              )}
            </div>
            <span className="text-[11px] text-zinc-400 text-center">
              Scan in Flacify Android to auto-fill host IP & token
            </span>
          </div>

          {/* Connection Details */}
          <div className="space-y-4 min-w-0">
            <div className="space-y-1.5">
              <div className="text-xs font-medium text-zinc-300">
                Detected PC Addresses
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
