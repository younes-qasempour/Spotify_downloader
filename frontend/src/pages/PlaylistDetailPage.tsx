import { useCallback, useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckSquare, Search, X } from "lucide-react";
import { useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { api } from "@/api/endpoints";
import type { PlayerTrack, PlaylistTrackRow } from "@/api/types";
import { BatchDownloadBar } from "@/components/playlists/BatchDownloadBar";
import { EditPlaylistModal } from "@/components/playlists/EditPlaylistModal";
import { EditTrackModal } from "@/components/playlists/EditTrackModal";
import {
  ExportM3u8Modal,
  type ExportM3u8Target,
} from "@/components/playlists/ExportM3u8Modal";
import {
  ExportSongsModal,
  type ExportSongsTarget,
} from "@/components/playlists/ExportSongsModal";
import { PlaylistDetailHero } from "@/components/playlists/PlaylistDetailHero";
import {
  PlaylistTrackList,
  type EngineChoice,
} from "@/components/playlists/PlaylistTrackList";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { useAppStore } from "@/stores/appStore";
import { usePlayerStore } from "@/stores/playerStore";

type PlaylistSort =
  | "default"
  | "genre"
  | "title"
  | "artist"
  | "duration_asc"
  | "duration_desc";

type PlaylistStatusFilter = "all" | "pending" | "queued" | "downloaded";

function toPlayerTrack(tr: PlaylistTrackRow): PlayerTrack {
  const id = tr.spotify_id;
  return {
    id,
    title: tr.title,
    artist: tr.artist,
    album: tr.album,
    durationSec: Math.round((tr.duration_ms || 0) / 1000),
    audioUrl: `/api/media/audio/${encodeURIComponent(id)}`,
    coverUrl: `/api/media/cover/track/${encodeURIComponent(id)}`,
    qualityBadge: tr.quality_badge,
    sourceType: tr.source_type,
  };
}

export function PlaylistDetailPage() {
  const { playlistId = "" } = useParams<{ playlistId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const liveProgress = useAppStore((s) => s.liveProgress);
  const queuePaused = useAppStore((s) => s.queuePaused);
  const playlistSyncProgress = useAppStore((s) => s.playlistSyncProgress);
  const playTrackList = usePlayerStore((s) => s.playTrackList);

  const [searchQuery, setSearchQuery] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [sortBy, setSortBy] = useState<PlaylistSort>("default");
  const [genreFilter, setGenreFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState<PlaylistStatusFilter>("all");
  const [batchSize, setBatchSize] = useState(50);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());

  const [syncing, setSyncing] = useState(false);
  const [busyBatch, setBusyBatch] = useState(false);
  const [editingPlaylist, setEditingPlaylist] = useState(false);
  const [editingTrack, setEditingTrack] = useState<PlaylistTrackRow | null>(null);
  const [exportM3u8Target, setExportM3u8Target] =
    useState<ExportM3u8Target | null>(null);
  const [exportSongsTarget, setExportSongsTarget] =
    useState<ExportSongsTarget | null>(null);

  const searchInputRef = useRef<HTMLInputElement | null>(null);
  const lastAnchorRef = useRef<number | null>(null);

  useEffect(() => {
    const t = window.setTimeout(() => setDebouncedSearch(searchQuery.trim()), 150);
    return () => window.clearTimeout(t);
  }, [searchQuery]);

  const { data, isLoading, isError } = useQuery({
    queryKey: [
      "playlists",
      "detail",
      playlistId,
      debouncedSearch,
      sortBy,
      genreFilter,
      statusFilter,
    ],
    queryFn: () =>
      api.playlists.detail(playlistId, {
        search: debouncedSearch,
        sort: sortBy,
        genre: genreFilter,
        status: statusFilter,
        reconcile: true,
      }),
    enabled: Boolean(playlistId),
  });

  const playlist = data?.playlist;
  const tracks = data?.tracks ?? [];
  const availableGenres = data?.available_genres ?? [];

  useEffect(() => {
    setSelectedIds((prev) => {
      if (prev.size === 0) return prev;
      const valid = new Set(tracks.map((t) => t.spotify_id));
      const next = new Set<string>();
      let changed = false;
      prev.forEach((id) => {
        if (valid.has(id)) next.add(id);
        else changed = true;
      });
      return changed ? next : prev;
    });
  }, [tracks]);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "f") {
        e.preventDefault();
        searchInputRef.current?.focus();
        searchInputRef.current?.select();
      } else if (e.key === "Escape" && selectedIds.size > 0) {
        setSelectedIds(new Set());
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [selectedIds.size]);

  const invalidateAll = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ["playlists"] });
    void queryClient.invalidateQueries({ queryKey: ["queue"] });
    void queryClient.invalidateQueries({ queryKey: ["library"] });
  }, [queryClient]);

  const handleRowClick = useCallback(
    (trackId: string, idx: number, e: React.MouseEvent) => {
      if (e.shiftKey && lastAnchorRef.current !== null) {
        const start = Math.min(lastAnchorRef.current, idx);
        const end = Math.max(lastAnchorRef.current, idx);
        setSelectedIds((prev) => {
          const next = new Set(e.ctrlKey || e.metaKey ? prev : []);
          for (let i = start; i <= end; i += 1) {
            if (tracks[i]) next.add(tracks[i].spotify_id);
          }
          return next;
        });
        return;
      }
      if (e.ctrlKey || e.metaKey) {
        lastAnchorRef.current = idx;
        setSelectedIds((prev) => {
          const next = new Set(prev);
          if (next.has(trackId)) next.delete(trackId);
          else next.add(trackId);
          return next;
        });
        return;
      }
      lastAnchorRef.current = idx;
      setSelectedIds(new Set([trackId]));
    },
    [tracks]
  );

  const handleCheckboxClick = useCallback(
    (trackId: string, idx: number, e: React.MouseEvent) => {
      if (e.shiftKey && lastAnchorRef.current !== null) {
        const start = Math.min(lastAnchorRef.current, idx);
        const end = Math.max(lastAnchorRef.current, idx);
        setSelectedIds((prev) => {
          const next = new Set(prev);
          for (let i = start; i <= end; i += 1) {
            if (tracks[i]) next.add(tracks[i].spotify_id);
          }
          return next;
        });
        return;
      }
      lastAnchorRef.current = idx;
      setSelectedIds((prev) => {
        const next = new Set(prev);
        if (next.has(trackId)) next.delete(trackId);
        else next.add(trackId);
        return next;
      });
    },
    [tracks]
  );

  const allSelected =
    tracks.length > 0 && tracks.every((t) => selectedIds.has(t.spotify_id));

  const handlePlay = useCallback(
    (tr: PlaylistTrackRow) => {
      const downloaded = tracks.filter(
        (t) => t.status === "downloaded" || t.file_exists
      );
      const list = downloaded.length > 0 ? downloaded : [tr];
      const idx = Math.max(
        0,
        list.findIndex((t) => t.spotify_id === tr.spotify_id)
      );
      playTrackList(list.map(toPlayerTrack), idx);
    },
    [playTrackList, tracks]
  );

  const handleDownloadTrack = useCallback(
    async (tr: PlaylistTrackRow, engine?: EngineChoice) => {
      try {
        await api.playlists.downloadSelected(playlistId, {
          track_ids: [tr.spotify_id],
          preferred_engine: engine,
        });
        invalidateAll();
        toast.info(`Queued "${tr.title}"${engine ? ` via ${engine}` : ""}`);
      } catch (err) {
        toast.error("Could not queue track", {
          description: err instanceof Error ? err.message : undefined,
        });
      }
    },
    [invalidateAll, playlistId]
  );

  const handleRedownloadTrack = useCallback(
    async (tr: PlaylistTrackRow, engine: EngineChoice) => {
      try {
        await api.playlists.downloadSelected(playlistId, {
          track_ids: [tr.spotify_id],
          preferred_engine: engine,
          redownload: true,
        });
        invalidateAll();
        toast.info(`Re-downloading "${tr.title}" via ${engine}`);
      } catch (err) {
        toast.error("Re-download failed", {
          description: err instanceof Error ? err.message : undefined,
        });
      }
    },
    [invalidateAll, playlistId]
  );

  const handleOpenFolder = async () => {
    const firstFile = tracks.find((t) => t.file_exists && t.file_path)?.file_path;
    try {
      if (firstFile) {
        await api.settings.openFolder(firstFile, true);
      } else {
        await api.settings.openFolder();
      }
    } catch (err) {
      toast.error("Could not open folder", {
        description: err instanceof Error ? err.message : undefined,
      });
    }
  };

  if (isLoading && !playlist) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-44 rounded-2xl" />
        <Skeleton className="h-14 rounded-2xl" />
        <Skeleton className="h-96 rounded-2xl" />
      </div>
    );
  }

  if (isError || !playlist) {
    return (
      <div className="glass-panel rounded-2xl p-10 text-center space-y-3">
        <h2 className="text-base font-semibold text-white">
          Playlist not found
        </h2>
        <p className="text-sm text-zinc-400">
          This playlist may have been deleted or is unavailable.
        </p>
        <Button
          type="button"
          variant="secondary"
          onClick={() => navigate("/playlists")}
        >
          Back to Playlists
        </Button>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <PlaylistDetailHero
        playlist={playlist}
        syncing={syncing}
        syncProgress={playlistSyncProgress[playlist.id]}
        onBack={() => navigate("/playlists")}
        onToggleWatch={async () => {
          const next = !playlist.auto_sync;
          await api.playlists.toggleAutoSync(playlist.id, next);
          invalidateAll();
          toast.success(
            next ? "Pinned playlist for Auto-Sync" : "Unpinned from Auto-Sync"
          );
        }}
        onSync={async () => {
          setSyncing(true);
          try {
            const res = await api.playlists.sync(playlist.id, true);
            invalidateAll();
            toast.success(`Synced "${playlist.name}"`, {
              description: `${res.added} added, ${res.removed} removed (${res.queued_count} auto-queued).`,
            });
          } catch (err) {
            toast.error("Sync failed", {
              description: err instanceof Error ? err.message : undefined,
            });
          } finally {
            setSyncing(false);
          }
        }}
        onEdit={() => setEditingPlaylist(true)}
        onOpenFolder={() => void handleOpenFolder()}
        onExportM3u8={() =>
          setExportM3u8Target({
            playlistId: playlist.id,
            playlistName: playlist.name,
          })
        }
        onExportSongs={() =>
          setExportSongsTarget({
            playlistId: playlist.id,
            playlistName: playlist.name,
            trackCountHint: playlist.downloaded_count,
          })
        }
      />

      <BatchDownloadBar
        pendingCount={playlist.pending_count}
        selectedCount={selectedIds.size}
        batchSize={batchSize}
        onBatchSizeChange={setBatchSize}
        paused={queuePaused}
        busy={busyBatch}
        onDownloadBatch={async (size) => {
          setBusyBatch(true);
          try {
            const res = await api.playlists.downloadBatch(playlist.id, size);
            invalidateAll();
            toast.success(`Queued batch of ${res.queued_count} track(s)`);
          } catch (err) {
            toast.error("Batch download failed", {
              description: err instanceof Error ? err.message : undefined,
            });
          } finally {
            setBusyBatch(false);
          }
        }}
        onDownloadSelected={async () => {
          const ids = Array.from(selectedIds);
          if (!ids.length) return;
          setBusyBatch(true);
          try {
            const res = await api.playlists.downloadSelected(playlist.id, {
              track_ids: ids,
            });
            invalidateAll();
            toast.success(
              res.queued_count > 0
                ? `Queued ${res.queued_count} selected track(s)`
                : "Selected tracks are already downloaded"
            );
          } catch (err) {
            toast.error("Selected download failed", {
              description: err instanceof Error ? err.message : undefined,
            });
          } finally {
            setBusyBatch(false);
          }
        }}
        onTogglePause={() =>
          void (queuePaused ? api.queue.resume() : api.queue.pause()).then(() =>
            invalidateAll()
          )
        }
        onStopQueue={() =>
          void api.queue.stop().then(() => {
            invalidateAll();
            toast.warning("Downloads stopped");
          })
        }
        onResetQueued={async () => {
          const res = await api.playlists.resetQueued(playlist.id);
          invalidateAll();
          toast.info(`Reset ${res.reverted_count} queued track(s) to pending`);
        }}
      />

      {/* Search, Sort, Genre & Status Filters */}
      <div className="glass-panel rounded-2xl p-3 flex flex-col lg:flex-row gap-2.5 items-stretch lg:items-center">
        <div className="flex-1 min-w-0">
          <Input
            ref={searchInputRef}
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            leadingIcon={<Search className="h-3.5 w-3.5" />}
            placeholder="Filter tracks in this playlist (Ctrl+F)..."
            className="h-8 text-xs"
            trailingSlot={
              searchQuery ? (
                <button
                  type="button"
                  onClick={() => setSearchQuery("")}
                  className="rounded p-1 text-zinc-400 hover:text-white cursor-pointer"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              ) : undefined
            }
          />
        </div>

        <div className="flex flex-wrap items-center gap-2 shrink-0">
          {tracks.length > 0 && (
            <button
              type="button"
              onClick={() =>
                setSelectedIds(
                  allSelected
                    ? new Set()
                    : new Set(tracks.map((t) => t.spotify_id))
                )
              }
              className={cn(
                "inline-flex items-center gap-1.5 h-8 rounded-lg px-2.5 text-xs font-medium border transition-colors cursor-pointer",
                allSelected
                  ? "bg-emerald-500/15 text-emerald-300 border-emerald-500/35"
                  : "bg-white/[0.04] text-zinc-300 border-white/10 hover:bg-white/[0.08]"
              )}
            >
              <CheckSquare className="h-3.5 w-3.5" />
              <span>{allSelected ? "Deselect All" : "Select All"}</span>
            </button>
          )}

          <select
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value as PlaylistSort)}
            aria-label="Sort playlist tracks"
            className="h-8 rounded-lg border border-white/10 bg-elevated px-2.5 text-xs text-zinc-200 focus:border-emerald-500/60 focus:outline-none cursor-pointer"
          >
            <option value="default">Sort: Default Order</option>
            <option value="genre">Sort: Genre (A–Z)</option>
            <option value="title">Sort: Title (A–Z)</option>
            <option value="artist">Sort: Artist (A–Z)</option>
            <option value="duration_asc">Sort: Shortest</option>
            <option value="duration_desc">Sort: Longest</option>
          </select>

          <select
            value={genreFilter}
            onChange={(e) => setGenreFilter(e.target.value)}
            aria-label="Filter by genre"
            className="h-8 rounded-lg border border-white/10 bg-elevated px-2.5 text-xs text-zinc-200 focus:border-emerald-500/60 focus:outline-none cursor-pointer max-w-[160px]"
          >
            <option value="all">All Genres</option>
            {availableGenres.map((g) => (
              <option key={g} value={g}>
                {g}
              </option>
            ))}
          </select>

          <select
            value={statusFilter}
            onChange={(e) =>
              setStatusFilter(e.target.value as PlaylistStatusFilter)
            }
            aria-label="Filter by status"
            className="h-8 rounded-lg border border-white/10 bg-elevated px-2.5 text-xs text-zinc-200 focus:border-emerald-500/60 focus:outline-none cursor-pointer"
          >
            <option value="all">All Statuses</option>
            <option value="pending">Pending Only</option>
            <option value="queued">Queued Only</option>
            <option value="downloaded">Completed Only</option>
          </select>
        </div>
      </div>

      {/* Virtualized Track Table */}
      <PlaylistTrackList
        tracks={tracks}
        selectedIds={selectedIds}
        liveProgress={liveProgress}
        onRowClick={handleRowClick}
        onCheckboxClick={handleCheckboxClick}
        onDoubleClick={(tr) => {
          if (tr.status === "downloaded" || tr.file_exists) {
            handlePlay(tr);
          } else {
            void handleDownloadTrack(tr);
          }
        }}
        onPlay={handlePlay}
        onDownloadTrack={(tr, eng) => void handleDownloadTrack(tr, eng)}
        onRedownloadTrack={(tr, eng) => void handleRedownloadTrack(tr, eng)}
        onDeleteTrackFile={async (tr) => {
          await api.playlists.deleteTrackFile(playlist.id, tr.spotify_id);
          invalidateAll();
          toast.info(`Deleted "${tr.title}" from disk and marked Pending`);
        }}
        onCancelTrack={async (tr) => {
          await api.playlists.cancelTrack(playlist.id, tr.spotify_id);
          invalidateAll();
          toast.info(`Cancelled "${tr.title}"`);
        }}
        onResetTrack={async (tr) => {
          await api.playlists.resetTrack(playlist.id, tr.spotify_id);
          invalidateAll();
          toast.info(`Reset "${tr.title}" to Pending`);
        }}
        onRevealInExplorer={async (tr) => {
          if (!tr.file_path) return;
          try {
            await api.settings.openFolder(tr.file_path, true);
          } catch (err) {
            toast.error("File not found on disk", {
              description: err instanceof Error ? err.message : undefined,
            });
          }
        }}
        onEditTrack={(tr) => setEditingTrack(tr)}
        onExportSelected={(fallback) => {
          const ids =
            selectedIds.size > 0
              ? Array.from(selectedIds)
              : [fallback.spotify_id];
          setExportSongsTarget({
            playlistName: playlist.name,
            trackIds: ids,
            trackCountHint: ids.length,
          });
        }}
        onExportM3u8={() =>
          setExportM3u8Target({
            playlistId: playlist.id,
            playlistName: playlist.name,
          })
        }
        onCopyTitle={(tr) =>
          void navigator.clipboard
            .writeText(`${tr.title} - ${tr.artist}`)
            .then(() => toast.success("Copied title & artist"))
        }
        onCopyUrl={(tr) =>
          void navigator.clipboard
            .writeText(`https://open.spotify.com/track/${tr.spotify_id}`)
            .then(() => toast.success("Copied Spotify URL"))
        }
      />

      {/* Modals */}
      <EditPlaylistModal
        playlist={editingPlaylist ? playlist : null}
        onClose={() => setEditingPlaylist(false)}
      />

      <EditTrackModal
        playlistId={playlist.id}
        track={editingTrack}
        onClose={() => setEditingTrack(null)}
      />

      <ExportM3u8Modal
        target={exportM3u8Target}
        onClose={() => setExportM3u8Target(null)}
      />

      <ExportSongsModal
        target={exportSongsTarget}
        onClose={() => setExportSongsTarget(null)}
      />
    </div>
  );
}
