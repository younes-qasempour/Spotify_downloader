import { useEffect, useState } from "react";
import {
  CheckCircle2,
  Copy,
  Disc3,
  Download,
  FileMusic,
  FolderOpen,
  FolderOutput,
  Link,
  MoreHorizontal,
  Pencil,
  Play,
  RotateCcw,
  Trash2,
  XCircle,
} from "lucide-react";
import { apiUrl } from "@/api/client";
import type { PlaylistTrackRow } from "@/api/types";
import { Badge, QualityBadge } from "@/components/ui/badge";
import { useVirtualList } from "@/hooks/useVirtualList";
import { cn, formatDuration } from "@/lib/utils";
import type { LiveTrackProgress } from "@/stores/appStore";

export type EngineChoice = "auto" | "melobot" | "musilon" | "youtube";

interface PlaylistTrackListProps {
  tracks: PlaylistTrackRow[];
  selectedIds: Set<string>;
  liveProgress: Record<string, LiveTrackProgress>;
  onRowClick: (trackId: string, index: number, e: React.MouseEvent) => void;
  onCheckboxClick: (trackId: string, index: number, e: React.MouseEvent) => void;
  onDoubleClick: (track: PlaylistTrackRow) => void;
  onPlay: (track: PlaylistTrackRow) => void;
  onDownloadTrack: (track: PlaylistTrackRow, engine?: EngineChoice) => void;
  onRedownloadTrack: (track: PlaylistTrackRow, engine: EngineChoice) => void;
  onDeleteTrackFile: (track: PlaylistTrackRow) => void;
  onCancelTrack: (track: PlaylistTrackRow) => void;
  onResetTrack: (track: PlaylistTrackRow) => void;
  onRevealInExplorer: (track: PlaylistTrackRow) => void;
  onEditTrack: (track: PlaylistTrackRow) => void;
  onExportSelected: (fallbackTrack: PlaylistTrackRow) => void;
  onExportM3u8: () => void;
  onCopyTitle: (track: PlaylistTrackRow) => void;
  onCopyUrl: (track: PlaylistTrackRow) => void;
}

interface ContextState {
  track: PlaylistTrackRow;
  x: number;
  y: number;
}

const ITEM_HEIGHT = 64;

