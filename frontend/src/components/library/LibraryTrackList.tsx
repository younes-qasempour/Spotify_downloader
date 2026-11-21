import { useEffect, useState } from "react";
import {
  Activity,
  Copy,
  Disc3,
  FileMusic,
  FolderOpen,
  FolderOutput,
  Gauge,
  Info,
  MoreHorizontal,
  Play,
  RotateCcw,
  Trash2,
  Volume2,
} from "lucide-react";
import { apiUrl } from "@/api/client";
import type { LibraryTrack } from "@/api/types";
import type { EngineChoice } from "@/components/playlists/PlaylistTrackList";
import { QualityBadge } from "@/components/ui/badge";
import { useVirtualList } from "@/hooks/useVirtualList";
import { cn, formatBytes, formatDuration } from "@/lib/utils";

interface LibraryTrackListProps {
  tracks: LibraryTrack[];
  selectedIds: Set<string>;
  playingTrackId?: string | null;
  onRowClick: (trackId: string, idx: number, e: React.MouseEvent) => void;
  onCheckboxClick: (trackId: string, idx: number, e: React.MouseEvent) => void;
  onDoubleClick: (track: LibraryTrack) => void;
  onPlay: (track: LibraryTrack) => void;
  onRevealInExplorer: (track: LibraryTrack) => void;
  onCopyTitle: (track: LibraryTrack) => void;
  onRedownload: (track: LibraryTrack, engine: EngineChoice) => void;
  onDeleteFile: (track: LibraryTrack) => void;
  onRemoveFromArchive: (track: LibraryTrack) => void;
  onExportSelected: (fallback: LibraryTrack) => void;
  onExportM3u8: () => void;
  onViewDetails: (track: LibraryTrack) => void;
  onInspectSpectrum: (track: LibraryTrack) => void;
  onNormalizeTrack: (track: LibraryTrack) => void;
  onReplayGainTrack: (track: LibraryTrack) => void;
}

interface ContextState {
  track: LibraryTrack;
  x: number;
  y: number;
}

const ITEM_HEIGHT = 64;

