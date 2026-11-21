import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  Check,
  Loader2,
  RotateCcw,
  Save,
  SlidersHorizontal,
  X,
} from "lucide-react";
import { toast } from "sonner";
import { api } from "@/api/endpoints";
import { Button } from "@/components/ui/button";
import { audioEngine } from "@/lib/audioEngine";
import { cn } from "@/lib/utils";
import { useAppStore } from "@/stores/appStore";
import { usePlayerStore } from "@/stores/playerStore";

const FREQ_LABELS = [
  "31",
  "62",
  "125",
  "250",
  "500",
  "1k",
  "2k",
  "4k",
  "8k",
  "16k",
];

export function EqualizerPopover() {
  const open = useAppStore((s) => s.eqPopoverOpen);
  const setOpen = useAppStore((s) => s.setEqPopoverOpen);

  const currentTrack = usePlayerStore((s) => s.currentTrack);
  const eq = usePlayerStore((s) => s.eq);
  const eqPresets = usePlayerStore((s) => s.eqPresets);
  const eqDirtyVersion = usePlayerStore((s) => s.eqDirtyVersion);
  const setEqEnabled = usePlayerStore((s) => s.setEqEnabled);
  const setEqPreset = usePlayerStore((s) => s.setEqPreset);
  const setEqPreamp = usePlayerStore((s) => s.setEqPreamp);
  const setEqBassBoost = usePlayerStore((s) => s.setEqBassBoost);
  const setEqBand = usePlayerStore((s) => s.setEqBand);
  const resetEqFlat = usePlayerStore((s) => s.resetEqFlat);

  const [baking, setBaking] = useState(false);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, setOpen]);

  // Persist user EQ adjustments cleanly with debounce
  useEffect(() => {
    if (eqDirtyVersion === 0) return;
    const timer = window.setTimeout(() => {
      void api.tools.updateEq(eq).catch(() => {});
    }, 250);
    return () => window.clearTimeout(timer);
  }, [eq, eqDirtyVersion]);

  const handleBakeToFile = async () => {
    if (!currentTrack || baking) return;
    const wasPlaying = usePlayerStore.getState().isPlaying;
    setBaking(true);

    try {
      audioEngine.releaseSource();
      await api.tools.updateEq(eq);
      const res = await api.tools.bakeEq(currentTrack.id, {
        bands: eq.bands,
        preamp_db: eq.preamp,
        bass_boost_db: eq.bass_boost,
      });

      if (res.success) {
        setEqEnabled(false);
        await api.tools.updateEq({ ...eq, enabled: false });
        usePlayerStore.getState().bumpReloadNonce();
        usePlayerStore.getState().seek(0);
        usePlayerStore.getState().setPlaying(wasPlaying);
        toast.success("EQ Permanently Rendered to File", {
          description: `Updated "${currentTrack.title}" with metadata & artwork preserved.`,
        });
      } else {
        usePlayerStore.getState().bumpReloadNonce();
        toast.error("Could not render EQ curve to file");
      }
    } catch (err) {
      usePlayerStore.getState().bumpReloadNonce();
      toast.error("EQ Bake Failed", {
        description: err instanceof Error ? err.message : undefined,
      });
    } finally {
      setBaking(false);
    }
  };

  const presetNames = [...Object.keys(eqPresets), "Custom"];

  // Build normalized SVG frequency curve points
  const curvePoints = eq.bands
    .map((db, idx) => {
      const x = (idx / 9) * 320;
      const y = 30 - (Math.max(-12, Math.min(12, db)) / 12) * 24;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  return (
    <AnimatePresence>
      {open && (
        <div className="fixed inset-0 z-40 flex items-end justify-center sm:justify-end p-3 sm:p-6 pb-[106px] pointer-events-none">
          <div
            onClick={() => setOpen(false)}
            className="fixed inset-0 pointer-events-auto"
          />

          <motion.div
            initial={{ opacity: 0, y: 16, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 16, scale: 0.97 }}
            transition={{ duration: 0.16, ease: "easeOut" }}
            onClick={(e) => e.stopPropagation()}
            className="pointer-events-auto relative z-10 w-full max-w-[660px] rounded-2xl glass-panel p-5 shadow-2xl space-y-4 border border-white/12"
          >
            {/* Header */}
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-2.5">
                <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-emerald-500/15 text-emerald-300 border border-emerald-500/30">
                  <SlidersHorizontal className="h-4 w-4" />
                </div>
                <div>
                  <h2 className="text-sm font-semibold text-white">
                    10-Band Equalizer & Bass Boost
                  </h2>
                  <p className="text-[11px] text-zinc-400">
                    Zero-latency Web Audio DSP with lookahead peak limiter
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-3">
                <button
                  type="button"
                  onClick={() => setEqEnabled(!eq.enabled)}
                  className={cn(
                    "inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold border transition-colors cursor-pointer",
                    eq.enabled
                      ? "bg-emerald-500/20 text-emerald-300 border-emerald-500/50"
                      : "bg-white/[0.05] text-zinc-400 border-white/10 hover:text-white"
                  )}
                >
                  <span
                    className={cn(
                      "h-2 w-2 rounded-full",
                      eq.enabled ? "bg-emerald-bright" : "bg-zinc-500"
                    )}
                  />
                  {eq.enabled ? "Live EQ On" : "Bypassed"}
                </button>

                <button
                  type="button"
                  onClick={() => setOpen(false)}
                  className="rounded-lg p-1.5 text-zinc-400 hover:bg-white/10 hover:text-white cursor-pointer"
                  aria-label="Close equalizer"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
            </div>

            {/* Preset + Preamp + Sub-Bass Row */}
            <div className="rounded-xl bg-white/[0.03] border border-white/[0.07] p-3.5 space-y-3">
              <div className="flex flex-wrap items-center gap-2.5">
                <span className="text-xs font-medium text-zinc-300">
                  Preset:
                </span>
                <select
                  value={eq.preset}
                  onChange={(e) => setEqPreset(e.target.value)}
                  aria-label="Equalizer preset"
                  className="h-8 flex-1 min-w-[180px] rounded-lg border border-white/10 bg-elevated px-2.5 text-xs text-white focus:border-emerald-500/60 focus:outline-none cursor-pointer"
                >
                  {presetNames.map((name) => (
                    <option key={name} value={name}>
                      {name}
                    </option>
                  ))}
                </select>
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  onClick={resetEqFlat}
                >
                  <RotateCcw className="h-3.5 w-3.5" />
                  Reset Flat
                </Button>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs">
                <div className="space-y-1">
                  <div className="flex justify-between text-zinc-400">
                    <span>Preamp Gain</span>
                    <span className="font-mono tabular-nums text-white">
                      {eq.preamp >= 0 ? "+" : ""}
                      {eq.preamp.toFixed(1)} dB
                    </span>
                  </div>
                  <input
                    type="range"
                    min={-12}
                    max={12}
                    step={0.5}
                    value={eq.preamp}
                    onChange={(e) => setEqPreamp(Number(e.target.value))}
                    className="w-full accent-emerald-500 cursor-pointer h-1.5"
                  />
                </div>

                <div className="space-y-1">
                  <div className="flex justify-between text-zinc-400">
                    <span>Sub-Bass Boost (85 Hz)</span>
                    <span className="font-mono tabular-nums text-emerald-300">
                      +{eq.bass_boost.toFixed(1)} dB
                    </span>
                  </div>
                  <input
                    type="range"
                    min={0}
                    max={12}
                    step={0.5}
                    value={eq.bass_boost}
                    onChange={(e) => setEqBassBoost(Number(e.target.value))}
                    className="w-full accent-emerald-500 cursor-pointer h-1.5"
                  />
                </div>
              </div>
            </div>

            {/* SVG Frequency Response Preview */}
            <div className="rounded-xl bg-black/35 border border-white/[0.06] px-4 py-2">
              <svg
                viewBox="0 0 320 60"
                className="w-full h-11 overflow-visible"
                preserveAspectRatio="none"
              >
                <line
                  x1="0"
                  y1="30"
                  x2="320"
                  y2="30"
                  stroke="rgba(255,255,255,0.12)"
                  strokeDasharray="3 3"
                />
                <polyline
                  fill="none"
                  stroke={eq.enabled ? "#1ED760" : "#64748B"}
                  strokeWidth="2.2"
                  strokeLinejoin="round"
                  strokeLinecap="round"
                  points={curvePoints}
                />
              </svg>
            </div>

            {/* 10-Band Vertical Sliders Rack */}
            <div className="grid grid-cols-10 gap-1.5 rounded-xl bg-white/[0.025] border border-white/[0.06] p-3">
              {FREQ_LABELS.map((freq, idx) => {
                const val = Number(eq.bands[idx] ?? 0);
                return (
                  <div
                    key={freq}
                    className="flex flex-col items-center gap-1.5"
                  >
                    <span
                      className={cn(
                        "text-[10px] font-mono tabular-nums",
                        val === 0
                          ? "text-zinc-500"
                          : val > 0
                            ? "text-emerald-300"
                            : "text-sky-300"
                      )}
                    >
                      {val >= 0 ? "+" : ""}
                      {val.toFixed(1)}
                    </span>

                    <div className="h-32 flex items-center justify-center">
                      <input
                        type="range"
                        min={-12}
                        max={12}
                        step={0.5}
                        value={val}
                        onChange={(e) => setEqBand(idx, Number(e.target.value))}
                        aria-label={`${freq} Hz band`}
                        style={{
                          writingMode: "vertical-lr",
                          direction: "rtl",
                        }}
                        className="h-28 w-4 accent-emerald-500 cursor-pointer"
                      />
                    </div>

                    <span className="text-[10px] font-mono text-zinc-400">
                      {freq}
                    </span>
                  </div>
                );
              })}
            </div>

            {/* Footer */}
            <div className="flex flex-wrap items-center justify-between gap-2 pt-2 border-t border-white/[0.06]">
              <div className="inline-flex items-center gap-1.5 text-[11px] text-zinc-400">
                <Check className="h-3.5 w-3.5 text-emerald-400" />
                <span>
                  {eq.enabled
                    ? `Live EQ active (${eq.preset})`
                    : "Changes save automatically"}
                </span>
              </div>

              <Button
                type="button"
                size="sm"
                variant="secondary"
                disabled={!currentTrack || baking}
                onClick={() => void handleBakeToFile()}
                title="Permanently renders this EQ curve into the audio file on disk while keeping metadata & cover art"
              >
                {baking ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Save className="h-3.5 w-3.5" />
                )}
                {baking
                  ? "Rendering to File..."
                  : "Permanently Apply EQ to File"}
              </Button>
            </div>
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  );
}
