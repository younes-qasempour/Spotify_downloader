import { useEffect, useMemo, useRef, useState } from "react";
import {
  Disc3,
  ListMusic,
  Loader2,
  Music2,
  Play,
  RefreshCw,
  RotateCcw,
  SlidersHorizontal,
  Subtitles,
} from "lucide-react";
import { toast } from "sonner";
import { apiUrl } from "@/api/client";
import { api } from "@/api/endpoints";
import type { LyricLine } from "@/api/types";
import { QualityBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn, formatDuration } from "@/lib/utils";
import { usePlayerStore } from "@/stores/playerStore";

type StudioTab = "lyrics" | "queue" | "eq";
type TranslationLang = "none" | "en" | "fa";

export function MiniPlayerStudioTabs() {
  const [activeTab, setActiveTab] = useState<StudioTab>("lyrics");

  const currentTrack = usePlayerStore((s) => s.currentTrack);
  const isPlaying = usePlayerStore((s) => s.isPlaying);
  const currentTimeSec = usePlayerStore((s) => s.currentTimeSec);
  const queue = usePlayerStore((s) => s.queue);
  const currentIndex = usePlayerStore((s) => s.currentIndex);
  const playQueueIndex = usePlayerStore((s) => s.playQueueIndex);
  const seek = usePlayerStore((s) => s.seek);

  const eq = usePlayerStore((s) => s.eq);
  const eqPresets = usePlayerStore((s) => s.eqPresets);
  const eqFrequencies = usePlayerStore((s) => s.eqFrequencies);
  const eqDirtyVersion = usePlayerStore((s) => s.eqDirtyVersion);
  const setEqEnabled = usePlayerStore((s) => s.setEqEnabled);
  const setEqPreset = usePlayerStore((s) => s.setEqPreset);
  const setEqPreamp = usePlayerStore((s) => s.setEqPreamp);
  const setEqBassBoost = usePlayerStore((s) => s.setEqBassBoost);
  const resetEqFlat = usePlayerStore((s) => s.resetEqFlat);

  // Lyrics state
  const [lines, setLines] = useState<LyricLine[]>([]);
  const [isSynced, setIsSynced] = useState(true);
  const [transLang, setTransLang] = useState<TranslationLang>("none");
  const [loadingLyrics, setLoadingLyrics] = useState(false);
  const [fetchingLyrics, setFetchingLyrics] = useState(false);
  const [translating, setTranslating] = useState(false);

  const userScrollingRef = useRef(false);
  const resumeTimerRef = useRef<number | null>(null);
  const activeLineRef = useRef<HTMLButtonElement | null>(null);
  const lastEqSaveVersionRef = useRef(eqDirtyVersion);

  useEffect(() => {
    if (!currentTrack) {
      setLines([]);
      return;
    }
    let cancelled = false;
    setLoadingLyrics(true);
    void api.lyrics
      .get(currentTrack.id, transLang)
      .then((res) => {
        if (cancelled) return;
        setLines(res.lines || []);
        setIsSynced(Boolean(res.is_synced));
      })
      .catch(() => {
        if (!cancelled) setLines([]);
      })
      .finally(() => {
        if (!cancelled) setLoadingLyrics(false);
      });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentTrack?.id]);

  // Persist EQ edits made inside Mini Player
  useEffect(() => {
    if (eqDirtyVersion === lastEqSaveVersionRef.current) return;
    lastEqSaveVersionRef.current = eqDirtyVersion;
    const timer = window.setTimeout(() => {
      void api.tools
        .updateEq({
          enabled: eq.enabled,
          preset: eq.preset,
          preamp: eq.preamp,
          bass_boost: eq.bass_boost,
          bands: eq.bands,
        })
        .catch(() => {});
    }, 250);
    return () => window.clearTimeout(timer);
  }, [eq, eqDirtyVersion]);

  const activeLineIndex = useMemo(() => {
    if (!isSynced || lines.length === 0) return -1;
    const nowMs = currentTimeSec * 1000 + 180;
    let active = -1;
    for (let i = 0; i < lines.length; i++) {
      if (lines[i].timestamp_ms <= nowMs) active = i;
      else break;
    }
    return active;
  }, [currentTimeSec, isSynced, lines]);

  useEffect(() => {
    if (
      activeTab === "lyrics" &&
      activeLineIndex >= 0 &&
      !userScrollingRef.current &&
      activeLineRef.current
    ) {
      activeLineRef.current.scrollIntoView({
        behavior: "smooth",
        block: "center",
      });
    }
  }, [activeLineIndex, activeTab]);

  const handleLangChange = async (lang: TranslationLang) => {
    setTransLang(lang);
    if (lang === "none") {
      setLines((prev) => prev.map((l) => ({ ...l, translated: undefined })));
      void api.lyrics.translate([], "none", true).catch(() => {});
      return;
    }
    if (!lines.length || translating) return;
    setTranslating(true);
    try {
      const res = await api.lyrics.translate(
        lines.map((l) => l.text),
        lang,
        true
      );
      setLines((prev) =>
        prev.map((l, idx) => ({
          ...l,
          translated: res.translated_lines[idx] || "",
        }))
      );
    } catch {
      toast.error("Lyrics translation failed");
    } finally {
      setTranslating(false);
    }
  };

  const handleFetchLrclib = async () => {
    if (!currentTrack || fetchingLyrics) return;
    setFetchingLyrics(true);
    try {
      const res = await api.lyrics.fetch(currentTrack.id);
      if (res.found) {
        setLines(res.lines || []);
        setIsSynced(Boolean(res.is_synced));
        toast.success("Synced lyrics fetched from LRCLIB");
      } else {
        toast.info("No lyrics found on LRCLIB for this track");
      }
    } catch {
      toast.error("Could not fetch LRCLIB lyrics");
    } finally {
      setFetchingLyrics(false);
    }
  };

  const pauseAutoScroll = () => {
    userScrollingRef.current = true;
    if (resumeTimerRef.current) window.clearTimeout(resumeTimerRef.current);
    resumeTimerRef.current = window.setTimeout(() => {
      userScrollingRef.current = false;
    }, 3500);
  };

  const presetNames = Object.keys(eqPresets);

  return (
    <div className="flex flex-1 min-h-0 flex-col border-t border-white/[0.08] bg-black/25">
      {/* Studio Tabs Bar */}
      <div className="flex items-center justify-between gap-2 px-3 py-1.5 border-b border-white/[0.06]">
        <div className="flex items-center gap-1">
          {(
            [
              ["lyrics", "Lyrics", Subtitles],
              ["queue", `Up Next (${queue.length})`, ListMusic],
              ["eq", "Quick EQ", SlidersHorizontal],
            ] as const
          ).map(([id, label, Icon]) => {
            const active = activeTab === id;
            return (
              <button
                key={id}
                type="button"
                onClick={() => setActiveTab(id)}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-[11px] font-medium transition-colors cursor-pointer",
                  active
                    ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/35"
                    : "text-zinc-400 hover:text-zinc-200 hover:bg-white/[0.04] border border-transparent"
                )}
              >
                <Icon className="h-3 w-3" />
                {label}
              </button>
            );
          })}
        </div>

        {activeTab === "lyrics" && (
          <div className="flex items-center gap-1">
            {(
              [
                ["none", "ORIG"],
                ["en", "EN"],
                ["fa", "FA"],
              ] as const
            ).map(([lang, tag]) => (
              <button
                key={lang}
                type="button"
                disabled={translating}
                onClick={() => void handleLangChange(lang)}
                className={cn(
                  "rounded-md px-1.5 py-0.5 text-[10px] font-mono transition-colors cursor-pointer",
                  transLang === lang
                    ? "bg-emerald-500/25 text-emerald-200"
                    : "text-zinc-500 hover:text-zinc-200"
                )}
              >
                {tag}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Tab Body */}
      <div className="flex-1 min-h-0 overflow-y-auto px-3 py-2.5">
        {activeTab === "lyrics" &&
          (!currentTrack ? (
            <div className="h-full flex flex-col items-center justify-center text-center text-xs text-zinc-500 py-6">
              <Music2 className="h-6 w-6 mb-2 text-zinc-600" />
              Play any track to view synced karaoke lyrics
            </div>
          ) : loadingLyrics ? (
            <div className="h-full flex items-center justify-center gap-2 text-xs text-zinc-400 py-8">
              <Loader2 className="h-4 w-4 animate-spin text-emerald-bright" />
              Loading lyrics...
            </div>
          ) : lines.length === 0 ? (
            <div className="h-full flex flex-col items-center justify-center gap-2.5 text-center py-6">
              <div className="text-xs text-zinc-400">
                No embedded or cached lyrics yet.
              </div>
              <Button
                type="button"
                size="sm"
                variant="secondary"
                disabled={fetchingLyrics}
                onClick={() => void handleFetchLrclib()}
              >
                {fetchingLyrics ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <RefreshCw className="h-3.5 w-3.5" />
                )}
                Fetch LRCLIB Lyrics
              </Button>
            </div>
          ) : (
            <div
              onWheel={pauseAutoScroll}
              onTouchMove={pauseAutoScroll}
              className="space-y-1.5 pb-4"
            >
              {lines.map((line, i) => {
                const isActive = i === activeLineIndex;
                return (
                  <button
                    key={`${i}-${line.timestamp_ms}`}
                    ref={isActive ? activeLineRef : undefined}
                    type="button"
                    onClick={() => {
                      if (isSynced && line.timestamp_ms >= 0) {
                        seek(line.timestamp_ms / 1000);
                      }
                    }}
                    className={cn(
                      "block w-full rounded-xl px-2.5 py-1.5 text-left transition-all cursor-pointer",
                      isActive
                        ? "bg-emerald-500/15 border border-emerald-500/30 text-white shadow-sm"
                        : "text-zinc-400 hover:bg-white/[0.04] hover:text-zinc-200 border border-transparent"
                    )}
                  >
                    <div
                      className={cn(
                        "leading-snug transition-all",
                        isActive ? "text-sm font-semibold text-white" : "text-xs"
                      )}
                    >
                      {line.text}
                    </div>
                    {line.translated && transLang !== "none" && (
                      <div
                        dir={transLang === "fa" ? "rtl" : "ltr"}
                        className={cn(
                          "mt-0.5 text-[11px]",
                          isActive ? "text-emerald-300" : "text-zinc-500"
                        )}
                      >
                        {line.translated}
                      </div>
                    )}
                  </button>
                );
              })}
            </div>
          ))}

        {activeTab === "queue" &&
          (queue.length === 0 ? (
            <div className="h-full flex flex-col items-center justify-center text-center text-xs text-zinc-500 py-6">
              <ListMusic className="h-6 w-6 mb-2 text-zinc-600" />
              Play a playlist, album, or track list to populate Up Next
            </div>
          ) : (
            <div className="space-y-1">
              {queue.map((track, idx) => {
                const isCurrent = idx === currentIndex;
                const thumb = track.coverUrl
                  ? track.coverUrl.startsWith("http")
                    ? track.coverUrl
                    : apiUrl(track.coverUrl)
                  : "";
                return (
                  <button
                    key={`${track.id}-${idx}`}
                    type="button"
                    onClick={() => playQueueIndex(idx)}
                    className={cn(
                      "flex w-full items-center gap-2.5 rounded-xl px-2 py-1.5 text-left transition-colors cursor-pointer",
                      isCurrent
                        ? "bg-emerald-500/15 border border-emerald-500/35"
                        : "hover:bg-white/[0.05] border border-transparent"
                    )}
                  >
                    <div className="relative h-8 w-8 shrink-0 overflow-hidden rounded-lg bg-elevated border border-white/[0.08]">
                      {thumb ? (
                        <img
                          src={thumb}
                          alt={track.title}
                          className="h-full w-full object-cover"
                        />
                      ) : (
                        <div className="flex h-full w-full items-center justify-center text-zinc-500">
                          <Disc3 className="h-3.5 w-3.5" />
                        </div>
                      )}
                      {isCurrent && (
                        <div className="absolute inset-0 bg-black/55 flex items-center justify-center">
                          <Play
                            className={cn(
                              "h-3 w-3 text-emerald-bright fill-current",
                              isPlaying && "animate-pulse"
                            )}
                          />
                        </div>
                      )}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div
                        className={cn(
                          "text-xs font-medium truncate",
                          isCurrent ? "text-emerald-300" : "text-white"
                        )}
                      >
                        {track.title}
                      </div>
                      <div className="text-[10px] text-zinc-400 truncate">
                        {track.artist}
                      </div>
                    </div>
                    <div className="flex items-center gap-1.5 shrink-0">
                      {track.qualityBadge && (
                        <QualityBadge
                          badge={track.qualityBadge}
                          className="text-[9px] px-1.5 py-0"
                        />
                      )}
                      <span className="text-[10px] font-mono tabular-nums text-zinc-500">
                        {formatDuration(track.durationSec, false)}
                      </span>
                    </div>
                  </button>
                );
              })}
            </div>
          ))}

        {activeTab === "eq" && (
          <div className="space-y-3">
            <div className="flex items-center justify-between gap-2">
              <label className="flex items-center gap-2 text-xs font-medium text-zinc-200 cursor-pointer">
                <input
                  type="checkbox"
                  checked={eq.enabled}
                  onChange={(e) => setEqEnabled(e.target.checked)}
                  className="h-3.5 w-3.5 accent-emerald-500"
                />
                10-Band Equalizer Active
              </label>
              <button
                type="button"
                onClick={resetEqFlat}
                className="inline-flex items-center gap-1 text-[11px] text-zinc-400 hover:text-white cursor-pointer"
              >
                <RotateCcw className="h-3 w-3" />
                Reset
              </button>
            </div>

            {presetNames.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {presetNames.map((name) => (
                  <button
                    key={name}
                    type="button"
                    onClick={() => setEqPreset(name)}
                    className={cn(
                      "rounded-full px-2.5 py-1 text-[10px] font-medium transition-colors cursor-pointer border",
                      eq.preset === name
                        ? "bg-emerald-500/20 text-emerald-300 border-emerald-500/40"
                        : "bg-white/[0.04] text-zinc-400 border-white/[0.06] hover:text-zinc-200"
                    )}
                  >
                    {name}
                  </button>
                ))}
              </div>
            )}

            <div className="grid grid-cols-2 gap-3 rounded-xl bg-white/[0.03] border border-white/[0.06] p-2.5 text-[11px]">
              <div className="space-y-1">
                <div className="flex justify-between text-zinc-300">
                  <span>Preamp</span>
                  <span className="font-mono text-emerald-300 tabular-nums">
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
                  className="w-full accent-emerald-500 cursor-pointer"
                />
              </div>
              <div className="space-y-1">
                <div className="flex justify-between text-zinc-300">
                  <span>Sub-Bass 85Hz</span>
                  <span className="font-mono text-emerald-300 tabular-nums">
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
                  className="w-full accent-emerald-500 cursor-pointer"
                />
              </div>
            </div>

            {/* Compact 10-band visual equalizer curve */}
            <div className="grid grid-cols-10 gap-1 items-end h-14 rounded-xl bg-white/[0.02] border border-white/[0.05] px-2 pt-2 pb-1">
              {eqFrequencies.map((freq, idx) => {
                const db = eq.bands[idx] ?? 0;
                const heightPct = Math.max(10, ((db + 12) / 24) * 100);
                const label = freq >= 1000 ? `${freq / 1000}k` : String(freq);
                return (
                  <div
                    key={freq}
                    className="flex flex-col items-center justify-end h-full gap-0.5"
                    title={`${label} Hz: ${db >= 0 ? "+" : ""}${db} dB`}
                  >
                    <div
                      className={cn(
                        "w-full rounded-t transition-all",
                        eq.enabled ? "bg-emerald-bright/80" : "bg-zinc-600/70"
                      )}
                      style={{ height: `${heightPct}%` }}
                    />
                    <span className="text-[8px] font-mono text-zinc-500">
                      {label}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
