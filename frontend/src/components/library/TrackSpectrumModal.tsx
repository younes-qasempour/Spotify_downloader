import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { Activity, ArrowUpCircle, Loader2, X } from "lucide-react";
import { toast } from "sonner";
import { apiUrl } from "@/api/client";
import { api } from "@/api/endpoints";
import type { LibraryTrack, SpectrumInspectResponse } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export interface SpectrumModalTarget {
  spotify_id?: string;
  file_path?: string;
  title: string;
  artist: string;
}

interface TrackSpectrumModalProps {
  track?: LibraryTrack | null;
  target?: SpectrumModalTarget | null;
  onClose: () => void;
}

export function TrackSpectrumModal({
  track,
  target,
  onClose,
}: TrackSpectrumModalProps) {
  const activeTarget: SpectrumModalTarget | null = track
    ? {
        spotify_id: track.spotify_id,
        file_path: track.file_path,
        title: track.title,
        artist: track.artist,
      }
    : (target ?? null);

  const queryClient = useQueryClient();
  const [loading, setLoading] = useState(false);
  const [upgrading, setUpgrading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<SpectrumInspectResponse | null>(null);

  const targetKey = activeTarget
    ? `${activeTarget.spotify_id || ""}|${activeTarget.file_path || ""}`
    : "";

  useEffect(() => {
    if (!activeTarget) {
      setResult(null);
      setError(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    setResult(null);

    const req = activeTarget.spotify_id
      ? api.tools.inspectSpectrum(activeTarget.spotify_id, true)
      : api.tools.inspectSpectrumByPath({
          file_path: activeTarget.file_path,
          generate_spectrogram: true,
        });

    void req
      .then((res) => {
        if (!cancelled) setResult(res);
      })
      .catch((err) => {
        if (!cancelled) {
          setError(
            err instanceof Error
              ? err.message
              : "Could not inspect spectrum (ensure FFmpeg is installed)."
          );
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [targetKey]);

  const handleUpgrade = async () => {
    if (!activeTarget || upgrading) return;
    if (!activeTarget.spotify_id && !activeTarget.file_path) return;
    setUpgrading(true);
    try {
      const res = await api.tools.upgradeSpectrumBySelection({
        track_ids: activeTarget.spotify_id ? [activeTarget.spotify_id] : [],
        file_paths:
          !activeTarget.spotify_id && activeTarget.file_path
            ? [activeTarget.file_path]
            : [],
        preferred_engine: "auto",
      });
      void queryClient.invalidateQueries({ queryKey: ["library"] });
      void queryClient.invalidateQueries({ queryKey: ["queue"] });
      if (res.queued_count > 0) {
        toast.success(`Queued "${activeTarget.title}" for quality upgrade`);
        onClose();
      } else {
        toast.warning("Track was not linked to an archive Spotify ID for re-download.");
      }
    } catch (err) {
      toast.error("Could not queue upgrade", {
        description: err instanceof Error ? err.message : undefined,
      });
    } finally {
      setUpgrading(false);
    }
  };

  const verdictVariant =
    result?.verdict === "authentic"
      ? "emerald"
      : result?.verdict === "good"
        ? "sky"
        : "danger";

  const bandEntries = result?.band_db
    ? Object.entries(result.band_db).sort((a, b) => Number(a[0]) - Number(b[0]))
    : [];

  return (
    <AnimatePresence>
      {activeTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="fixed inset-0 bg-black/75 backdrop-blur-sm"
          />

          <motion.div
            initial={{ opacity: 0, scale: 0.96, y: 10 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.96, y: 10 }}
            className="relative z-10 w-full max-w-2xl rounded-2xl glass-panel p-6 shadow-2xl space-y-4 max-h-[88vh] overflow-y-auto"
          >
            <div className="flex items-start justify-between gap-3">
              <div className="flex items-center gap-2.5 min-w-0">
                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-emerald-500/15 text-emerald-300 border border-emerald-500/30">
                  <Activity className="h-4 w-4" />
                </div>
                <div className="min-w-0">
                  <h2 className="text-base font-semibold text-white truncate">
                    Spectrum Audit — {activeTarget.title}
                  </h2>
                  <p className="text-xs text-zinc-400 truncate">
                    {activeTarget.artist || activeTarget.file_path}
                  </p>
                </div>
              </div>
              <button
                type="button"
                onClick={onClose}
                className="rounded-lg p-1.5 text-zinc-400 hover:bg-white/10 hover:text-white cursor-pointer"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            {loading ? (
              <div className="py-12 flex flex-col items-center gap-3 text-zinc-400 text-sm">
                <Loader2 className="h-7 w-7 animate-spin text-emerald-bright" />
                <span>Analyzing ultrasonic frequency cutoff & rendering spectrogram...</span>
              </div>
            ) : error ? (
              <div className="rounded-xl border border-red-500/35 bg-red-500/10 p-4 text-xs text-red-200">
                {error}
              </div>
            ) : result ? (
              <div className="space-y-4">
                <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl bg-white/[0.03] border border-white/[0.07] p-3.5">
                  <div className="space-y-0.5">
                    <div className="text-xs text-zinc-400">Verdict</div>
                    <div className="text-sm font-semibold text-white">
                      {result.verdict_title || result.verdict}
                    </div>
                  </div>
                  <Badge variant={verdictVariant} className="uppercase font-mono">
                    Cutoff {result.cutoff_khz} kHz
                  </Badge>
                </div>

                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5 text-xs">
                  <div className="rounded-xl bg-white/[0.03] border border-white/[0.06] p-3">
                    <div className="text-zinc-500">Codec</div>
                    <div className="font-mono font-semibold text-white mt-0.5">
                      {result.codec} · {result.bits_per_sample}-bit
                    </div>
                  </div>
                  <div className="rounded-xl bg-white/[0.03] border border-white/[0.06] p-3">
                    <div className="text-zinc-500">Sample Rate</div>
                    <div className="font-mono font-semibold text-white mt-0.5 tabular-nums">
                      {(result.sample_rate / 1000).toFixed(1)} kHz
                    </div>
                  </div>
                  <div className="rounded-xl bg-white/[0.03] border border-white/[0.06] p-3">
                    <div className="text-zinc-500">Container Bitrate</div>
                    <div className="font-mono font-semibold text-white mt-0.5 tabular-nums">
                      {result.container_bitrate_kbps} kbps
                    </div>
                  </div>
                  <div className="rounded-xl bg-white/[0.03] border border-white/[0.06] p-3">
                    <div className="text-zinc-500">True Quality Est.</div>
                    <div className="font-mono font-semibold text-emerald-300 mt-0.5 tabular-nums">
                      {result.estimated_true_kbps} kbps
                    </div>
                  </div>
                </div>

                {result.spectrogram_url && (
                  <div className="overflow-hidden rounded-xl border border-white/10 bg-black">
                    <img
                      src={apiUrl(result.spectrogram_url)}
                      alt="Audio Spectrogram"
                      className="w-full h-auto object-contain"
                    />
                  </div>
                )}

                {bandEntries.length > 0 && (
                  <div className="rounded-xl bg-white/[0.03] border border-white/[0.06] p-3.5 space-y-2">
                    <div className="text-[11px] font-medium text-zinc-400">
                      Spectral Energy Profile (dBFS by Frequency Band)
                    </div>
                    <div className="grid grid-cols-6 sm:grid-cols-13 gap-1.5 items-end h-20 pt-2">
                      {bandEntries.map(([hz, db]) => {
                        const pct = Math.max(8, Math.min(100, ((Number(db) + 95) / 95) * 100));
                        const numHz = Number(hz);
                        const label =
                          numHz >= 1000 ? `${(numHz / 1000).toFixed(numHz % 1000 === 0 ? 0 : 1)}k` : hz;
                        return (
                          <div
                            key={hz}
                            className="flex flex-col items-center gap-1 h-full justify-end"
                            title={`${label} Hz: ${db} dB`}
                          >
                            <div
                              className={cn(
                                "w-full rounded-t",
                                numHz >= 18000
                                  ? "bg-emerald-bright/80"
                                  : numHz >= 14000
                                    ? "bg-sky-400/80"
                                    : "bg-zinc-400/75"
                              )}
                              style={{ height: `${pct}%` }}
                            />
                            <span className="text-[9px] font-mono text-zinc-500 tabular-nums">
                              {label}
                            </span>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}
              </div>
            ) : null}

            <div className="flex items-center justify-end gap-2 pt-2 border-t border-white/[0.06]">
              {result && result.verdict === "upscaled" && (
                <Button
                  type="button"
                  size="sm"
                  disabled={upgrading}
                  onClick={() => void handleUpgrade()}
                >
                  <ArrowUpCircle className="h-3.5 w-3.5" />
                  {upgrading ? "Queuing Upgrade..." : "Re-Download Higher Quality"}
                </Button>
              )}
              <Button type="button" size="sm" variant="secondary" onClick={onClose}>
                Close
              </Button>
            </div>
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  );
}
