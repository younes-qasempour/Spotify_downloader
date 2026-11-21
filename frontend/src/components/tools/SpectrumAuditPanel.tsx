import { useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  ArrowUpCircle,
  CheckSquare,
  Eye,
  Loader2,
  Search,
  Sparkles,
  Square,
} from "lucide-react";
import { toast } from "sonner";
import { api } from "@/api/endpoints";
import type { SpectrumScanItem, SpectrumScanResponse } from "@/api/types";
import {
  TrackSpectrumModal,
  type SpectrumModalTarget,
} from "@/components/library/TrackSpectrumModal";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { useAppStore } from "@/stores/appStore";

type VerdictFilter = "all" | "upscaled" | "good" | "authentic";
type PreferredEngine = "auto" | "melobot" | "musilon" | "youtube";

export function SpectrumAuditPanel() {
  const queryClient = useQueryClient();
  const activeToolProgress = useAppStore((s) => s.activeToolProgress);

  const [scanning, setScanning] = useState(false);
  const [upgrading, setUpgrading] = useState(false);
  const [scanData, setScanData] = useState<SpectrumScanResponse | null>(null);
  const [verdictFilter, setVerdictFilter] = useState<VerdictFilter>("all");
  const [query, setQuery] = useState("");
  const [selectedPaths, setSelectedPaths] = useState<Set<string>>(new Set());
  const [preferredEngine, setPreferredEngine] =
    useState<PreferredEngine>("auto");
  const [inspectTarget, setInspectTarget] =
    useState<SpectrumModalTarget | null>(null);

  const handleScan = async () => {
    if (scanning) return;
    setScanning(true);
    try {
      const res = await api.tools.scanSpectrum({ max_workers: 6 });
      setScanData(res);
      setSelectedPaths(
        new Set(
          res.results
            .filter((r) => r.verdict === "upscaled")
            .map((r) => r.file_path)
        )
      );
      toast.success(`Spectrum audit complete (${res.summary.total} tracks)`, {
        description: `${res.summary.authentic} authentic · ${res.summary.good} good · ${res.summary.upscaled} upscaled`,
      });
    } catch (err) {
      toast.error("Spectrum scan failed", {
        description:
          err instanceof Error
            ? err.message
            : "Ensure FFmpeg is installed in Settings.",
      });
    } finally {
      setScanning(false);
    }
  };

  const filteredResults = useMemo(() => {
    if (!scanData) return [];
    const q = query.trim().toLowerCase();
    return scanData.results.filter((item) => {
      if (verdictFilter !== "all" && item.verdict !== verdictFilter) {
        return false;
      }
      if (q) {
        const hay = `${item.title} ${item.artist} ${item.file_path}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [query, scanData, verdictFilter]);

  const togglePath = (filePath: string) => {
    setSelectedPaths((prev) => {
      const next = new Set(prev);
      if (next.has(filePath)) next.delete(filePath);
      else next.add(filePath);
      return next;
    });
  };

  const selectAllUpscaled = () => {
    if (!scanData) return;
    setSelectedPaths(
      new Set(
        scanData.results
          .filter((r) => r.verdict === "upscaled")
          .map((r) => r.file_path)
      )
    );
  };

  const clearSelection = () => setSelectedPaths(new Set());

  const handleUpgradeSelected = async () => {
    if (!scanData || selectedPaths.size === 0 || upgrading) return;
    const picked = scanData.results.filter((r) =>
      selectedPaths.has(r.file_path)
    );
    const trackIds = Array.from(
      new Set(picked.map((p) => p.spotify_id).filter(Boolean))
    );
    const filePaths = picked
      .filter((p) => !p.spotify_id)
      .map((p) => p.file_path);

    if (trackIds.length === 0 && filePaths.length === 0) return;

    setUpgrading(true);
    try {
      const res = await api.tools.upgradeSpectrumBySelection({
        track_ids: trackIds,
        file_paths: filePaths,
        preferred_engine: preferredEngine,
      });
      void queryClient.invalidateQueries({ queryKey: ["queue"] });
      void queryClient.invalidateQueries({ queryKey: ["library"] });
      void queryClient.invalidateQueries({ queryKey: ["playlists"] });

      if (res.queued_count > 0) {
        toast.success(
          `Queued ${res.queued_count} track(s) for high-quality upgrade`,
          res.not_found.length > 0
            ? {
                description: `${res.not_found.length} file(s) had no linked Spotify archive record.`,
              }
            : undefined
        );
        const queuedSet = new Set(res.track_ids);
        setSelectedPaths((prev) => {
          const next = new Set(prev);
          for (const item of picked) {
            if (item.spotify_id && queuedSet.has(item.spotify_id)) {
              next.delete(item.file_path);
            }
          }
          return next;
        });
      } else {
        toast.warning("No matching archive tracks found to re-download", {
          description:
            "Only library tracks linked to an archive Spotify ID can be queued for upgrade.",
        });
      }
    } catch (err) {
      toast.error("Failed to queue upgrades", {
        description: err instanceof Error ? err.message : undefined,
      });
    } finally {
      setUpgrading(false);
    }
  };

  const scanProgress =
    scanning && activeToolProgress?.tool === "spectrum_scan"
      ? activeToolProgress
      : null;

  const verdictBadge = (item: SpectrumScanItem) => {
    const variant =
      item.verdict === "authentic"
        ? "emerald"
        : item.verdict === "good"
          ? "sky"
          : "danger";
    return (
      <Badge variant={variant} className="uppercase font-mono text-[10px]">
        {item.verdict}
      </Badge>
    );
  };

  return (
    <div className="space-y-5">
      <div className="glass-panel rounded-2xl p-5 flex flex-wrap items-center justify-between gap-4">
        <div className="space-y-1 max-w-2xl">
          <div className="flex items-center gap-2">
            <Activity className="h-4 w-4 text-emerald-bright" />
            <h2 className="text-base font-semibold text-white">
              Ultrasonic Spectrum Audit & Anti-Fake-Bitrate Scanner
            </h2>
          </div>
          <p className="text-xs text-zinc-400 leading-relaxed">
            Measures true high-frequency energy cutoffs across every downloaded
            track to expose YouTube/lossy upscales disguised as FLAC or 320
            kbps MP3, and queues them for genuine re-download.
          </p>
        </div>

        <Button
          type="button"
          disabled={scanning}
          onClick={() => void handleScan()}
        >
          {scanning ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Sparkles className="h-4 w-4" />
          )}
          {scanning ? "Scanning Library..." : "Scan Library Spectrum"}
        </Button>
      </div>

      {scanProgress && (
        <div className="glass-panel rounded-2xl p-4 space-y-2 border-emerald-500/30">
          <div className="flex items-center justify-between text-xs font-mono text-emerald-300 tabular-nums">
            <span className="truncate">{scanProgress.message}</span>
            <span>
              {scanProgress.current}/{scanProgress.total} (
              {Math.round(scanProgress.percent)}%)
            </span>
          </div>
          <div className="h-2 w-full rounded-full bg-black/50 overflow-hidden">
            <div
              className="h-full bg-emerald-bright transition-all"
              style={{
                width: `${Math.max(4, Math.min(100, scanProgress.percent))}%`,
              }}
            />
          </div>
        </div>
      )}

      {scanData ? (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <div className="glass-panel rounded-2xl p-4">
              <div className="text-xs text-zinc-400">Tracks Audited</div>
              <div className="mt-1 text-2xl font-bold text-white tabular-nums">
                {scanData.summary.total}
              </div>
            </div>
            <div className="glass-panel rounded-2xl p-4 border-emerald-500/20">
              <div className="text-xs text-emerald-300/90">
                Authentic Lossless / Hi-Res
              </div>
              <div className="mt-1 text-2xl font-bold text-emerald-300 tabular-nums">
                {scanData.summary.authentic}
              </div>
            </div>
            <div className="glass-panel rounded-2xl p-4 border-sky-500/20">
              <div className="text-xs text-sky-300/90">Good True 256-320k</div>
              <div className="mt-1 text-2xl font-bold text-sky-300 tabular-nums">
                {scanData.summary.good}
              </div>
            </div>
            <div className="glass-panel rounded-2xl p-4 border-red-500/25">
              <div className="text-xs text-red-300/90">
                Upscaled / Low Cutoff
              </div>
              <div className="mt-1 text-2xl font-bold text-red-300 tabular-nums">
                {scanData.summary.upscaled}
              </div>
            </div>
          </div>

          <div className="glass-panel rounded-2xl p-4 space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex flex-wrap items-center gap-1.5">
                {(
                  [
                    ["all", `All (${scanData.summary.total})`],
                    ["upscaled", `Upscaled (${scanData.summary.upscaled})`],
                    ["good", `Good (${scanData.summary.good})`],
                    ["authentic", `Authentic (${scanData.summary.authentic})`],
                  ] as const
                ).map(([id, label]) => (
                  <button
                    key={id}
                    type="button"
                    onClick={() => setVerdictFilter(id)}
                    className={cn(
                      "rounded-full px-3 py-1.5 text-xs font-medium transition-colors cursor-pointer",
                      verdictFilter === id
                        ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/40"
                        : "bg-white/[0.04] text-zinc-400 border border-white/[0.06] hover:text-zinc-200"
                    )}
                  >
                    {label}
                  </button>
                ))}
              </div>

              <div className="relative w-full sm:w-64">
                <Search className="h-3.5 w-3.5 text-zinc-500 absolute left-3 top-1/2 -translate-y-1/2" />
                <Input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Filter scanned tracks..."
                  className="pl-8 h-9 text-xs"
                />
              </div>
            </div>

            <div className="flex flex-wrap items-center justify-between gap-2 pt-2 border-t border-white/[0.06]">
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  onClick={selectAllUpscaled}
                  disabled={scanData.summary.upscaled === 0}
                >
                  Select All Upscaled ({scanData.summary.upscaled})
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  onClick={clearSelection}
                  disabled={selectedPaths.size === 0}
                >
                  Clear ({selectedPaths.size})
                </Button>
              </div>

              <div className="flex flex-wrap items-center gap-2">
                <select
                  value={preferredEngine}
                  onChange={(e) =>
                    setPreferredEngine(e.target.value as PreferredEngine)
                  }
                  className="h-9 rounded-xl border border-white/10 bg-elevated px-2.5 text-xs text-zinc-200 focus:border-emerald-500/60 focus:outline-none cursor-pointer"
                  aria-label="Upgrade engine"
                >
                  <option value="auto">Engine: Auto Priority</option>
                  <option value="musilon">Prefer Musilon VIP</option>
                  <option value="melobot">Prefer MeloBot</option>
                  <option value="youtube">Prefer YouTube Music</option>
                </select>

                <Button
                  type="button"
                  size="sm"
                  disabled={selectedPaths.size === 0 || upgrading}
                  onClick={() => void handleUpgradeSelected()}
                >
                  <ArrowUpCircle className="h-3.5 w-3.5" />
                  {upgrading
                    ? "Queuing Upgrades..."
                    : `Upgrade Selected (${selectedPaths.size})`}
                </Button>
              </div>
            </div>

            <div className="divide-y divide-white/[0.06] max-h-[520px] overflow-y-auto pr-1">
              {filteredResults.length === 0 ? (
                <div className="py-10 text-center text-xs text-zinc-500">
                  No scanned tracks match this filter.
                </div>
              ) : (
                filteredResults.map((item) => {
                  const checked = selectedPaths.has(item.file_path);
                  return (
                    <div
                      key={item.file_path}
                      className={cn(
                        "flex flex-wrap sm:flex-nowrap items-center justify-between gap-3 py-2.5 px-2 rounded-lg transition-colors",
                        checked
                          ? "bg-emerald-500/[0.06]"
                          : "hover:bg-white/[0.03]"
                      )}
                    >
                      <div className="flex items-center gap-3 min-w-0 flex-1">
                        <button
                          type="button"
                          onClick={() => togglePath(item.file_path)}
                          className="text-zinc-400 hover:text-emerald-300 shrink-0 cursor-pointer"
                          aria-label={`Select ${item.title}`}
                        >
                          {checked ? (
                            <CheckSquare className="h-4 w-4 text-emerald-bright" />
                          ) : (
                            <Square className="h-4 w-4" />
                          )}
                        </button>

                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2 min-w-0">
                            <span className="text-sm font-medium text-white truncate">
                              {item.title || "Untitled Track"}
                            </span>
                            {verdictBadge(item)}
                          </div>
                          <div className="text-[11px] text-zinc-400 truncate">
                            {item.artist ? `${item.artist} · ` : ""}
                            <span className="font-mono text-zinc-500">
                              {item.file_path}
                            </span>
                          </div>
                        </div>
                      </div>

                      <div className="flex items-center gap-3 shrink-0 ml-7 sm:ml-0">
                        <div className="text-right font-mono text-[11px] tabular-nums">
                          <div className="text-zinc-200">
                            Cutoff {item.cutoff_khz} kHz · Est{" "}
                            {item.estimated_true_kbps} kbps
                          </div>
                          <div className="text-zinc-500">
                            {item.codec} · {(item.sample_rate / 1000).toFixed(1)}kHz ·
                            Container {item.container_bitrate_kbps} kbps
                          </div>
                        </div>

                        <Button
                          type="button"
                          size="sm"
                          variant="secondary"
                          onClick={() =>
                            setInspectTarget({
                              spotify_id: item.spotify_id || undefined,
                              file_path: item.file_path,
                              title: item.title || "Spectrogram Inspection",
                              artist: item.artist || "",
                            })
                          }
                        >
                          <Eye className="h-3.5 w-3.5" />
                          Spectrogram
                        </Button>
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </div>
        </>
      ) : (
        <div className="glass-panel rounded-2xl p-10 text-center space-y-2">
          <Activity className="h-8 w-8 text-zinc-600 mx-auto" />
          <div className="text-sm font-medium text-zinc-200">
            No spectrum audit run yet
          </div>
          <p className="text-xs text-zinc-400 max-w-md mx-auto">
            Click <strong>Scan Library Spectrum</strong> to inspect every audio
            file in your downloads folder for authentic lossless cutoffs.
          </p>
        </div>
      )}

      <TrackSpectrumModal
        target={inspectTarget}
        onClose={() => setInspectTarget(null)}
      />
    </div>
  );
}
