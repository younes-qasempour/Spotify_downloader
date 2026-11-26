import { useEffect, useRef, useState } from "react";
import {
  Disc3,
  Loader2,
  Minus,
  PanelBottomClose,
  Pause,
  Pin,
  PinOff,
  Play,
  Repeat,
  Repeat1,
  Shuffle,
  SkipBack,
  SkipForward,
  Volume2,
  VolumeX,
  X,
} from "lucide-react";
import { apiUrl } from "@/api/client";
import { MiniPlayerStudioTabs } from "@/components/player/MiniPlayerStudioTabs";
import { SpectrumVisualizerCanvas } from "@/components/player/SpectrumVisualizerCanvas";
import { QualityBadge } from "@/components/ui/badge";
import {
  hideDesktopToTray,
  minimizeDesktopWindow,
  resizeDesktopMiniPlayer,
  setDesktopAlwaysOnTop,
  startDesktopResizeDragging,
  type DesktopResizeDirection,
} from "@/lib/desktop";
import { cn, formatDuration } from "@/lib/utils";
import { useAppStore } from "@/stores/appStore";
import { usePlayerStore } from "@/stores/playerStore";

const STORAGE_KEY = "flacify.miniPlayer.v1";

const MIN_WIDTH = 300;
const MAX_WIDTH = 920;
const MIN_HEIGHT = 152;
const MAX_HEIGHT = 900;

export interface MiniPlayerGeometry {
  width: number;
  height: number;
  x: number;
  y: number;
}

const DEFAULT_GEOMETRY: MiniPlayerGeometry = {
  width: 416,
  height: 548,
  x: 32,
  y: 72,
};

const PRESETS = [
  { id: "micro", label: "Micro", width: 384, height: 156 },
  { id: "card", label: "Art", width: 360, height: 396 },
  { id: "studio", label: "Studio", width: 432, height: 584 },
] as const;

export function loadSavedMiniGeometry(): MiniPlayerGeometry {
  if (typeof window === "undefined") return DEFAULT_GEOMETRY;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_GEOMETRY;
    const parsed = JSON.parse(raw) as Partial<MiniPlayerGeometry>;
    const w = Math.max(
      MIN_WIDTH,
      Math.min(MAX_WIDTH, Number(parsed.width) || DEFAULT_GEOMETRY.width)
    );
    const h = Math.max(
      MIN_HEIGHT,
      Math.min(MAX_HEIGHT, Number(parsed.height) || DEFAULT_GEOMETRY.height)
    );
    const maxX = Math.max(16, window.innerWidth - w - 16);
    const maxY = Math.max(16, window.innerHeight - h - 16);
    const x = Math.max(12, Math.min(maxX, Number(parsed.x) || maxX));
    const y = Math.max(12, Math.min(maxY, Number(parsed.y) || maxY));
    return { width: w, height: h, x, y };
  } catch {
    return DEFAULT_GEOMETRY;
  }
}

function saveMiniGeometry(geo: MiniPlayerGeometry): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(geo));
  } catch {
    // Ignore quota errors
  }
}

interface MiniPlayerProps {
  mode: "desktop" | "web";
}