export function PlaylistTrackList({
  tracks,
  selectedIds,
  liveProgress,
  onRowClick,
  onCheckboxClick,
  onDoubleClick,
  onPlay,
  onDownloadTrack,
  onRedownloadTrack,
  onDeleteTrackFile,
  onCancelTrack,
  onResetTrack,
  onRevealInExplorer,
  onEditTrack,
  onExportSelected,
  onExportM3u8,
  onCopyTitle,
  onCopyUrl,
}: PlaylistTrackListProps) {
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

  const openMenu = (track: PlaylistTrackRow, rawX: number, rawY: number) => {
    const safeX = Math.max(12, Math.min(rawX, window.innerWidth - 250));
    const safeY = Math.max(12, Math.min(rawY, window.innerHeight - 360));
    setContextMenu({ track, x: safeX, y: safeY });
  };

  if (tracks.length === 0) {
    return (
      <div className="glass-panel rounded-2xl p-10 text-center text-sm text-zinc-400">
        No tracks match the current search, genre, or status filters.
      </div>
    );
  }

  const visibleTracks = tracks.slice(startIndex, endIndex);
  const menuTrack = contextMenu?.track;
  const menuDownloaded =
    menuTrack?.status === "downloaded" || Boolean(menuTrack?.file_exists);
  const menuQueued = menuTrack?.status === "queued";

  return (
    <>
      <div className="glass-panel rounded-2xl overflow-hidden">
        <div
          ref={containerRef}
          onScroll={onScroll}
          className="h-[min(56vh,620px)] min-h-[300px] overflow-y-auto relative"
        >
          <div style={{ height: totalHeight }} className="relative w-full">
            <div
              style={{ transform: `translateY(${offsetY}px)` }}
              className="absolute inset-x-0 top-0"
            >
              {visibleTracks.map((tr, localIdx) => {
                const absIdx = startIndex + localIdx;
                const isSelected = selectedIds.has(tr.spotify_id);
                const isDownloaded = tr.status === "downloaded" || tr.file_exists;
                const isQueued = tr.status === "queued";
                const live = liveProgress[tr.spotify_id];

                const coverSrc = isDownloaded
                  ? apiUrl(
                      `/api/media/cover/track/${encodeURIComponent(tr.spotify_id)}`
                    )
                  : tr.cover_url || "";

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

                    <span className="hidden sm:inline-block w-7 text-right text-[11px] font-mono tabular-nums text-zinc-500">
                      {tr.position || absIdx + 1}
                    </span>

                    {/* Artwork */}
                    <div className="relative h-10 w-10 shrink-0 overflow-hidden rounded-lg bg-elevated border border-white/[0.07] flex items-center justify-center text-zinc-500">
                      <Disc3 className="h-4 w-4" />
                      {coverSrc && (
                        <img
                          src={coverSrc}
                          alt={tr.title}
                          loading="lazy"
                          className="absolute inset-0 h-full w-full object-cover"
                          onError={(e) => {
                            const img = e.currentTarget;
                            if (
                              tr.cover_url &&
                              !img.dataset.fallbackTried &&
                              img.src !== tr.cover_url
                            ) {
                              img.dataset.fallbackTried = "1";
                              img.src = tr.cover_url;
                            } else {
                              img.style.display = "none";
                            }
                          }}
                        />
                      )}
                      {isDownloaded && (
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            onPlay(tr);
                          }}
                          className="absolute inset-0 flex items-center justify-center bg-black/60 opacity-0 group-hover:opacity-100 transition-opacity text-white cursor-pointer"
                          title="Play in Audio Dock"
                        >
                          <Play className="h-4 w-4 fill-current" />
                        </button>
                      )}
                    </div>

                    {/* Title & Artist */}
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2 min-w-0">
                        <span className="truncate text-sm font-medium text-white">
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

                    {/* Quality + Duration */}
                    <div className="hidden md:flex items-center gap-3 shrink-0">
                      {isDownloaded && tr.quality_badge && (
                        <QualityBadge
                          badge={tr.quality_badge}
                          sourceType={tr.source_type}
                        />
                      )}
                      <span className="w-12 text-right text-xs font-mono tabular-nums text-zinc-400">
                        {formatDuration(tr.duration_ms)}
                      </span>
                    </div>

                    {/* Status / Live Progress */}
                    <div className="w-28 sm:w-36 shrink-0 flex flex-col items-end justify-center gap-1">
                      {live && !isDownloaded ? (
                        <>
                          <div className="flex w-full items-center justify-between text-[11px] font-mono tabular-nums">
                            <span className="text-sky-300">Downloading</span>
                            <span className="text-white">
                              {Math.round(live.percent)}%
                            </span>
                          </div>
                          <div className="h-1.5 w-full overflow-hidden rounded-full bg-white/10">
                            <div
                              className="h-full rounded-full bg-emerald-bright transition-all"
                              style={{
                                width: `${Math.min(100, Math.max(3, live.percent))}%`,
                              }}
                            />
                          </div>
                        </>
                      ) : (
                        <Badge
                          variant={
                            isDownloaded
                              ? "emerald"
                              : isQueued
                                ? "sky"
                                : "default"
                          }
                          className="gap-1"
                        >
                          {isDownloaded && <CheckCircle2 className="h-3 w-3" />}
                          <span>{tr.status_pill || tr.status}</span>
                        </Badge>
                      )}
                    </div>

                    {/* Inline Quick Buttons */}
                    <div
                      className="flex items-center gap-1 shrink-0"
                      onClick={(e) => e.stopPropagation()}
                    >
                      {isDownloaded ? (
                        <button
                          type="button"
                          onClick={() => onPlay(tr)}
                          className="rounded-lg p-1.5 text-zinc-400 hover:bg-white/10 hover:text-emerald-bright cursor-pointer"
                          title="Play Track"
                        >
                          <Play className="h-3.5 w-3.5" />
                        </button>
                      ) : (
                        <button
                          type="button"
                          onClick={() => onDownloadTrack(tr)}
                          className="rounded-lg p-1.5 text-zinc-400 hover:bg-white/10 hover:text-emerald-bright cursor-pointer"
                          title="Download Track"
                        >
                          <Download className="h-3.5 w-3.5" />
                        </button>
                      )}

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

      {/* Right-Click & Overflow Context Menu */}
      {contextMenu && menuTrack && (
        <div
          style={{ left: contextMenu.x, top: contextMenu.y }}
          onClick={(e) => e.stopPropagation()}
          className="fixed z-50 w-60 rounded-xl glass-panel py-1.5 shadow-2xl border border-white/12 text-xs max-h-[82vh] overflow-y-auto"
        >
          {menuDownloaded ? (
            <>
              <button
                type="button"
                onClick={() => {
                  setContextMenu(null);
                  onPlay(menuTrack);
                }}
                className="flex w-full items-center gap-2.5 px-3 py-2 text-zinc-200 hover:bg-white/10 hover:text-emerald-bright cursor-pointer"
              >
                <Play className="h-3.5 w-3.5" />
                Play in Audio Dock
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
                Show in File Explorer
              </button>

              <div className="my-1 border-t border-white/[0.06]" />
              <div className="px-3 py-1 text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
                Re-download Track
              </div>
              {(
                [
                  ["auto", "Auto (Best Available)"],
                  ["melobot", "Via MeloBot Telegram"],
                  ["musilon", "Via Musilon VIP"],
                  ["youtube", "Via YouTube Music"],
                ] as Array<[EngineChoice, string]>
              ).map(([eng, label]) => (
                <button
                  key={eng}
                  type="button"
                  onClick={() => {
                    setContextMenu(null);
                    onRedownloadTrack(menuTrack, eng);
                  }}
                  className="flex w-full items-center gap-2.5 px-3 py-1.5 text-zinc-300 hover:bg-white/10 cursor-pointer"
                >
                  <RotateCcw className="h-3.5 w-3.5" />
                  {label}
                </button>
              ))}

              <button
                type="button"
                onClick={() => {
                  setContextMenu(null);
                  onDeleteTrackFile(menuTrack);
                }}
                className="flex w-full items-center gap-2.5 px-3 py-2 text-red-300 hover:bg-red-500/15 cursor-pointer"
              >
                <Trash2 className="h-3.5 w-3.5" />
                Delete Downloaded File
              </button>
            </>
          ) : (
            <>
              <button
                type="button"
                onClick={() => {
                  setContextMenu(null);
                  onDownloadTrack(menuTrack);
                }}
                className="flex w-full items-center gap-2.5 px-3 py-2 text-zinc-200 hover:bg-white/10 hover:text-emerald-bright cursor-pointer"
              >
                <Download className="h-3.5 w-3.5" />
                Download This Track
              </button>
              <div className="px-3 py-1 text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
                Download via Specific Source
              </div>
              {(
                [
                  ["melobot", "Telegram Bot (MeloBot)"],
                  ["musilon", "Musilon VIP"],
                  ["youtube", "YouTube Music"],
                ] as Array<[EngineChoice, string]>
              ).map(([eng, label]) => (
                <button
                  key={eng}
                  type="button"
                  onClick={() => {
                    setContextMenu(null);
                    onDownloadTrack(menuTrack, eng);
                  }}
                  className="flex w-full items-center gap-2.5 px-3 py-1.5 text-zinc-300 hover:bg-white/10 cursor-pointer"
                >
                  <Download className="h-3.5 w-3.5" />
                  {label}
                </button>
              ))}
            </>
          )}

          {menuQueued && (
            <>
              <div className="my-1 border-t border-white/[0.06]" />
              <button
                type="button"
                onClick={() => {
                  setContextMenu(null);
                  onCancelTrack(menuTrack);
                }}
                className="flex w-full items-center gap-2.5 px-3 py-2 text-amber-300 hover:bg-amber-500/12 cursor-pointer"
              >
                <XCircle className="h-3.5 w-3.5" />
                Cancel / Stop Download
              </button>
              <button
                type="button"
                onClick={() => {
                  setContextMenu(null);
                  onResetTrack(menuTrack);
                }}
                className="flex w-full items-center gap-2.5 px-3 py-2 text-zinc-300 hover:bg-white/10 cursor-pointer"
              >
                <RotateCcw className="h-3.5 w-3.5" />
                Reset Status to Pending
              </button>
            </>
          )}

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
              onEditTrack(menuTrack);
            }}
            className="flex w-full items-center gap-2.5 px-3 py-2 text-zinc-200 hover:bg-white/10 cursor-pointer"
          >
            <Pencil className="h-3.5 w-3.5" />
            Edit Track Metadata...
          </button>
          <button
            type="button"
            onClick={() => {
              setContextMenu(null);
              onCopyTitle(menuTrack);
            }}
            className="flex w-full items-center gap-2.5 px-3 py-2 text-zinc-300 hover:bg-white/10 cursor-pointer"
          >
            <Copy className="h-3.5 w-3.5" />
            Copy Title & Artist
          </button>
          <button
            type="button"
            onClick={() => {
              setContextMenu(null);
              onCopyUrl(menuTrack);
            }}
            className="flex w-full items-center gap-2.5 px-3 py-2 text-zinc-300 hover:bg-white/10 cursor-pointer"
          >
            <Link className="h-3.5 w-3.5" />
            Copy Spotify URL
          </button>
        </div>
      )}
    </>
  );
}