export function LibraryTrackList({
  tracks,
  selectedIds,
  playingTrackId,
  onRowClick,
  onCheckboxClick,
  onDoubleClick,
  onPlay,
  onRevealInExplorer,
  onCopyTitle,
  onRedownload,
  onDeleteFile,
  onRemoveFromArchive,
  onExportSelected,
  onExportM3u8,
  onViewDetails,
  onInspectSpectrum,
  onNormalizeTrack,
  onReplayGainTrack,
}: LibraryTrackListProps) {
  const [contextMenu, setContextMenu] = useState<ContextState | null>(null);

  const { containerRef, totalHeight, startIndex, endIndex, offsetY, onScroll } =
    useVirtualList({
      count: tracks.length,
      itemHeight: ITEM_HEIGHT,
      overscan: 8,
    });

  useEffect(() => {
    if (!contextMenu) return;
    const close = () => setContextMenu(null);
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    window.addEventListener("click", close);
    window.addEventListener("scroll", close, true);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("click", close);
      window.removeEventListener("scroll", close, true);
      window.removeEventListener("keydown", onKey);
    };
  }, [contextMenu]);

  const openMenu = (track: LibraryTrack, rawX: number, rawY: number) => {
    const safeX = Math.max(12, Math.min(rawX, window.innerWidth - 260));
    const safeY = Math.max(12, Math.min(rawY, window.innerHeight - 400));
    setContextMenu({ track, x: safeX, y: safeY });
  };

  if (tracks.length === 0) {
    return (
      <div className="glass-panel rounded-2xl p-10 text-center text-sm text-zinc-400">
        No downloaded songs match your search or genre filters.
      </div>
    );
  }

  const visibleTracks = tracks.slice(startIndex, endIndex);
  const menuTrack = contextMenu?.track;

  return (
    <>
      <div className="glass-panel rounded-2xl overflow-hidden">
        <div
          ref={containerRef}
          onScroll={onScroll}
          className="h-[min(58vh,640px)] min-h-[300px] overflow-y-auto relative"
        >
          <div style={{ height: totalHeight }} className="relative w-full">
            <div
              style={{ transform: `translateY(${offsetY}px)` }}
              className="absolute inset-x-0 top-0"
            >
              {visibleTracks.map((tr, localIdx) => {
                const absIdx = startIndex + localIdx;
                const isSelected = selectedIds.has(tr.spotify_id);
                const isPlayingRow = playingTrackId === tr.spotify_id;

                return (
                  <div
                    key={tr.spotify_id}
                    onClick={(e) => onRowClick(tr.spotify_id, absIdx, e)}
                    onDoubleClick={() => onDoubleClick(tr)}
                    onContextMenu={(e) => {
                      e.preventDefault();
                      openMenu(tr, e.clientX, e.clientY);
                    }}
                    className={cn(
                      "group flex h-[64px] items-center gap-3 px-3.5 border-b border-white/[0.05] transition-colors select-none cursor-default",
                      isSelected
                        ? "bg-emerald-500/[0.11]"
                        : isPlayingRow
                          ? "bg-emerald-500/[0.06]"
                          : "hover:bg-white/[0.03]"
                    )}
                  >
                    <input
                      type="checkbox"
                      checked={isSelected}
                      onChange={() => {}}
                      onClick={(e) => {
                        e.stopPropagation();
                        onCheckboxClick(tr.spotify_id, absIdx, e);
                      }}
                      aria-label={`Select ${tr.title}`}
                      className="h-4 w-4 shrink-0 rounded accent-emerald-500 cursor-pointer"
                    />

                    {/* Artwork */}
                    <div className="relative h-10 w-10 shrink-0 overflow-hidden rounded-lg bg-elevated border border-white/[0.08] flex items-center justify-center text-zinc-500">
                      <Disc3 className="h-4 w-4" />
                      <img
                        src={apiUrl(tr.cover_url_local)}
                        alt={tr.title}
                        loading="lazy"
                        className="absolute inset-0 h-full w-full object-cover"
                        onError={(e) => {
                          e.currentTarget.style.display = "none";
                        }}
                      />
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          onPlay(tr);
                        }}
                        className="absolute inset-0 flex items-center justify-center bg-black/60 opacity-0 group-hover:opacity-100 transition-opacity text-white cursor-pointer"
                        title="Play Track"
                      >
                        <Play className="h-4 w-4 fill-current" />
                      </button>
                    </div>

                    {/* Metadata */}
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2 min-w-0">
                        <span
                          className={cn(
                            "truncate text-sm font-medium",
                            isPlayingRow ? "text-emerald-bright" : "text-white"
                          )}
                        >
                          {tr.title}
                        </span>
                        {tr.genres.length > 0 && (
                          <span className="hidden lg:inline-block rounded-md bg-white/[0.05] px-1.5 py-0.5 text-[10px] text-zinc-400 truncate max-w-[110px]">
                            {tr.genres[0]}
                          </span>
                        )}
                      </div>
                      <div className="truncate text-xs text-zinc-400">
                        {tr.artist}
                        {tr.album ? ` · ${tr.album}` : ""}
                      </div>
                    </div>

                    {/* Quality + Size + Duration */}
                    <div className="hidden sm:flex items-center gap-3 shrink-0">
                      <QualityBadge
                        badge={tr.quality_badge}
                        sourceType={tr.source_type}
                      />
                      <span className="hidden md:inline-block w-16 text-right text-[11px] font-mono tabular-nums text-zinc-500">
                        {formatBytes(tr.file_size)}
                      </span>
                      <span className="w-12 text-right text-xs font-mono tabular-nums text-zinc-300">
                        {formatDuration(tr.duration_ms)}
                      </span>
                    </div>

                    {/* Inline Actions */}
                    <div
                      className="flex items-center gap-1 shrink-0"
                      onClick={(e) => e.stopPropagation()}
                    >
                      <button
                        type="button"
                        onClick={() => onPlay(tr)}
                        className="rounded-lg p-1.5 text-zinc-400 hover:bg-white/10 hover:text-emerald-bright cursor-pointer"
                        title="Play in Audio Dock"
                      >
                        <Play className="h-3.5 w-3.5" />
                      </button>

                      <button
                        type="button"
                        onClick={() => onRevealInExplorer(tr)}
                        className="hidden md:inline-flex rounded-lg p-1.5 text-zinc-400 hover:bg-white/10 hover:text-white cursor-pointer"
                        title="Show in Explorer"
                      >
                        <FolderOpen className="h-3.5 w-3.5" />
                      </button>

                      <button
                        type="button"
                        onClick={(e) => {
                          const rect = e.currentTarget.getBoundingClientRect();
                          openMenu(tr, rect.right, rect.bottom + 4);
                        }}
                        className="rounded-lg p-1.5 text-zinc-400 hover:bg-white/10 hover:text-white cursor-pointer"
                        title="More actions"
                      >
                        <MoreHorizontal className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </div>

      {/* Right-Click Context Menu */}
      {contextMenu && menuTrack && (
        <div
          style={{ left: contextMenu.x, top: contextMenu.y }}
          onClick={(e) => e.stopPropagation()}
          className="fixed z-50 w-64 rounded-xl glass-panel py-1.5 shadow-2xl border border-white/12 text-xs max-h-[84vh] overflow-y-auto"
        >
          <button
            type="button"
            onClick={() => {
              setContextMenu(null);
              onPlay(menuTrack);
            }}
            className="flex w-full items-center gap-2.5 px-3 py-2 text-zinc-200 hover:bg-white/10 hover:text-emerald-bright cursor-pointer"
          >
            <Play className="h-3.5 w-3.5" />
            Play Track
          </button>
          <button
            type="button"
            onClick={() => {
              setContextMenu(null);
              onRevealInExplorer(menuTrack);
            }}
            className="flex w-full items-center gap-2.5 px-3 py-2 text-zinc-200 hover:bg-white/10 cursor-pointer"
          >
            <FolderOpen className="h-3.5 w-3.5" />
            Show in Explorer
          </button>
          <button
            type="button"
            onClick={() => {
              setContextMenu(null);
              onCopyTitle(menuTrack);
            }}
            className="flex w-full items-center gap-2.5 px-3 py-2 text-zinc-200 hover:bg-white/10 cursor-pointer"
          >
            <Copy className="h-3.5 w-3.5" />
            Copy Track Title
          </button>

          <div className="my-1 border-t border-white/[0.06]" />
          <div className="px-3 py-1 text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
            Re-download Track
          </div>
          {(
            [
              ["auto", "Auto (Best Available)"],
              ["melobot", "Via Telegram Bot (MeloBot)"],
              ["musilon", "Via Musilon VIP"],
              ["youtube", "Via YouTube Music"],
            ] as Array<[EngineChoice, string]>
          ).map(([eng, label]) => (
            <button
              key={eng}
              type="button"
              onClick={() => {
                setContextMenu(null);
                onRedownload(menuTrack, eng);
              }}
              className="flex w-full items-center gap-2.5 px-3 py-1.5 text-zinc-300 hover:bg-white/10 cursor-pointer"
            >
              <RotateCcw className="h-3.5 w-3.5" />
              {label}
            </button>
          ))}

          <div className="my-1 border-t border-white/[0.06]" />
          <button
            type="button"
            onClick={() => {
              setContextMenu(null);
              onInspectSpectrum(menuTrack);
            }}
            className="flex w-full items-center gap-2.5 px-3 py-2 text-zinc-200 hover:bg-white/10 cursor-pointer"
          >
            <Activity className="h-3.5 w-3.5 text-emerald-400" />
            Inspect Audio Spectrum & True Bitrate...
          </button>
          <button
            type="button"
            onClick={() => {
              setContextMenu(null);
              onNormalizeTrack(menuTrack);
            }}
            className="flex w-full items-center gap-2.5 px-3 py-2 text-zinc-200 hover:bg-white/10 cursor-pointer"
          >
            <Volume2 className="h-3.5 w-3.5" />
            Boost & Balance Track Volume
          </button>
          <button
            type="button"
            onClick={() => {
              setContextMenu(null);
              onReplayGainTrack(menuTrack);
            }}
            className="flex w-full items-center gap-2.5 px-3 py-2 text-zinc-200 hover:bg-white/10 cursor-pointer"
          >
            <Gauge className="h-3.5 w-3.5" />
            Calculate ReplayGain 2.0
          </button>
          <button
            type="button"
            onClick={() => {
              setContextMenu(null);
              onViewDetails(menuTrack);
            }}
            className="flex w-full items-center gap-2.5 px-3 py-2 text-zinc-200 hover:bg-white/10 cursor-pointer"
          >
            <Info className="h-3.5 w-3.5" />
            View Metadata & Genres
          </button>

          <div className="my-1 border-t border-white/[0.06]" />
          <button
            type="button"
            onClick={() => {
              setContextMenu(null);
              onExportSelected(menuTrack);
            }}
            className="flex w-full items-center gap-2.5 px-3 py-2 text-zinc-200 hover:bg-white/10 cursor-pointer"
          >
            <FolderOutput className="h-3.5 w-3.5" />
            Export Selected Tracks...
          </button>
          <button
            type="button"
            onClick={() => {
              setContextMenu(null);
              onExportM3u8();
            }}
            className="flex w-full items-center gap-2.5 px-3 py-2 text-zinc-200 hover:bg-white/10 cursor-pointer"
          >
            <FileMusic className="h-3.5 w-3.5" />
            Export Playlist (.m3u8)...
          </button>

          <div className="my-1 border-t border-white/[0.06]" />
          <button
            type="button"
            onClick={() => {
              setContextMenu(null);
              onRemoveFromArchive(menuTrack);
            }}
            className="flex w-full items-center gap-2.5 px-3 py-2 text-zinc-300 hover:bg-white/10 cursor-pointer"
          >
            <Trash2 className="h-3.5 w-3.5" />
            Remove from Archive Only
          </button>
          <button
            type="button"
            onClick={() => {
              setContextMenu(null);
              onDeleteFile(menuTrack);
            }}
            className="flex w-full items-center gap-2.5 px-3 py-2 text-red-300 hover:bg-red-500/15 cursor-pointer"
          >
            <Trash2 className="h-3.5 w-3.5" />
            Delete File from Disk
          </button>
        </div>
      )}
    </>
  );
}