export function MiniPlayer({ mode }: MiniPlayerProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [geo, setGeo] = useState<MiniPlayerGeometry>(() => loadSavedMiniGeometry());
  const [measuredSize, setMeasuredSize] = useState({
    width: geo.width,
    height: geo.height,
  });

  const currentTrack = usePlayerStore((s) => s.currentTrack);
  const isPlaying = usePlayerStore((s) => s.isPlaying);
  const isBuffering = usePlayerStore((s) => s.isBuffering);
  const currentTimeSec = usePlayerStore((s) => s.currentTimeSec);
  const durationSec = usePlayerStore((s) => s.durationSec);
  const volume = usePlayerStore((s) => s.volume);
  const muted = usePlayerStore((s) => s.muted);
  const shuffle = usePlayerStore((s) => s.shuffle);
  const repeatMode = usePlayerStore((s) => s.repeatMode);

  const togglePlay = usePlayerStore((s) => s.togglePlay);
  const seek = usePlayerStore((s) => s.seek);
  const nextTrack = usePlayerStore((s) => s.nextTrack);
  const prevTrack = usePlayerStore((s) => s.prevTrack);
  const setVolume = usePlayerStore((s) => s.setVolume);
  const toggleMute = usePlayerStore((s) => s.toggleMute);
  const toggleShuffle = usePlayerStore((s) => s.toggleShuffle);
  const cycleRepeat = usePlayerStore((s) => s.cycleRepeat);

  const setMiniPlayerOpen = useAppStore((s) => s.setMiniPlayerOpen);
  const miniPlayerPinned = useAppStore((s) => s.miniPlayerPinned);
  const toggleMiniPlayerPinned = useAppStore((s) => s.toggleMiniPlayerPinned);
  const ambientColor = useAppStore((s) => s.ambientColor);

  const isDesktop = mode === "desktop";

  useEffect(() => {
    saveMiniGeometry(geo);
  }, [geo]);

  // Measure live dimensions so layout transitions cleanly between Micro / Art / Studio
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const updateSize = () => {
      const w = Math.round(el.clientWidth);
      const h = Math.round(el.clientHeight);
      if (w > 0 && h > 0) {
        setMeasuredSize({ width: w, height: h });
        if (isDesktop) {
          setGeo((prev) =>
            prev.width === w && prev.height === h
              ? prev
              : { ...prev, width: w, height: h }
          );
        }
      }
    };

    const observer = new ResizeObserver(updateSize);
    observer.observe(el);
    updateSize();
    return () => observer.disconnect();
  }, [isDesktop]);

  // Sync pinned state with desktop OS window Always-on-Top
  useEffect(() => {
    if (isDesktop) {
      void setDesktopAlwaysOnTop(miniPlayerPinned);
    }
  }, [isDesktop, miniPlayerPinned]);

  const effectiveDuration = durationSec || currentTrack?.durationSec || 0;
  const progressPct =
    effectiveDuration > 0
      ? Math.min(100, Math.max(0, (currentTimeSec / effectiveDuration) * 100))
      : 0;

  const tier: "micro" | "card" | "studio" =
    measuredSize.height < 230
      ? "micro"
      : measuredSize.height < 420
        ? "card"
        : "studio";

  // Keep viewport anchored at (0, 0) on mount and tier switches
  useEffect(() => {
    window.scrollTo(0, 0);
    if (containerRef.current) {
      containerRef.current.scrollTop = 0;
    }
  }, [tier]);

  // Keyboard shortcuts inside Mini Player (Escape exits to Full Studio; Arrows seek)
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (
        e.target instanceof HTMLElement &&
        (["input", "textarea", "select"].includes(e.target.tagName.toLowerCase()) ||
          e.target.isContentEditable)
      ) {
        return;
      }

      if (e.key === "Escape") {
        e.preventDefault();
        useAppStore.getState().setMiniPlayerOpen(false);
        return;
      }

      if ((e.key === "ArrowLeft" || e.key === "ArrowRight") && !e.altKey && !e.ctrlKey && !e.metaKey) {
        const st = usePlayerStore.getState();
        const dur = st.durationSec || st.currentTrack?.durationSec || 0;
        if (!st.currentTrack || dur <= 0) return;
        e.preventDefault();
        const step = e.shiftKey ? 10 : 5;
        const delta = e.key === "ArrowRight" ? step : -step;
        st.seek(Math.max(0, Math.min(dur, st.currentTimeSec + delta)));
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  const applyPreset = (w: number, h: number) => {
    if (isDesktop) {
      setGeo((prev) => ({ ...prev, width: w, height: h }));
      void resizeDesktopMiniPlayer(w, h);
    } else {
      const maxX = Math.max(12, window.innerWidth - w - 12);
      const maxY = Math.max(12, window.innerHeight - h - 12);
      setGeo((prev) => ({
        width: w,
        height: h,
        x: Math.max(12, Math.min(maxX, prev.x)),
        y: Math.max(12, Math.min(maxY, prev.y)),
      }));
    }
  };

  // Web floating drag & 8-direction resize
  const handleWebHeaderDrag = (e: React.PointerEvent<HTMLDivElement>) => {
    if (isDesktop || e.button !== 0) return;
    if ((e.target as HTMLElement).closest("button, input, a")) return;
    e.preventDefault();
    const startX = e.clientX;
    const startY = e.clientY;
    const initGeo = { ...geo };

    const onMove = (ev: PointerEvent) => {
      const dx = ev.clientX - startX;
      const dy = ev.clientY - startY;
      const maxX = Math.max(8, window.innerWidth - initGeo.width - 8);
      const maxY = Math.max(8, window.innerHeight - initGeo.height - 8);
      setGeo((prev) => ({
        ...prev,
        x: Math.max(8, Math.min(maxX, initGeo.x + dx)),
        y: Math.max(8, Math.min(maxY, initGeo.y + dy)),
      }));
    };

    const onUp = () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };

    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  };

  const handleEdgeResizeDown =
    (dir: DesktopResizeDirection) => (e: React.PointerEvent<HTMLDivElement>) => {
      if (e.button !== 0) return;
      e.preventDefault();
      e.stopPropagation();

      if (isDesktop) {
        void startDesktopResizeDragging(dir);
        return;
      }

      const startX = e.clientX;
      const startY = e.clientY;
      const init = { ...geo };

      const hasW = dir.includes("West");
      const hasE = dir.includes("East");
      const hasN = dir.includes("North");
      const hasS = dir.includes("South");

      const onMove = (ev: PointerEvent) => {
        const dx = ev.clientX - startX;
        const dy = ev.clientY - startY;

        let nextW = init.width;
        let nextH = init.height;
        let nextX = init.x;
        let nextY = init.y;

        if (hasE) {
          nextW = Math.max(
            MIN_WIDTH,
            Math.min(window.innerWidth - init.x - 8, init.width + dx)
          );
        } else if (hasW) {
          const proposedW = Math.max(
            MIN_WIDTH,
            Math.min(init.x + init.width - 8, init.width - dx)
          );
          nextX = init.x + (init.width - proposedW);
          nextW = proposedW;
        }

        if (hasS) {
          nextH = Math.max(
            MIN_HEIGHT,
            Math.min(window.innerHeight - init.y - 8, init.height + dy)
          );
        } else if (hasN) {
          const proposedH = Math.max(
            MIN_HEIGHT,
            Math.min(init.y + init.height - 8, init.height - dy)
          );
          nextY = init.y + (init.height - proposedH);
          nextH = proposedH;
        }

        setGeo({ width: nextW, height: nextH, x: nextX, y: nextY });
      };

      const onUp = () => {
        window.removeEventListener("pointermove", onMove);
        window.removeEventListener("pointerup", onUp);
      };

      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp);
    };

  const handleVolumeWheel = (e: React.WheelEvent) => {
    e.preventDefault();
    const delta = e.deltaY < 0 ? 0.05 : -0.05;
    setVolume((muted ? 0 : volume) + delta);
  };

  const coverSrc = currentTrack?.coverUrl
    ? currentTrack.coverUrl.startsWith("http")
      ? currentTrack.coverUrl
      : apiUrl(currentTrack.coverUrl)
    : "";

  const [coverFailed, setCoverFailed] = useState(false);

  useEffect(() => {
    setCoverFailed(false);
  }, [coverSrc]);

  const [r, g, b] = ambientColor;

  const artSize = Math.max(
    68,
    Math.min(184, measuredSize.height - 216, measuredSize.width - 72)
  );

  const renderScrubber = (trackHeightClass: string, ariaLabel: string) => (
    <div className="flex items-center gap-2">
      <span className="w-8 text-right text-[10px] font-mono tabular-nums text-zinc-400">
        {formatDuration(currentTimeSec, false)}
      </span>
      <div className="group relative flex-1 h-4 flex items-center">
        <div
          className={cn(
            "w-full rounded-full bg-white/14 overflow-hidden transition-[height] duration-150 group-hover:h-1.5",
            trackHeightClass
          )}
        >
          <div
            className="h-full bg-emerald-bright rounded-full transition-[width] duration-75"
            style={{ width: `${progressPct}%` }}
          />
        </div>
        {currentTrack && effectiveDuration > 0 && (
          <div
            className="pointer-events-none absolute top-1/2 -translate-y-1/2 h-2.5 w-2.5 rounded-full bg-white shadow-[0_0_8px_rgba(30,215,96,0.95)] opacity-0 scale-75 group-hover:opacity-100 group-hover:scale-100 transition-all duration-150"
            style={{ left: `calc(${progressPct}% - 5px)` }}
          />
        )}
        <input
          type="range"
          min={0}
          max={effectiveDuration || 100}
          step={0.5}
          value={currentTimeSec}
          disabled={!currentTrack || effectiveDuration <= 0}
          onChange={(e) => seek(Number(e.target.value))}
          aria-label={ariaLabel}
          className="absolute inset-0 w-full opacity-0 cursor-pointer"
        />
      </div>
      <span className="w-8 text-[10px] font-mono tabular-nums text-zinc-400">
        {formatDuration(effectiveDuration, false)}
      </span>
    </div>
  );

  return (
    <div
      ref={containerRef}
      style={
        isDesktop
          ? undefined
          : {
              width: geo.width,
              height: geo.height,
              left: geo.x,
              top: geo.y,
            }
      }
      className={cn(
        "flex flex-col overflow-hidden bg-panel text-zinc-100 select-none",
        isDesktop
          ? "fixed inset-0 h-full w-full border border-white/[0.10]"
          : "fixed z-50 rounded-2xl border border-white/15 shadow-[0_24px_70px_-10px_rgba(0,0,0,0.9)] backdrop-blur-2xl"
      )}
    >
      {/* Dynamic Ambient Artwork Backdrop */}
      {coverSrc && !coverFailed && (
        <div
          className="pointer-events-none absolute inset-0 opacity-25 blur-3xl scale-125 transition-opacity duration-500"
          style={{
            backgroundImage: `url("${coverSrc}")`,
            backgroundSize: "cover",
            backgroundPosition: "center",
          }}
        />
      )}
      <div
        className="pointer-events-none absolute inset-0"
        style={{
          background: `radial-gradient(480px circle at 20% 0%, rgba(${r}, ${g}, ${b}, 0.22), rgba(9, 10, 15, 0.9) 70%)`,
        }}
      />

      {/* 8-Direction Resize Handles */}
      {(
        [
          ["North", "inset-x-3 top-0 h-1 cursor-ns-resize"],
          ["South", "inset-x-3 bottom-0 h-1.5 cursor-ns-resize"],
          ["West", "inset-y-3 left-0 w-1.5 cursor-ew-resize"],
          ["East", "inset-y-3 right-0 w-1.5 cursor-ew-resize"],
          ["NorthWest", "top-0 left-0 h-3 w-3 cursor-nwse-resize"],
          ["NorthEast", "top-0 right-0 h-3 w-3 cursor-nesw-resize"],
          ["SouthWest", "bottom-0 left-0 h-3 w-3 cursor-nesw-resize"],
          ["SouthEast", "bottom-0 right-0 h-3.5 w-3.5 cursor-nwse-resize"],
        ] as Array<[DesktopResizeDirection, string]>
      ).map(([dir, posCls]) => (
        <div
          key={dir}
          onPointerDown={handleEdgeResizeDown(dir)}
          className={cn("absolute z-40", posCls)}
        />
      ))}

      {/* Subtle Bottom-Right Resize Grip */}
      <div className="pointer-events-none absolute bottom-1 right-1 z-30 flex items-end justify-end opacity-40">
        <svg viewBox="0 0 10 10" className="h-2.5 w-2.5 text-zinc-400">
          <path
            d="M9 1L1 9M9 5L5 9"
            stroke="currentColor"
            strokeWidth="1.4"
            strokeLinecap="round"
          />
        </svg>
      </div>

      {/* Header / Drag Region */}
      <div
        data-tauri-drag-region={isDesktop ? true : undefined}
        onPointerDown={handleWebHeaderDrag}
        onDoubleClick={(e) => {
          if ((e.target as HTMLElement).closest("button, input, a")) return;
          setMiniPlayerOpen(false);
        }}
        className={cn(
          "relative z-20 flex h-10 shrink-0 items-center justify-between gap-2 border-b border-white/[0.08] bg-black/35 px-2.5 backdrop-blur-md",
          !isDesktop && "cursor-grab active:cursor-grabbing"
        )}
      >
        <div
          data-tauri-drag-region={isDesktop ? true : undefined}
          className="flex items-center gap-1.5 min-w-0"
        >
          <span
            className={cn(
              "h-2 w-2 rounded-full shrink-0",
              isPlaying
                ? "bg-emerald-bright shadow-[0_0_8px_rgba(30,215,96,0.9)] animate-pulse"
                : "bg-zinc-500"
            )}
          />
          <span
            data-tauri-drag-region={isDesktop ? true : undefined}
            className="hidden min-[385px]:inline text-[11px] font-semibold tracking-tight text-zinc-200 truncate"
          >
            Flacify
          </span>

          {/* Size Presets */}
          <div className="flex items-center gap-0.5 rounded-lg bg-white/[0.05] p-0.5 border border-white/[0.07]">
            {PRESETS.map((p) => {
              const active =
                (p.id === "micro" && tier === "micro") ||
                (p.id === "card" && tier === "card") ||
                (p.id === "studio" && tier === "studio");
              return (
                <button
                  key={p.id}
                  type="button"
                  onClick={() => applyPreset(p.width, p.height)}
                  className={cn(
                    "rounded-md px-1.5 py-0.5 text-[10px] font-medium transition-colors cursor-pointer",
                    active
                      ? "bg-emerald-500/25 text-emerald-300"
                      : "text-zinc-400 hover:text-zinc-200"
                  )}
                  title={`${p.label} (${p.width}×${p.height})`}
                >
                  {p.label}
                </button>
              );
            })}
          </div>
        </div>

        <div className="flex items-center gap-0.5 shrink-0">
          {isDesktop ? (
            <>
              <button
                type="button"
                onClick={toggleMiniPlayerPinned}
                className={cn(
                  "h-7 w-7 flex items-center justify-center rounded-md transition-colors cursor-pointer",
                  miniPlayerPinned
                    ? "text-emerald-300 bg-emerald-500/15"
                    : "text-zinc-400 hover:bg-white/10 hover:text-white"
                )}
                title={
                  miniPlayerPinned
                    ? "Always on Top: Enabled (Click to unpin)"
                    : "Pin Always on Top"
                }
                aria-label="Toggle Always on Top"
              >
                {miniPlayerPinned ? (
                  <Pin className="h-3.5 w-3.5" />
                ) : (
                  <PinOff className="h-3.5 w-3.5" />
                )}
              </button>
              <button
                type="button"
                onClick={() => void hideDesktopToTray()}
                className="h-7 w-7 flex items-center justify-center rounded-md text-zinc-400 hover:bg-white/10 hover:text-white transition-colors cursor-pointer"
                title="Hide to System Tray"
                aria-label="Hide to System Tray"
              >
                <PanelBottomClose className="h-3.5 w-3.5" />
              </button>
              <button
                type="button"
                onClick={() => void minimizeDesktopWindow()}
                className="h-7 w-7 flex items-center justify-center rounded-md text-zinc-400 hover:bg-white/10 hover:text-white transition-colors cursor-pointer"
                title="Minimize"
                aria-label="Minimize Window"
              >
                <Minus className="h-3.5 w-3.5" />
              </button>
            </>
          ) : null}

          <button
            type="button"
            onClick={() => setMiniPlayerOpen(false)}
            className="h-7 w-7 flex items-center justify-center rounded-md text-zinc-300 hover:bg-white/15 hover:text-white transition-colors cursor-pointer"
            title="Close Mini Player (Return to Studio · Alt+M)"
            aria-label="Close Mini Player"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      {/* Main Content Area by Size Tier */}
      <div className="relative z-10 flex-1 min-h-0 flex flex-col overflow-hidden">
        {tier === "micro" ? (
          /* MICRO STRIP TIER (< 230px height) */
          <div className="flex-1 min-h-0 flex flex-col justify-between px-3 py-2 overflow-hidden">
            <div className="flex items-center justify-between gap-2.5 min-w-0 flex-1">
              <div className="flex items-center gap-2.5 min-w-0 flex-1">
                <div className="relative h-12 w-12 shrink-0 overflow-hidden rounded-xl bg-elevated border border-white/10 shadow-md">
                  {coverSrc && !coverFailed ? (
                    <img
                      src={coverSrc}
                      alt={currentTrack?.title || "Cover"}
                      onError={() => setCoverFailed(true)}
                      className="h-full w-full object-cover"
                    />
                  ) : (
                    <div className="flex h-full w-full items-center justify-center text-zinc-500">
                      <Disc3
                        className={cn(
                          "h-5 w-5",
                          isPlaying && "animate-spin text-emerald-400"
                        )}
                      />
                    </div>
                  )}
                </div>

                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5 min-w-0">
                    <span className="truncate text-sm font-semibold text-white">
                      {currentTrack ? currentTrack.title : "Ready to Play"}
                    </span>
                    {currentTrack?.qualityBadge && (
                      <QualityBadge
                        badge={currentTrack.qualityBadge}
                        className="shrink-0 text-[9px] px-1.5 py-0"
                      />
                    )}
                  </div>
                  <div className="truncate text-xs text-zinc-400">
                    {currentTrack ? currentTrack.artist : "Select any track"}
                  </div>
                </div>
              </div>

              <div className="flex items-center gap-1 shrink-0">
                <button
                  type="button"
                  onClick={prevTrack}
                  disabled={!currentTrack}
                  className="rounded-lg p-1.5 text-zinc-300 hover:text-white disabled:opacity-40 cursor-pointer"
                  title="Previous"
                >
                  <SkipBack className="h-4 w-4 fill-current" />
                </button>
                <button
                  type="button"
                  onClick={togglePlay}
                  disabled={!currentTrack}
                  className="flex h-9 w-9 items-center justify-center rounded-full bg-white text-black hover:scale-105 active:scale-95 transition-transform disabled:opacity-40 cursor-pointer shadow"
                  title={isPlaying ? "Pause (Space)" : "Play (Space)"}
                >
                  {isBuffering ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : isPlaying ? (
                    <Pause className="h-4 w-4 fill-current" />
                  ) : (
                    <Play className="h-4 w-4 fill-current translate-x-[1px]" />
                  )}
                </button>
                <button
                  type="button"
                  onClick={nextTrack}
                  disabled={!currentTrack}
                  className="rounded-lg p-1.5 text-zinc-300 hover:text-white disabled:opacity-40 cursor-pointer"
                  title="Next"
                >
                  <SkipForward className="h-4 w-4 fill-current" />
                </button>
              </div>
            </div>

            {/* Bottom edge scrubber */}
            <div className="shrink-0 pt-1">
              {renderScrubber("h-1", "Seek")}
            </div>
          </div>
        ) : (
          /* ART CARD (230..419px) OR STUDIO DECK (>= 420px) */
          <>
            <div
              className={cn(
                "flex flex-col",
                tier === "card"
                  ? "flex-1 min-h-0 justify-between px-3.5 pt-2.5 pb-3 gap-2 overflow-hidden"
                  : "shrink-0 px-3.5 pt-2.5 pb-2.5 gap-2.5"
              )}
            >
              {/* Artwork + Title/Spectrum Row */}
              <div
                onWheel={handleVolumeWheel}
                className={cn(
                  "flex items-center",
                  tier === "card"
                    ? "flex-1 min-h-0 flex-col justify-center gap-2 overflow-hidden"
                    : "gap-3"
                )}
              >
                <div
                  style={
                    tier === "card"
                      ? { width: artSize, height: artSize }
                      : undefined
                  }
                  className={cn(
                    "relative overflow-hidden rounded-2xl bg-elevated border border-white/10 shadow-xl shrink-0",
                    tier === "studio" && "h-[72px] w-[72px]"
                  )}
                >
                  {coverSrc && !coverFailed ? (
                    <img
                      src={coverSrc}
                      alt={currentTrack?.title || "Album Art"}
                      onError={() => setCoverFailed(true)}
                      className="h-full w-full object-cover"
                    />
                  ) : (
                    <div className="flex h-full w-full items-center justify-center text-zinc-500">
                      <Disc3
                        className={cn(
                          "h-9 w-9",
                          isPlaying && "animate-spin text-emerald-400"
                        )}
                      />
                    </div>
                  )}
                  {tier === "card" && artSize >= 96 && (
                    <div className="absolute inset-x-2 bottom-1.5 h-7 opacity-90">
                      <SpectrumVisualizerCanvas isPlaying={isPlaying} barCount={22} />
                    </div>
                  )}
                </div>

                <div
                  className={cn(
                    "min-w-0 w-full",
                    tier === "card" ? "shrink-0 text-center" : "flex-1"
                  )}
                >
                  <div
                    className={cn(
                      "flex items-center gap-2 min-w-0",
                      tier === "card" && "justify-center"
                    )}
                  >
                    <h2 className="text-sm font-bold text-white truncate">
                      {currentTrack ? currentTrack.title : "Ready to Play"}
                    </h2>
                    {currentTrack?.qualityBadge && (
                      <QualityBadge
                        badge={currentTrack.qualityBadge}
                        className="shrink-0 text-[9px] px-1.5 py-0"
                      />
                    )}
                  </div>
                  <p className="text-xs text-zinc-400 truncate mt-0.5">
                    {currentTrack
                      ? currentTrack.artist
                      : "Pick any downloaded track from Library"}
                  </p>

                  {tier === "studio" && (
                    <div className="mt-2 h-6 w-full">
                      <SpectrumVisualizerCanvas isPlaying={isPlaying} barCount={28} />
                    </div>
                  )}
                </div>
              </div>

              {/* Scrubber */}
              <div className="shrink-0">
                {renderScrubber("h-1.5", "Seek track position")}
              </div>

              {/* Transport + Volume */}
              <div className="flex shrink-0 items-center justify-between gap-2">
                <div className="flex items-center gap-1.5">
                  <button
                    type="button"
                    onClick={toggleShuffle}
                    className={cn(
                      "rounded-lg p-1.5 transition-colors cursor-pointer",
                      shuffle
                        ? "text-emerald-bright bg-emerald-500/15"
                        : "text-zinc-400 hover:text-white"
                    )}
                    title="Shuffle"
                  >
                    <Shuffle className="h-3.5 w-3.5" />
                  </button>
                  <button
                    type="button"
                    onClick={prevTrack}
                    disabled={!currentTrack}
                    className="rounded-lg p-1.5 text-zinc-300 hover:text-white disabled:opacity-40 cursor-pointer"
                    title="Previous"
                  >
                    <SkipBack className="h-4 w-4 fill-current" />
                  </button>
                  <button
                    type="button"
                    onClick={togglePlay}
                    disabled={!currentTrack}
                    className="flex h-9 w-9 items-center justify-center rounded-full bg-white text-black hover:scale-105 active:scale-95 transition-transform disabled:opacity-40 cursor-pointer shadow-lg"
                    title={isPlaying ? "Pause (Space)" : "Play (Space)"}
                  >
                    {isBuffering ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : isPlaying ? (
                      <Pause className="h-4 w-4 fill-current" />
                    ) : (
                      <Play className="h-4 w-4 fill-current translate-x-[1px]" />
                    )}
                  </button>
                  <button
                    type="button"
                    onClick={nextTrack}
                    disabled={!currentTrack}
                    className="rounded-lg p-1.5 text-zinc-300 hover:text-white disabled:opacity-40 cursor-pointer"
                    title="Next"
                  >
                    <SkipForward className="h-4 w-4 fill-current" />
                  </button>
                  <button
                    type="button"
                    onClick={cycleRepeat}
                    className={cn(
                      "rounded-lg p-1.5 transition-colors cursor-pointer",
                      repeatMode !== "off"
                        ? "text-emerald-bright bg-emerald-500/15"
                        : "text-zinc-400 hover:text-white"
                    )}
                    title={`Repeat: ${repeatMode}`}
                  >
                    {repeatMode === "one" ? (
                      <Repeat1 className="h-3.5 w-3.5" />
                    ) : (
                      <Repeat className="h-3.5 w-3.5" />
                    )}
                  </button>
                </div>

                {/* Volume Strip (scroll wheel also adjusts) */}
                <div
                  onWheel={handleVolumeWheel}
                  className="flex items-center gap-1.5 shrink-0"
                  title="Volume (Scroll wheel adjusts)"
                >
                  <button
                    type="button"
                    onClick={toggleMute}
                    className="rounded-md p-1 text-zinc-400 hover:text-white cursor-pointer"
                    aria-label={muted ? "Unmute" : "Mute"}
                  >
                    {muted || volume === 0 ? (
                      <VolumeX className="h-3.5 w-3.5 text-zinc-500" />
                    ) : (
                      <Volume2 className="h-3.5 w-3.5" />
                    )}
                  </button>
                  <input
                    type="range"
                    min={0}
                    max={1}
                    step={0.02}
                    value={muted ? 0 : volume}
                    onChange={(e) => setVolume(Number(e.target.value))}
                    aria-label="Mini player volume"
                    className="hidden min-[330px]:block w-16 accent-emerald-500 cursor-pointer h-1"
                  />
                </div>
              </div>
            </div>

            {tier === "studio" && <MiniPlayerStudioTabs />}
          </>
        )}
      </div>
    </div>
  );
}
