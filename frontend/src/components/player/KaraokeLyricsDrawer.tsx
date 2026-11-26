import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  Copy,
  Disc3,
  Download,
  Loader2,
  Music2,
  RefreshCw,
  X,
} from "lucide-react";
import { toast } from "sonner";
import { apiUrl } from "@/api/client";
import { api } from "@/api/endpoints";
import type { LyricLine } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn, formatDuration } from "@/lib/utils";
import { useAppStore } from "@/stores/appStore";
import { usePlayerStore } from "@/stores/playerStore";

type TranslationLang = "none" | "en" | "fa";

function cleanTranslatedText(raw: string | undefined, sourceText: string): string {
  const cleaned = (raw || "").trim();
  if (!cleaned) return "";
  if (cleaned.toUpperCase().includes("PLEASE SELECT TWO DISTINCT")) return "";
  if (cleaned.toLowerCase() === sourceText.trim().toLowerCase()) return "";
  return cleaned;
}

export function KaraokeLyricsDrawer() {
  const open = useAppStore((s) => s.lyricsDrawerOpen);
  const setOpen = useAppStore((s) => s.setLyricsDrawerOpen);

  const currentTrack = usePlayerStore((s) => s.currentTrack);
  const currentTimeSec = usePlayerStore((s) => s.currentTimeSec);
  const seek = usePlayerStore((s) => s.seek);

  const [lines, setLines] = useState<LyricLine[]>([]);
  const [isSynced, setIsSynced] = useState(true);
  const [source, setSource] = useState<string>("none");
  const [transLang, setTransLang] = useState<TranslationLang>("none");
  const [loading, setLoading] = useState(false);
  const [fetchingOnline, setFetchingOnline] = useState(false);
  const [translating, setTranslating] = useState(false);
  const [exporting, setExporting] = useState(false);

  const langInitializedRef = useRef(false);
  const userScrollingRef = useRef(false);
  const scrollResumeTimerRef = useRef<number | null>(null);
  const activeLineRef = useRef<HTMLButtonElement | null>(null);
  const scrollContainerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, setOpen]);

  // Load lyrics + persisted translation preference whenever drawer opens or track changes
  useEffect(() => {
    if (!open || !currentTrack) return;
    let cancelled = false;

    const load = async () => {
      setLoading(true);
      try {
        let langToUse = transLang;
        if (!langInitializedRef.current) {
          langInitializedRef.current = true;
          try {
            const sRes = await api.settings.get();
            const saved = String(
              sRes.config.ui?.lyrics_translation_lang || "none"
            ).toLowerCase();
            if (saved === "en" || saved === "fa") {
              langToUse = saved;
              if (!cancelled) setTransLang(saved);
            }
          } catch {
            // Fall back cleanly
          }
        }

        const res = await api.lyrics.get(currentTrack.id, langToUse);
        if (cancelled) return;
        setLines(res.lines || []);
        setIsSynced(Boolean(res.is_synced));
        setSource(res.source || "none");
      } catch {
        if (!cancelled) {
          setLines([]);
          setIsSynced(false);
          setSource("none");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    void load();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, currentTrack?.id]);

  const handleSelectLanguage = async (lang: TranslationLang) => {
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
        prev.map((line, i) => ({
          ...line,
          translated: res.translated_lines[i] || "",
        }))
      );
    } catch {
      toast.error("Lyrics translation failed", {
        description: "Check internet connection.",
      });
    } finally {
      setTranslating(false);
    }
  };

  const handleFetchOnline = async () => {
    if (!currentTrack || fetchingOnline) return;
    setFetchingOnline(true);
    try {
      const res = await api.lyrics.fetch(currentTrack.id);
      if (res.found && res.lines.length > 0) {
        let nextLines = res.lines;
        if (transLang === "en" || transLang === "fa") {
          try {
            const tr = await api.lyrics.translate(
              nextLines.map((l) => l.text),
              transLang,
              false
            );
            nextLines = nextLines.map((line, i) => ({
              ...line,
              translated: tr.translated_lines[i] || "",
            }));
          } catch {
            // Keep untagged lines if translation fails
          }
        }
        setLines(nextLines);
        setIsSynced(Boolean(res.is_synced));
        setSource("lrclib");
        toast.success(
          res.is_synced
            ? "Synchronized lyrics fetched & embedded!"
            : "Plain lyrics fetched & embedded!"
        );
      } else {
        toast.warning("No lyrics found on LRCLIB for this track.");
      }
    } catch (err) {
      toast.error("Failed to fetch lyrics", {
        description: err instanceof Error ? err.message : undefined,
      });
    } finally {
      setFetchingOnline(false);
    }
  };

  const handleCopyLyrics = useCallback(async () => {
    if (!lines.length) return;
    const content = lines
      .map((l) => {
        const sub = cleanTranslatedText(l.translated, l.text);
        return sub ? `${l.text}\n  [${sub}]` : l.text;
      })
      .join("\n");
    try {
      await navigator.clipboard.writeText(content);
      toast.success("Copied lyrics to clipboard");
    } catch {
      toast.error("Clipboard copy failed");
    }
  }, [lines]);

  const handleExportLrc = async () => {
    if (!currentTrack || !lines.length || exporting) return;
    setExporting(true);
    try {
      const res = await api.lyrics.exportLrc(currentTrack.id, {
        include_translation: transLang !== "none",
        target_lang: transLang === "none" ? undefined : transLang,
        write_to_disk: true,
      });
      toast.success("Saved .lrc file", {
        description: res.saved_path || undefined,
        action: res.saved_path
          ? {
              label: "Reveal",
              onClick: () =>
                void api.settings.openFolder(res.saved_path || undefined, true),
            }
          : undefined,
      });
    } catch (err) {
      toast.error("Failed to export .lrc", {
        description: err instanceof Error ? err.message : undefined,
      });
    } finally {
      setExporting(false);
    }
  };

  const posMs = currentTimeSec * 1000;
  const activeIndex = useMemo(() => {
    if (!isSynced || !lines.length) return -1;
    let idx = -1;
    for (let i = 0; i < lines.length; i += 1) {
      if (lines[i].timestamp_ms <= posMs + 120) {
        idx = i;
      } else {
        break;
      }
    }
    return idx;
  }, [isSynced, lines, posMs]);

  useEffect(() => {
    if (
      !open ||
      activeIndex < 0 ||
      userScrollingRef.current ||
      !activeLineRef.current ||
      !scrollContainerRef.current
    ) {
      return;
    }
    const container = scrollContainerRef.current;
    const lineEl = activeLineRef.current;
    const containerRect = container.getBoundingClientRect();
    const lineRect = lineEl.getBoundingClientRect();
    const targetTop =
      container.scrollTop +
      (lineRect.top - containerRect.top) -
      container.clientHeight / 2 +
      lineRect.height / 2;
    container.scrollTo({
      top: Math.max(0, targetTop),
      behavior: "smooth",
    });
  }, [activeIndex, open]);

  const handleViewportWheelOrTouch = () => {
    userScrollingRef.current = true;
    if (scrollResumeTimerRef.current !== null) {
      window.clearTimeout(scrollResumeTimerRef.current);
    }
    scrollResumeTimerRef.current = window.setTimeout(() => {
      userScrollingRef.current = false;
    }, 3500);
  };

  const coverSrc = currentTrack?.coverUrl
    ? currentTrack.coverUrl.startsWith("http")
      ? currentTrack.coverUrl
      : apiUrl(currentTrack.coverUrl)
    : "";

  return (
    <AnimatePresence>
      {open && (
        <div className="fixed inset-0 z-40 flex justify-end">
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={() => setOpen(false)}
            className="fixed inset-0 bg-black/60 backdrop-blur-xs"
          />

          <motion.aside
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ type: "spring", stiffness: 360, damping: 36 }}
            className="relative z-10 flex h-full w-full max-w-[540px] flex-col bg-panel/95 backdrop-blur-2xl border-l border-white/10 shadow-2xl pb-[96px]"
          >
            {/* Header Card */}
            <div className="border-b border-white/[0.08] p-4 space-y-3">
              <div className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-3 min-w-0">
                  <div className="h-12 w-12 shrink-0 overflow-hidden rounded-xl bg-elevated border border-white/10">
                    {coverSrc ? (
                      <img
                        src={coverSrc}
                        alt={currentTrack?.title || "Track"}
                        className="h-full w-full object-cover"
                      />
                    ) : (
                      <div className="flex h-full w-full items-center justify-center text-zinc-500">
                        <Disc3 className="h-5 w-5" />
                      </div>
                    )}
                  </div>
                  <div className="min-w-0">
                    <h2 className="truncate text-sm font-semibold text-white">
                      {currentTrack?.title || "No Track Playing"}
                    </h2>
                    <p className="truncate text-xs text-zinc-400">
                      {currentTrack?.artist ||
                        "Play a song from Library or Queue"}
                    </p>
                  </div>
                </div>

                <button
                  type="button"
                  onClick={() => setOpen(false)}
                  className="rounded-lg p-1.5 text-zinc-400 hover:bg-white/10 hover:text-white cursor-pointer"
                  aria-label="Close lyrics drawer"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>

              {/* Controls: Status + 3-Pill Translation Switcher + Actions */}
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <Badge variant={isSynced ? "emerald" : "default"}>
                    {lines.length === 0
                      ? "No Lyrics"
                      : isSynced
                        ? `Synced (${source})`
                        : `Plain (${source})`}
                  </Badge>

                  {/* 3-Pill Translation Switcher */}
                  <div className="inline-flex rounded-full bg-black/50 p-0.5 border border-white/10 text-[11px]">
                    {(
                      [
                        ["none", "Original"],
                        ["en", "English"],
                        ["fa", "فارسی"],
                      ] as Array<[TranslationLang, string]>
                    ).map(([id, label]) => (
                      <button
                        key={id}
                        type="button"
                        disabled={translating && transLang === id}
                        onClick={() => void handleSelectLanguage(id)}
                        className={cn(
                          "rounded-full px-3 py-1 font-semibold transition-colors cursor-pointer",
                          transLang === id
                            ? "bg-emerald-brand text-black"
                            : "text-zinc-400 hover:text-white"
                        )}
                      >
                        {translating && transLang === id ? "..." : label}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="flex items-center gap-1">
                  <Button
                    type="button"
                    size="icon"
                    variant="ghost"
                    className="h-8 w-8"
                    disabled={!currentTrack || fetchingOnline}
                    onClick={() => void handleFetchOnline()}
                    title="Sync / Fetch Lyrics Online from LRCLIB"
                  >
                    <RefreshCw
                      className={cn(
                        "h-3.5 w-3.5",
                        fetchingOnline && "animate-spin text-emerald-bright"
                      )}
                    />
                  </Button>

                  <Button
                    type="button"
                    size="icon"
                    variant="ghost"
                    className="h-8 w-8"
                    disabled={!lines.length}
                    onClick={() => void handleCopyLyrics()}
                    title="Copy Lyrics to Clipboard"
                  >
                    <Copy className="h-3.5 w-3.5" />
                  </Button>

                  <Button
                    type="button"
                    size="icon"
                    variant="ghost"
                    className="h-8 w-8"
                    disabled={!lines.length || exporting}
                    onClick={() => void handleExportLrc()}
                    title="Save Synchronized .lrc File Beside Audio"
                  >
                    <Download className="h-3.5 w-3.5" />
                  </Button>
                </div>
              </div>
            </div>

            {/* Karaoke Scrolling Viewport */}
            <div
              ref={scrollContainerRef}
              onWheel={handleViewportWheelOrTouch}
              onTouchStart={handleViewportWheelOrTouch}
              className="flex-1 overflow-y-auto px-4 py-6 space-y-1.5"
            >
              {!currentTrack ? (
                <div className="h-full flex flex-col items-center justify-center text-center gap-2 text-zinc-400 px-6">
                  <Music2 className="h-8 w-8 text-zinc-600" />
                  <p className="text-sm">
                    Start playing any downloaded song to view synchronized
                    karaoke lyrics and translations.
                  </p>
                </div>
              ) : loading ? (
                <div className="h-full flex flex-col items-center justify-center gap-2 text-zinc-400 text-sm">
                  <Loader2 className="h-6 w-6 animate-spin text-emerald-bright" />
                  <span>Loading lyrics...</span>
                </div>
              ) : lines.length === 0 ? (
                <div className="h-full flex flex-col items-center justify-center text-center gap-3 px-6">
                  <Music2 className="h-8 w-8 text-zinc-600" />
                  <p className="text-sm text-zinc-400 max-w-xs">
                    No embedded or companion `.lrc` lyrics found for this track.
                  </p>
                  <Button
                    type="button"
                    size="sm"
                    disabled={fetchingOnline}
                    onClick={() => void handleFetchOnline()}
                  >
                    <RefreshCw
                      className={cn(
                        "h-3.5 w-3.5",
                        fetchingOnline && "animate-spin"
                      )}
                    />
                    {fetchingOnline
                      ? "Searching LRCLIB..."
                      : "Fetch Synced Lyrics from LRCLIB"}
                  </Button>
                </div>
              ) : (
                lines.map((line, idx) => {
                  const isActive = isSynced && idx === activeIndex;
                  const isPast = isSynced && activeIndex >= 0 && idx < activeIndex;
                  const transText = cleanTranslatedText(
                    line.translated,
                    line.text
                  );
                  return (
                    <button
                      key={`${idx}-${line.timestamp_ms}`}
                      ref={isActive ? activeLineRef : undefined}
                      type="button"
                      disabled={!isSynced}
                      onClick={() => {
                        if (isSynced) {
                          seek(line.timestamp_ms / 1000);
                        }
                      }}
                      className={cn(
                        "w-full flex items-start gap-3.5 rounded-xl px-4 py-2.5 text-left transition-all border-l-3",
                        isSynced && "cursor-pointer",
                        isActive
                          ? "bg-emerald-500/15 border-emerald-bright shadow-sm"
                          : "border-transparent hover:bg-white/[0.04]"
                      )}
                    >
                      <span
                        className={cn(
                          "w-11 shrink-0 pt-0.5 text-[11px] font-mono tabular-nums",
                          isActive ? "text-emerald-bright font-bold" : "text-zinc-500"
                        )}
                      >
                        {isSynced
                          ? formatDuration(line.timestamp_ms, true)
                          : "·"}
                      </span>

                      <div className="min-w-0 flex-1 space-y-1">
                        <div
                          className={cn(
                            "leading-snug transition-colors",
                            isActive
                              ? "text-[17px] font-bold text-emerald-bright"
                              : isPast
                                ? "text-[15px] font-semibold text-zinc-500"
                                : "text-[15px] font-semibold text-zinc-200"
                          )}
                        >
                          {line.text}
                        </div>

                        {transText && (
                          <div
                            dir={transLang === "fa" ? "rtl" : "ltr"}
                            className={cn(
                              "leading-snug",
                              transLang === "fa" && "text-right",
                              isActive
                                ? "text-sm font-semibold text-emerald-200"
                                : isPast
                                  ? "text-xs text-zinc-600"
                                  : "text-xs text-zinc-400"
                            )}
                          >
                            {transText}
                          </div>
                        )}
                      </div>
                    </button>
                  );
                })
              )}
            </div>
          </motion.aside>
        </div>
      )}
    </AnimatePresence>
  );
}
