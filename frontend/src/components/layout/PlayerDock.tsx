import { useEffect } from "react";
import {
  AlertCircle,
  Disc3,
  ListMusic,
  Loader2,
  Pause,
  PictureInPicture2,
  Play,
  Repeat,
  Repeat1,
  Shuffle,
  SkipBack,
  SkipForward,
  SlidersHorizontal,
  Volume2,
  VolumeX,
} from "lucide-react";
import { apiUrl } from "@/api/client";
import { QualityBadge } from "@/components/ui/badge";
import { extractAmbientColor } from "@/lib/colorExtract";
import { cn, formatDuration } from "@/lib/utils";
import { useAppStore } from "@/stores/appStore";
import { usePlayerStore } from "@/stores/playerStore";

export function PlayerDock() {
  const currentTrack = usePlayerStore((s) => s.currentTrack);
  const isPlaying = usePlayerStore((s) => s.isPlaying);
  const isBuffering = usePlayerStore((s) => s.isBuffering);
  const audioError = usePlayerStore((s) => s.audioError);
  const currentTimeSec = usePlayerStore((s) => s.currentTimeSec);
  const durationSec = usePlayerStore((s) => s.durationSec);
  const volume = usePlayerStore((s) => s.volume);
  const muted = usePlayerStore((s) => s.muted);
  const shuffle = usePlayerStore((s) => s.shuffle);
  const repeatMode = usePlayerStore((s) => s.repeatMode);
  const eqEnabled = usePlayerStore((s) => s.eq.enabled);

  const togglePlay = usePlayerStore((s) => s.togglePlay);
  const seek = usePlayerStore((s) => s.seek);
  const nextTrack = usePlayerStore((s) => s.nextTrack);
  const prevTrack = usePlayerStore((s) => s.prevTrack);
  const setVolume = usePlayerStore((s) => s.setVolume);
  const toggleMute = usePlayerStore((s) => s.toggleMute);
  const toggleShuffle = usePlayerStore((s) => s.toggleShuffle);
  const cycleRepeat = usePlayerStore((s) => s.cycleRepeat);

  const lyricsDrawerOpen = useAppStore((s) => s.lyricsDrawerOpen);
  const toggleLyricsDrawer = useAppStore((s) => s.toggleLyricsDrawer);
  const eqPopoverOpen = useAppStore((s) => s.eqPopoverOpen);
  const toggleEqPopover = useAppStore((s) => s.toggleEqPopover);
  const miniPlayerOpen = useAppStore((s) => s.miniPlayerOpen);
  const toggleMiniPlayer = useAppStore((s) => s.toggleMiniPlayer);
  const setAmbientColor = useAppStore((s) => s.setAmbientColor);
  const resetAmbientColor = useAppStore((s) => s.resetAmbientColor);

  const coverSrc = currentTrack?.coverUrl
    ? currentTrack.coverUrl.startsWith("http")
      ? currentTrack.coverUrl
      : apiUrl(currentTrack.coverUrl)
    : "";

  useEffect(() => {
    let cancelled = false;
    if (!coverSrc) {
      resetAmbientColor();
      return;
    }
    void extractAmbientColor(coverSrc).then((rgb) => {
      if (!cancelled && rgb) {
        setAmbientColor(rgb);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [coverSrc, resetAmbientColor, setAmbientColor]);

  const effectiveDuration = durationSec || currentTrack?.durationSec || 0;
  const progressPct =
    effectiveDuration > 0
      ? Math.min(100, Math.max(0, (currentTimeSec / effectiveDuration) * 100))
      : 0;

  return (
    <div className="mx-2 sm:mx-3 mb-2 sm:mb-3 rounded-2xl glass-dock px-3 sm:px-4 py-2.5 sm:py-0 sm:h-[84px]">
      {/* Mobile Compact 2-Row Dock (< sm) */}
      <div className="flex sm:hidden flex-col gap-2 w-full">
        <div className="flex items-center justify-between gap-2.5 min-w-0">
          <div className="flex items-center gap-2.5 min-w-0 flex-1">
            <div className="relative h-10 w-10 shrink-0 overflow-hidden rounded-lg bg-elevated border border-white/[0.08]">
              {coverSrc ? (
                <img
                  src={coverSrc}
                  alt={currentTrack?.title || "Album Art"}
                  className="h-full w-full object-cover"
                />
              ) : (
                <div className="flex h-full w-full items-center justify-center text-zinc-500">
                  <Disc3
                    className={cn(
                      "h-4 w-4",
                      isPlaying && "animate-spin text-emerald-400"
                    )}
                  />
                </div>
              )}
            </div>

            <div className="min-w-0 flex-1">
              <div className="truncate text-xs font-semibold text-white">
                {currentTrack ? currentTrack.title : "Ready to Play"}
              </div>
              <div className="truncate text-[11px] text-zinc-400">
                {audioError
                  ? audioError
                  : currentTrack
                    ? currentTrack.artist
                    : "Pick any track from Library"}
              </div>
            </div>
          </div>

          <div className="flex items-center gap-1 shrink-0">
            <button
              type="button"
              onClick={prevTrack}
              disabled={!currentTrack}
              className="rounded-lg p-1.5 text-zinc-300 hover:text-white disabled:opacity-40 cursor-pointer"
              title="Previous Track"
            >
              <SkipBack className="h-4 w-4 fill-current" />
            </button>
            <button
              type="button"
              onClick={togglePlay}
              disabled={!currentTrack}
              className="flex h-8 w-8 items-center justify-center rounded-full bg-white text-black disabled:opacity-40 cursor-pointer shadow-md"
              title={isPlaying ? "Pause" : "Play"}
            >
              {isBuffering ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : isPlaying ? (
                <Pause className="h-3.5 w-3.5 fill-current" />
              ) : (
                <Play className="h-3.5 w-3.5 fill-current translate-x-[0.5px]" />
              )}
            </button>
            <button
              type="button"
              onClick={nextTrack}
              disabled={!currentTrack}
              className="rounded-lg p-1.5 text-zinc-300 hover:text-white disabled:opacity-40 cursor-pointer"
              title="Next Track"
            >
              <SkipForward className="h-4 w-4 fill-current" />
            </button>
            <button
              type="button"
              onClick={toggleLyricsDrawer}
              className={cn(
                "rounded-lg p-1.5 transition-colors cursor-pointer border",
                lyricsDrawerOpen
                  ? "bg-emerald-500/15 text-emerald-300 border-emerald-500/30"
                  : "text-zinc-400 border-transparent hover:text-white"
              )}
              title="Synced Lyrics Drawer"
            >
              <ListMusic className="h-4 w-4" />
            </button>
            <button
              type="button"
              onClick={toggleEqPopover}
              className={cn(
                "relative rounded-lg p-1.5 transition-colors cursor-pointer border",
                eqPopoverOpen || eqEnabled
                  ? "bg-emerald-500/15 text-emerald-300 border-emerald-500/30"
                  : "text-zinc-400 border-transparent hover:text-white"
              )}
              title="10-Band Equalizer"
            >
              <SlidersHorizontal className="h-4 w-4" />
              {eqEnabled && (
                <span className="absolute top-1 right-1 h-1.5 w-1.5 rounded-full bg-emerald-bright" />
              )}
            </button>
            <button
              type="button"
              onClick={toggleMiniPlayer}
              className={cn(
                "rounded-lg p-1.5 transition-colors cursor-pointer border",
                miniPlayerOpen
                  ? "bg-emerald-500/15 text-emerald-300 border-emerald-500/30"
                  : "text-zinc-400 border-transparent hover:text-white"
              )}
              title="Studio Mini Player (Alt+M)"
            >
              <PictureInPicture2 className="h-4 w-4" />
            </button>
          </div>
        </div>

        <div className="flex w-full items-center gap-2">
          <span className="w-8 text-right text-[10px] font-mono tabular-nums text-zinc-400">
            {formatDuration(currentTimeSec, false)}
          </span>
          <div className="relative flex-1 flex items-center h-3.5">
            <div className="h-1 w-full rounded-full bg-white/10 overflow-hidden">
              <div
                className="h-full rounded-full bg-emerald-bright transition-[width] duration-75"
                style={{ width: `${progressPct}%` }}
              />
            </div>
            <input
              type="range"
              min={0}
              max={effectiveDuration || 100}
              step={0.5}
              value={currentTimeSec}
              disabled={!currentTrack || effectiveDuration <= 0}
              onChange={(e) => seek(Number(e.target.value))}
              aria-label="Mobile playback position"
              className="absolute inset-0 w-full opacity-0 cursor-pointer disabled:cursor-default"
            />
          </div>
          <span className="w-8 text-[10px] font-mono tabular-nums text-zinc-400">
            {formatDuration(effectiveDuration, false)}
          </span>
        </div>
      </div>

      {/* Desktop 3-Column Dock (sm+) */}
      <div className="hidden sm:flex h-full items-center justify-between gap-5">
      {/* Left: Now Playing Metadata */}
      <div className="flex items-center gap-3 min-w-0 w-[34%] max-w-[320px]">
        <div className="relative h-12 w-12 shrink-0 overflow-hidden rounded-xl bg-elevated border border-white/[0.08] shadow-lg">
          {coverSrc ? (
            <img
              src={coverSrc}
              alt={currentTrack?.title || "Album Art"}
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
          <div className="flex items-center gap-2 min-w-0">
            <span className="truncate text-sm font-semibold text-white">
              {currentTrack ? currentTrack.title : "Ready to Play"}
            </span>
            {currentTrack?.qualityBadge && (
              <QualityBadge
                badge={currentTrack.qualityBadge}
                sourceType={currentTrack.sourceType}
                className="hidden md:inline-flex shrink-0"
              />
            )}
          </div>
          <p className="truncate text-xs text-zinc-400 mt-0.5 flex items-center gap-1.5">
            {audioError ? (
              <span className="inline-flex items-center gap-1 text-red-300 truncate">
                <AlertCircle className="h-3 w-3 shrink-0" />
                {audioError}
              </span>
            ) : currentTrack ? (
              currentTrack.artist
            ) : (
              "Pick any downloaded track from your library"
            )}
          </p>
        </div>
      </div>

      {/* Center: Transport & Scrubber */}
      <div className="flex flex-1 max-w-[520px] flex-col items-center gap-1.5 min-w-0">
        <div className="flex items-center gap-2 sm:gap-3">
          <button
            type="button"
            onClick={toggleShuffle}
            className={cn(
              "hidden sm:inline-flex rounded-lg p-1.5 transition-colors cursor-pointer",
              shuffle
                ? "text-emerald-bright bg-emerald-500/12"
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
            title="Previous Track"
          >
            <SkipBack className="h-4 w-4 fill-current" />
          </button>

          <button
            type="button"
            onClick={togglePlay}
            disabled={!currentTrack}
            className="flex h-9 w-9 items-center justify-center rounded-full bg-white text-black hover:scale-105 active:scale-95 transition-transform disabled:opacity-40 cursor-pointer shadow-md"
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
            title="Next Track"
          >
            <SkipForward className="h-4 w-4 fill-current" />
          </button>

          <button
            type="button"
            onClick={cycleRepeat}
            className={cn(
              "hidden sm:inline-flex rounded-lg p-1.5 transition-colors cursor-pointer",
              repeatMode !== "off"
                ? "text-emerald-bright bg-emerald-500/12"
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

        {/* Scrubber */}
        <div className="flex w-full items-center gap-2">
          <span className="w-9 text-right text-[11px] font-mono tabular-nums text-zinc-400">
            {formatDuration(currentTimeSec, false)}
          </span>
          <div className="relative flex-1 flex items-center h-4 group">
            <div className="h-1 w-full rounded-full bg-white/10 overflow-hidden">
              <div
                className="h-full rounded-full bg-emerald-bright transition-[width] duration-75"
                style={{ width: `${progressPct}%` }}
              />
            </div>
            <input
              type="range"
              min={0}
              max={effectiveDuration || 100}
              step={0.5}
              value={currentTimeSec}
              disabled={!currentTrack || effectiveDuration <= 0}
              onChange={(e) => seek(Number(e.target.value))}
              aria-label="Playback position"
              className="absolute inset-0 w-full opacity-0 cursor-pointer disabled:cursor-default"
            />
          </div>
          <span className="w-9 text-[11px] font-mono tabular-nums text-zinc-400">
            {formatDuration(effectiveDuration, false)}
          </span>
        </div>
      </div>

      {/* Right: Lyrics, EQ & Volume */}
      <div className="flex items-center justify-end gap-1.5 sm:gap-2.5 min-w-0 w-[26%] max-w-[260px]">
        <button
          type="button"
          onClick={toggleLyricsDrawer}
          className={cn(
            "rounded-lg p-2 transition-colors cursor-pointer border",
            lyricsDrawerOpen
              ? "bg-emerald-500/15 text-emerald-300 border-emerald-500/30"
              : "text-zinc-400 border-transparent hover:bg-white/8 hover:text-white"
          )}
          title="Synced Lyrics Drawer"
        >
          <ListMusic className="h-4 w-4" />
        </button>

        <button
          type="button"
          onClick={toggleEqPopover}
          className={cn(
            "relative rounded-lg p-2 transition-colors cursor-pointer border",
            eqPopoverOpen || eqEnabled
              ? "bg-emerald-500/15 text-emerald-300 border-emerald-500/30"
              : "text-zinc-400 border-transparent hover:bg-white/8 hover:text-white"
          )}
          title="10-Band Equalizer"
        >
          <SlidersHorizontal className="h-4 w-4" />
          {eqEnabled && (
            <span className="absolute top-1.5 right-1.5 h-1.5 w-1.5 rounded-full bg-emerald-bright" />
          )}
        </button>

        <button
          type="button"
          onClick={toggleMiniPlayer}
          className={cn(
            "rounded-lg p-2 transition-colors cursor-pointer border",
            miniPlayerOpen
              ? "bg-emerald-500/15 text-emerald-300 border-emerald-500/30"
              : "text-zinc-400 border-transparent hover:bg-white/8 hover:text-white"
          )}
          title="Studio Mini Player (Alt+M)"
        >
          <PictureInPicture2 className="h-4 w-4" />
        </button>

        <div className="hidden md:flex items-center gap-2 pl-1">
          <button
            type="button"
            onClick={toggleMute}
            className="rounded-lg p-1.5 text-zinc-400 hover:text-white cursor-pointer"
            title={muted ? "Unmute" : "Mute"}
          >
            {muted || volume === 0 ? (
              <VolumeX className="h-4 w-4 text-zinc-500" />
            ) : (
              <Volume2 className="h-4 w-4" />
            )}
          </button>
          <input
            type="range"
            min={0}
            max={1}
            step={0.02}
            value={muted ? 0 : volume}
            onChange={(e) => setVolume(Number(e.target.value))}
            aria-label="Volume"
            className="w-20 accent-emerald-500 cursor-pointer h-1.5"
          />
        </div>
      </div>
      </div>
    </div>
  );
}
