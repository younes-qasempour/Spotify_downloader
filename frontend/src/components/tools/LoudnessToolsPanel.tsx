import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Gauge, Loader2, Square, Volume2 } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/api/endpoints";
import type {
  NormalizeLibraryResponse,
  ReplayGainLibraryResponse,
} from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useAppStore } from "@/stores/appStore";

const LUFS_PRESETS = [
  { label: "-14.0 Broadcast (Spotify Standard)", value: -14.0 },
  { label: "-11.0 Dynamic Hi-Fi", value: -11.0 },
  { label: "-9.0 Punchy Club / Car (Default)", value: -9.0 },
];

export function LoudnessToolsPanel() {
  const activeToolProgress = useAppStore((s) => s.activeToolProgress);

  const { data: settings } = useQuery({
    queryKey: ["settings"],
    queryFn: () => api.settings.get(),
    staleTime: 60000,
  });

  const [targetLufs, setTargetLufs] = useState(-9.0);
  const [normalizing, setNormalizing] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [normStats, setNormStats] = useState<NormalizeLibraryResponse | null>(
    null
  );

  const [taggingRg, setTaggingRg] = useState(false);
  const [rgStats, setRgStats] = useState<ReplayGainLibraryResponse | null>(null);

  useEffect(() => {
    const val = settings?.config.download.target_lufs;
    if (typeof val === "number" && Number.isFinite(val)) {
      setTargetLufs(val);
    }
  }, [settings?.config.download.target_lufs]);

  const handleNormalizeLibrary = async () => {
    if (normalizing) return;
    setNormalizing(true);
    setCancelling(false);
    setNormStats(null);
    try {
      const res = await api.tools.normalizeLibrary({
        target_lufs: targetLufs,
      });
      setNormStats(res);
      if (res.cancelled) {
        toast.info("Library volume normalization cancelled");
      } else {
        toast.success("Library Volume Normalization Complete", {
          description: `${res.boosted} boosted · ${res.attenuated} balanced · ${res.already_balanced} already optimal`,
        });
      }
    } catch (err) {
      toast.error("Volume normalization failed", {
        description: err instanceof Error ? err.message : undefined,
      });
    } finally {
      setNormalizing(false);
      setCancelling(false);
    }
  };

  const handleCancelNormalize = async () => {
    if (!normalizing || cancelling) return;
    setCancelling(true);
    try {
      await api.tools.cancel("normalize_library");
    } catch (err) {
      toast.error("Could not send cancel signal", {
        description: err instanceof Error ? err.message : undefined,
      });
      setCancelling(false);
    }
  };

  const handleReplayGainLibrary = async () => {
    if (taggingRg) return;
    setTaggingRg(true);
    setRgStats(null);
    try {
      const res = await api.tools.replaygainLibrary();
      setRgStats(res);
      toast.success("ReplayGain 2.0 Library Tagging Complete", {
        description: `${res.calculated} track(s) tagged across ${res.scanned} scanned`,
      });
    } catch (err) {
      toast.error("ReplayGain tagging failed", {
        description: err instanceof Error ? err.message : undefined,
      });
    } finally {
      setTaggingRg(false);
    }
  };

  const normProgress =
    normalizing && activeToolProgress?.tool === "normalize_library"
      ? activeToolProgress
      : null;
  const rgProgress =
    taggingRg && activeToolProgress?.tool === "replaygain_library"
      ? activeToolProgress
      : null;

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
      {/* Volume Boost & Balance */}
      <div className="glass-panel rounded-2xl p-6 space-y-5 flex flex-col justify-between">
        <div className="space-y-4">
          <div className="flex items-start gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-emerald-500/15 text-emerald-300 border border-emerald-500/25">
              <Volume2 className="h-5 w-5" />
            </div>
            <div>
              <h2 className="text-base font-semibold text-white">
                Volume Boost & Balance (EBU R128)
              </h2>
              <p className="text-xs text-zinc-400 mt-0.5 leading-relaxed">
                Brings quiet and loud tracks to a consistent integrated loudness
                using peak-safe lookahead limiting while keeping embedded artwork,
                lyrics, and metadata intact.
              </p>
            </div>
          </div>

          <div className="rounded-xl bg-white/[0.03] border border-white/[0.06] p-4 space-y-3">
            <div className="flex items-center justify-between text-xs">
              <span className="font-medium text-zinc-300">
                Target Integrated Loudness
              </span>
              <span className="font-mono font-bold text-emerald-300 tabular-nums">
                {targetLufs.toFixed(1)} LUFS
              </span>
            </div>
            <input
              type="range"
              min={-16}
              max={-6}
              step={0.5}
              value={targetLufs}
              onChange={(e) => setTargetLufs(Number(e.target.value))}
              className="w-full accent-emerald-500 cursor-pointer"
            />
            <div className="flex flex-wrap gap-1.5">
              {LUFS_PRESETS.map((p) => (
                <button
                  key={p.value}
                  type="button"
                  onClick={() => setTargetLufs(p.value)}
                  className={cn(
                    "rounded-full px-2.5 py-1 text-[11px] font-medium transition-colors cursor-pointer border",
                    Math.abs(targetLufs - p.value) < 0.05
                      ? "bg-emerald-500/20 text-emerald-300 border-emerald-500/40"
                      : "bg-white/[0.03] text-zinc-400 border-white/[0.06] hover:text-zinc-200"
                  )}
                >
                  {p.label}
                </button>
              ))}
            </div>
          </div>

          {normProgress && (
            <div className="rounded-xl bg-emerald-500/10 border border-emerald-500/25 p-3 space-y-1.5">
              <div className="flex items-center justify-between text-xs font-mono text-emerald-300 tabular-nums">
                <span className="truncate">{normProgress.message}</span>
                <span>
                  {normProgress.current}/{normProgress.total} (
                  {Math.round(normProgress.percent)}%)
                </span>
              </div>
              <div className="h-1.5 w-full rounded-full bg-black/40 overflow-hidden">
                <div
                  className="h-full bg-emerald-bright transition-all"
                  style={{
                    width: `${Math.max(4, Math.min(100, normProgress.percent))}%`,
                  }}
                />
              </div>
            </div>
          )}

          {normStats && (
            <div className="rounded-xl bg-white/[0.03] border border-white/[0.07] p-3.5 space-y-2.5">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold text-white">
                  Normalization Summary
                </span>
                {normStats.cancelled && (
                  <Badge variant="gold">Cancelled</Badge>
                )}
              </div>
              <div className="grid grid-cols-5 gap-2 text-center text-[11px]">
                <div className="rounded-lg bg-black/30 p-2">
                  <div className="text-zinc-500">Scanned</div>
                  <div className="font-mono font-bold text-white tabular-nums">
                    {normStats.scanned}
                  </div>
                </div>
                <div className="rounded-lg bg-black/30 p-2">
                  <div className="text-zinc-500">Boosted</div>
                  <div className="font-mono font-bold text-emerald-300 tabular-nums">
                    {normStats.boosted}
                  </div>
                </div>
                <div className="rounded-lg bg-black/30 p-2">
                  <div className="text-zinc-500">Attenuated</div>
                  <div className="font-mono font-bold text-sky-300 tabular-nums">
                    {normStats.attenuated}
                  </div>
                </div>
                <div className="rounded-lg bg-black/30 p-2">
                  <div className="text-zinc-500">Balanced</div>
                  <div className="font-mono font-bold text-zinc-200 tabular-nums">
                    {normStats.already_balanced}
                  </div>
                </div>
                <div className="rounded-lg bg-black/30 p-2">
                  <div className="text-zinc-500">Errors</div>
                  <div className="font-mono font-bold text-red-300 tabular-nums">
                    {normStats.errors}
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>

        <div className="flex items-center gap-2 pt-2 border-t border-white/[0.06]">
          <Button
            type="button"
            disabled={normalizing}
            onClick={() => void handleNormalizeLibrary()}
          >
            {normalizing ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Volume2 className="h-4 w-4" />
            )}
            {normalizing
              ? "Normalizing Library..."
              : "Boost & Balance All Songs"}
          </Button>

          {normalizing && (
            <Button
              type="button"
              variant="destructive"
              disabled={cancelling}
              onClick={() => void handleCancelNormalize()}
            >
              <Square className="h-3.5 w-3.5" />
              {cancelling ? "Stopping..." : "Cancel"}
            </Button>
          )}
        </div>
      </div>

      {/* ReplayGain 2.0 Tagging */}
      <div className="glass-panel rounded-2xl p-6 space-y-5 flex flex-col justify-between">
        <div className="space-y-4">
          <div className="flex items-start gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-sky-500/15 text-sky-300 border border-sky-500/25">
              <Gauge className="h-5 w-5" />
            </div>
            <div>
              <h2 className="text-base font-semibold text-white">
                ReplayGain 2.0 Tagging (Bit-Exact)
              </h2>
              <p className="text-xs text-zinc-400 mt-0.5 leading-relaxed">
                Calculates non-destructive EBU R128 track gain and peak tags
                without altering the audio samples. Supported natively by
                Poweramp, foobar2000, VLC, Musicolet, and Symfonium.
              </p>
            </div>
          </div>

          <div className="rounded-xl bg-white/[0.03] border border-white/[0.06] p-4 text-xs text-zinc-300 space-y-1.5">
            <div className="font-medium text-white">
              Written Metadata Frames:
            </div>
            <p className="text-zinc-400">
              • <span className="font-mono text-zinc-200">REPLAYGAIN_TRACK_GAIN</span>{" "}
              (EBU R128 loudness delta to -18 LUFS reference)
            </p>
            <p className="text-zinc-400">
              • <span className="font-mono text-zinc-200">REPLAYGAIN_TRACK_PEAK</span>{" "}
              (True sample peak prevents digital clipping)
            </p>
          </div>

          {rgProgress && (
            <div className="rounded-xl bg-sky-500/10 border border-sky-500/25 p-3 space-y-1.5">
              <div className="flex items-center justify-between text-xs font-mono text-sky-300 tabular-nums">
                <span className="truncate">{rgProgress.message}</span>
                <span>
                  {rgProgress.current}/{rgProgress.total} (
                  {Math.round(rgProgress.percent)}%)
                </span>
              </div>
              <div className="h-1.5 w-full rounded-full bg-black/40 overflow-hidden">
                <div
                  className="h-full bg-sky-400 transition-all"
                  style={{
                    width: `${Math.max(4, Math.min(100, rgProgress.percent))}%`,
                  }}
                />
              </div>
            </div>
          )}

          {rgStats && (
            <div className="rounded-xl bg-white/[0.03] border border-white/[0.07] p-3.5 space-y-2.5">
              <div className="text-xs font-semibold text-white">
                ReplayGain Results
              </div>
              <div className="grid grid-cols-3 gap-2 text-center text-[11px]">
                <div className="rounded-lg bg-black/30 p-2">
                  <div className="text-zinc-500">Scanned</div>
                  <div className="font-mono font-bold text-white tabular-nums">
                    {rgStats.scanned}
                  </div>
                </div>
                <div className="rounded-lg bg-black/30 p-2">
                  <div className="text-zinc-500">Tagged</div>
                  <div className="font-mono font-bold text-emerald-300 tabular-nums">
                    {rgStats.calculated}
                  </div>
                </div>
                <div className="rounded-lg bg-black/30 p-2">
                  <div className="text-zinc-500">Errors</div>
                  <div className="font-mono font-bold text-red-300 tabular-nums">
                    {rgStats.errors}
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>

        <div className="flex items-center gap-2 pt-2 border-t border-white/[0.06]">
          <Button
            type="button"
            disabled={taggingRg}
            onClick={() => void handleReplayGainLibrary()}
          >
            {taggingRg ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Gauge className="h-4 w-4" />
            )}
            {taggingRg
              ? "Calculating ReplayGain..."
              : "Tag Entire Library with ReplayGain 2.0"}
          </Button>
        </div>
      </div>
    </div>
  );
}
