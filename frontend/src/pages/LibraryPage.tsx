import { useCallback, useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import {
  Activity,
  ArrowLeft,
  CheckSquare,
  CopyCheck,
  Disc3,
  FileMusic,
  Folder,
  FolderOpen,
  FolderOutput,
  Library as LibraryIcon,
  Music,
  Pencil,
  Play,
  RefreshCw,
  Search,
  X,
} from "lucide-react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { apiUrl } from "@/api/client";
import { api } from "@/api/endpoints";
import type { LibraryCollection, LibraryTrack, PlayerTrack } from "@/api/types";
import { CollectionCard } from "@/components/library/CollectionCard";
import { LibraryTrackList } from "@/components/library/LibraryTrackList";
import { RenameCollectionModal } from "@/components/library/RenameCollectionModal";
import { TrackDetailsModal } from "@/components/library/TrackDetailsModal";
import { TrackSpectrumModal } from "@/components/library/TrackSpectrumModal";
import {
  ExportM3u8Modal,
  type ExportM3u8Target,
} from "@/components/playlists/ExportM3u8Modal";
import {
  ExportSongsModal,
  type ExportSongsTarget,
} from "@/components/playlists/ExportSongsModal";
import type { EngineChoice } from "@/components/playlists/PlaylistTrackList";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { usePlayerStore } from "@/stores/playerStore";

type LibraryTab = "tracks" | "playlists" | "albums";
type LibrarySort =
  | "title"
  | "track_number"
  | "artist"
  | "duration_asc"
  | "duration_desc"
  | "recent"
  | "genre";

interface ActiveCollectionState {
  name: string;
  type: "playlist" | "album";
  artist?: string;
  folderPath?: string;
  coverUrlLocal: string;
  sizeStr?: string;
  trackCount?: number;
}

function toPlayerTrack(tr: LibraryTrack): PlayerTrack {
  return {
    id: tr.spotify_id,
    title: tr.title,
    artist: tr.artist,
    album: tr.album,
    durationSec: Math.round((tr.duration_ms || 0) / 1000),
    audioUrl: tr.audio_url,
    coverUrl: tr.cover_url_local,
    qualityBadge: tr.quality_badge,
    sourceType: tr.source_type,
  };
}

export function LibraryPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const playTrackList = usePlayerStore((s) => s.playTrackList);
  const playingTrackId = usePlayerStore((s) => s.currentTrack?.id ?? null);

  const [activeTab, setActiveTab] = useState<LibraryTab>("tracks");
  const [activeCollection, setActiveCollection] =
    useState<ActiveCollectionState | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [sortBy, setSortBy] = useState<LibrarySort>("title");
  const [genreFilter, setGenreFilter] = useState("all");
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [rescanning, setRescanning] = useState(false);

  const [renamingName, setRenamingName] = useState<string | null>(null);
  const [detailsTrack, setDetailsTrack] = useState<LibraryTrack | null>(null);
  const [spectrumTrack, setSpectrumTrack] = useState<LibraryTrack | null>(null);
  const [deletingDiskTrack, setDeletingDiskTrack] =
    useState<LibraryTrack | null>(null);
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

  const { data: stats } = useQuery({
    queryKey: ["library", "stats"],
    queryFn: () => api.library.stats(),
  });

  const viewingTrackRows = activeTab === "tracks" || activeCollection !== null;

  const { data: tracksData, isLoading: loadingTracks } = useQuery({
    queryKey: ["library", "tracks", debouncedSearch, genreFilter, sortBy],
    queryFn: () =>
      api.library.tracks({
        search: debouncedSearch,
        genre: genreFilter,
        sort: sortBy,
      }),
    enabled: activeTab === "tracks" && activeCollection === null,
  });

  const collectionApiSort =
    sortBy === "track_number" ? "track_count" : sortBy;

  const { data: playlistsData, isLoading: loadingPlaylists } = useQuery({
    queryKey: [
      "library",
      "playlists",
      debouncedSearch,
      genreFilter,
      collectionApiSort,
    ],
    queryFn: () =>
      api.library.playlists({
        search: debouncedSearch,
        genre: genreFilter,
        sort: collectionApiSort,
      }),
    enabled: activeTab === "playlists" && activeCollection === null,
  });

  const { data: albumsData, isLoading: loadingAlbums } = useQuery({
    queryKey: [
      "library",
      "albums",
      debouncedSearch,
      genreFilter,
      collectionApiSort,
    ],
    queryFn: () =>
      api.library.albums({
        search: debouncedSearch,
        genre: genreFilter,
        sort: collectionApiSort,
      }),
    enabled: activeTab === "albums" && activeCollection === null,
  });

  const { data: collTracksData, isLoading: loadingCollTracks } = useQuery({
    queryKey: [
      "library",
      "collection",
      activeCollection?.type,
      activeCollection?.name,
      debouncedSearch,
      genreFilter,
      sortBy,
    ],
    queryFn: () =>
      api.library.collectionTracks({
        name: activeCollection!.name,
        type: activeCollection!.type,
        search: debouncedSearch,
        genre: genreFilter,
        sort: sortBy,
      }),
    enabled: activeCollection !== null,
  });

  const tracks = activeCollection
    ? (collTracksData?.tracks ?? [])
    : (tracksData?.tracks ?? []);
  const playlists = playlistsData?.playlists ?? [];
  const albums = albumsData?.albums ?? [];
  const availableGenres =
    stats?.available_genres ?? tracksData?.available_genres ?? [];

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

  const invalidateLibrary = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ["library"] });
    void queryClient.invalidateQueries({ queryKey: ["playlists"] });
  }, [queryClient]);

  const handleSwitchTab = (tab: LibraryTab) => {
    setActiveCollection(null);
    setActiveTab(tab);
    setSelectedIds(new Set());
    if (tab === "tracks" && sortBy === "artist") {
      setSortBy("title");
    }
  };

  const handleBrowseCollection = (
    coll: LibraryCollection,
    type: "playlist" | "album"
  ) => {
    setSearchQuery("");
    setDebouncedSearch("");
    setSelectedIds(new Set());
    if (type === "album" && (sortBy === "title" || sortBy === "recent")) {
      setSortBy("track_number");
    }
    setActiveCollection({
      name: coll.name,
      type,
      artist: coll.artist,
      folderPath: coll.folder_path,
      coverUrlLocal: coll.cover_url_local,
      sizeStr: coll.size_str,
      trackCount: coll.track_count,
    });
  };

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
    viewingTrackRows &&
    tracks.length > 0 &&
    tracks.every((t) => selectedIds.has(t.spotify_id));

  const handlePlayTrack = useCallback(
    (tr: LibraryTrack) => {
      const idx = Math.max(
        0,
        tracks.findIndex((t) => t.spotify_id === tr.spotify_id)
      );
      playTrackList(tracks.map(toPlayerTrack), idx);
    },
    [playTrackList, tracks]
  );

  const handleRescan = async () => {
    if (rescanning) return;
    setRescanning(true);
    try {
      const res = await api.library.rescan();
      invalidateLibrary();
      toast.success("Library Synced", {
        description: `Scanned downloads folder and indexed ${res.indexed} file(s).`,
      });
    } catch (err) {
      toast.error("Rescan failed", {
        description: err instanceof Error ? err.message : undefined,
      });
    } finally {
      setRescanning(false);
    }
  };

  const tabs: Array<{
    id: LibraryTab;
    label: string;
    count: number;
    icon: React.ComponentType<{ className?: string }>;
  }> = [
    {
      id: "tracks",
      label: "All Songs",
      count: stats?.total_tracks ?? 0,
      icon: Music,
    },
    {
      id: "playlists",
      label: "Playlists",
      count: stats?.total_playlists ?? 0,
      icon: Folder,
    },
    {
      id: "albums",
      label: "Albums",
      count: stats?.total_albums ?? 0,
      icon: Disc3,
    },
  ];

  return (
    <div className="space-y-4">
      {/* 1. Segmented Tabs + Quick Utility Actions */}
      <div className="flex flex-col xl:flex-row gap-3 items-stretch xl:items-center justify-between">
        <div className="flex flex-wrap items-center gap-3">
          <div className="inline-flex rounded-xl bg-white/[0.04] p-1 border border-white/[0.08]">
            {tabs.map((tab) => {
              const Icon = tab.icon;
              const isActive =
                activeCollection === null
                  ? activeTab === tab.id
                  : (tab.id === "playlists" &&
                      activeCollection.type === "playlist") ||
                    (tab.id === "albums" && activeCollection.type === "album");
              return (
                <button
                  key={tab.id}
                  type="button"
                  onClick={() => handleSwitchTab(tab.id)}
                  className={cn(
                    "relative flex items-center gap-2 rounded-lg px-3.5 py-1.5 text-xs font-medium transition-colors cursor-pointer",
                    isActive
                      ? "text-white"
                      : "text-zinc-400 hover:text-zinc-200"
                  )}
                >
                  {isActive && (
                    <motion.span
                      layoutId="library-tab-pill"
                      transition={{
                        type: "spring",
                        stiffness: 380,
                        damping: 32,
                      }}
                      className="absolute inset-0 rounded-lg bg-white/12 border border-white/12"
                    />
                  )}
                  <Icon className="relative z-10 h-3.5 w-3.5 text-emerald-400" />
                  <span className="relative z-10">{tab.label}</span>
                  <span className="relative z-10 font-mono text-[11px] tabular-nums text-zinc-400">
                    ({tab.count})
                  </span>
                </button>
              );
            })}
          </div>

          {stats && (
            <span className="text-xs text-zinc-400 font-mono tabular-nums">
              {stats.total_tracks} song(s) · {stats.total_playlists} playlist(s) ·{" "}
              {stats.total_albums} album(s) · {stats.size_str}
            </span>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            size="sm"
            variant="secondary"
            onClick={() => navigate("/tools?tab=spectrum")}
          >
            <Activity className="h-3.5 w-3.5 text-emerald-400" />
            Spectrum Audit
          </Button>

          <Button
            type="button"
            size="sm"
            variant="secondary"
            onClick={() => navigate("/tools?tab=duplicates")}
          >
            <CopyCheck className="h-3.5 w-3.5 text-sky-300" />
            Deduplicate
          </Button>

          <Button
            type="button"
            size="sm"
            variant="secondary"
            onClick={() =>
              void api.settings
                .openFolder()
                .catch((err) =>
                  toast.error("Could not open folder", {
                    description: err instanceof Error ? err.message : undefined,
                  })
                )
            }
          >
            <FolderOpen className="h-3.5 w-3.5" />
            Downloads
          </Button>

          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={rescanning}
            onClick={() => void handleRescan()}
            title="Rescan & synchronize audio files on disk"
          >
            <RefreshCw className={cn("h-3.5 w-3.5", rescanning && "animate-spin")} />
            {rescanning ? "Scanning..." : "Rescan"}
          </Button>
        </div>
      </div>

      {/* 2. Search, Sort & Genre Controls */}
      <div className="glass-panel rounded-2xl p-3 flex flex-col lg:flex-row gap-2.5 items-stretch lg:items-center">
        <div className="flex-1 min-w-0">
          <Input
            ref={searchInputRef}
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            leadingIcon={<Search className="h-3.5 w-3.5" />}
            placeholder="Search songs, artists, albums, or playlists (Ctrl+F)..."
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
          {viewingTrackRows && tracks.length > 0 && (
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
            onChange={(e) => setSortBy(e.target.value as LibrarySort)}
            aria-label="Sort library"
            className="h-8 rounded-lg border border-white/10 bg-elevated px-2.5 text-xs text-zinc-200 focus:border-emerald-500/60 focus:outline-none cursor-pointer"
          >
            <option value="title">Sort: Title (A–Z)</option>
            <option value="track_number">
              {viewingTrackRows ? "Sort: Track Number" : "Sort: Track Count"}
            </option>
            <option value="artist">Sort: Artist (A–Z)</option>
            <option value="duration_asc">
              {viewingTrackRows ? "Sort: Duration (Shortest)" : "Sort: Size (Smallest)"}
            </option>
            <option value="duration_desc">
              {viewingTrackRows ? "Sort: Duration (Longest)" : "Sort: Size (Largest)"}
            </option>
            <option value="recent">Sort: Recently Added</option>
            <option value="genre">Sort: Genre (A–Z)</option>
          </select>

          <select
            value={genreFilter}
            onChange={(e) => setGenreFilter(e.target.value)}
            aria-label="Filter by genre"
            className="h-8 rounded-lg border border-white/10 bg-elevated px-2.5 text-xs text-zinc-200 focus:border-emerald-500/60 focus:outline-none cursor-pointer max-w-[165px]"
          >
            <option value="all">All Genres</option>
            {availableGenres.map((g) => (
              <option key={g} value={g}>
                {g}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* 3. Collection Drill-Down Banner */}
      {activeCollection && (
        <div className="relative overflow-hidden rounded-2xl glass-panel p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="flex items-center gap-3 min-w-0">
            <Button
              type="button"
              size="sm"
              variant="secondary"
              onClick={() => {
                setActiveCollection(null);
                setSelectedIds(new Set());
              }}
            >
              <ArrowLeft className="h-3.5 w-3.5" />
              Back to{" "}
              {activeCollection.type === "album" ? "Albums" : "Playlists"}
            </Button>

            <div className="h-11 w-11 shrink-0 overflow-hidden rounded-lg bg-elevated border border-white/10 flex items-center justify-center text-zinc-500">
              {activeCollection.type === "album" ? (
                <Disc3 className="h-5 w-5" />
              ) : (
                <Folder className="h-5 w-5" />
              )}
              <img
                src={apiUrl(activeCollection.coverUrlLocal)}
                alt={activeCollection.name}
                className="h-full w-full object-cover"
                onError={(e) => {
                  e.currentTarget.style.display = "none";
                }}
              />
            </div>

            <div className="min-w-0">
              <h2 className="text-sm sm:text-base font-semibold text-white truncate">
                {activeCollection.name}
              </h2>
              <p className="text-xs text-zinc-400 truncate font-mono">
                {activeCollection.artist ? `by ${activeCollection.artist} · ` : ""}
                {tracks.length} song(s)
                {activeCollection.sizeStr ? ` · ${activeCollection.sizeStr}` : ""}
              </p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-1.5 shrink-0">
            <Button
              type="button"
              size="sm"
              disabled={tracks.length === 0}
              onClick={() => handlePlayTrack(tracks[0])}
            >
              <Play className="h-3.5 w-3.5" />
              Play All
            </Button>

            <Button
              type="button"
              size="sm"
              variant="secondary"
              onClick={() =>
                void api.settings
                  .openFolder(activeCollection.folderPath || undefined)
                  .catch((err) =>
                    toast.error("Folder not found", {
                      description: err instanceof Error ? err.message : undefined,
                    })
                  )
              }
            >
              <FolderOpen className="h-3.5 w-3.5" />
              Folder
            </Button>

            <Button
              type="button"
              size="sm"
              variant="secondary"
              onClick={() =>
                setExportSongsTarget({
                  playlistName: activeCollection.name,
                  collectionName: activeCollection.name,
                  collectionType: activeCollection.type,
                  trackCountHint: tracks.length,
                })
              }
            >
              <FolderOutput className="h-3.5 w-3.5" />
              Export
            </Button>

            <Button
              type="button"
              size="sm"
              variant="secondary"
              onClick={() =>
                setExportM3u8Target({
                  playlistName: activeCollection.name,
                  collectionName: activeCollection.name,
                  collectionType: activeCollection.type,
                })
              }
            >
              <FileMusic className="h-3.5 w-3.5" />
              M3U8
            </Button>

            {activeCollection.type === "playlist" && (
              <Button
                type="button"
                size="icon"
                variant="secondary"
                className="h-8 w-8"
                onClick={() => setRenamingName(activeCollection.name)}
                title="Rename playlist"
              >
                <Pencil className="h-3.5 w-3.5" />
              </Button>
            )}
          </div>
        </div>
      )}

      {/* 4. Multi-Selection Mini Bar */}
      {viewingTrackRows && selectedIds.size > 0 && (
        <div className="glass-panel rounded-xl px-4 py-2 flex flex-wrap items-center justify-between gap-2 border border-emerald-500/35 bg-emerald-500/[0.06]">
          <div className="flex items-center gap-2 text-xs">
            <span className="font-semibold font-mono text-emerald-300 tabular-nums">
              {selectedIds.size} track{selectedIds.size === 1 ? "" : "s"} selected
            </span>
            <button
              type="button"
              onClick={() => setSelectedIds(new Set())}
              className="rounded px-2 py-0.5 text-zinc-400 hover:bg-white/10 hover:text-white cursor-pointer"
            >
              Clear
            </button>
          </div>
          <div className="flex items-center gap-2">
            <Button
              type="button"
              size="sm"
              variant="secondary"
              onClick={() =>
                setExportSongsTarget({
                  playlistName: activeCollection?.name || "Exported Songs",
                  trackIds: Array.from(selectedIds),
                  trackCountHint: selectedIds.size,
                })
              }
            >
              <FolderOutput className="h-3.5 w-3.5" />
              Export Selected
            </Button>
            <Button
              type="button"
              size="sm"
              variant="secondary"
              onClick={() =>
                setExportM3u8Target({
                  playlistName: activeCollection?.name || "Selected Playlist",
                  trackIds: Array.from(selectedIds),
                })
              }
            >
              <FileMusic className="h-3.5 w-3.5" />
              Export .m3u8
            </Button>
          </div>
        </div>
      )}

      {/* 5. Content Stage */}
      {viewingTrackRows ? (
        (activeCollection ? loadingCollTracks : loadingTracks) ? (
          <div className="space-y-2">
            {Array.from({ length: 6 }).map((_, i) => (
              <Skeleton key={i} className="h-16 rounded-xl" />
            ))}
          </div>
        ) : tracks.length === 0 && !debouncedSearch && genreFilter === "all" && !activeCollection ? (
          <div className="glass-panel rounded-2xl p-12 text-center space-y-2 border border-dashed border-white/[0.12]">
            <LibraryIcon className="h-8 w-8 mx-auto text-emerald-400/80" />
            <h2 className="text-base font-semibold text-white">
              Your Offline Library is Empty
            </h2>
            <p className="text-sm text-zinc-400 max-w-md mx-auto">
              Downloaded tracks will appear here automatically. Already have
              music on disk? Click <strong>Rescan</strong> above to index it.
            </p>
          </div>
        ) : (
          <LibraryTrackList
            tracks={tracks}
            selectedIds={selectedIds}
            playingTrackId={playingTrackId}
            onRowClick={handleRowClick}
            onCheckboxClick={handleCheckboxClick}
            onDoubleClick={handlePlayTrack}
            onPlay={handlePlayTrack}
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
            onCopyTitle={(tr) =>
              void navigator.clipboard
                .writeText(`${tr.title} - ${tr.artist}`)
                .then(() => toast.success("Copied title & artist"))
            }
            onRedownload={async (tr, eng: EngineChoice) => {
              try {
                await api.library.redownloadTrack(tr.spotify_id, eng);
                invalidateLibrary();
                void queryClient.invalidateQueries({ queryKey: ["queue"] });
                toast.info(`Re-downloading "${tr.title}" via ${eng}`);
              } catch (err) {
                toast.error("Re-download failed", {
                  description: err instanceof Error ? err.message : undefined,
                });
              }
            }}
            onDeleteFile={(tr) => setDeletingDiskTrack(tr)}
            onRemoveFromArchive={async (tr) => {
              await api.library.deleteTrack(tr.spotify_id, false);
              invalidateLibrary();
              toast.info(`Removed "${tr.title}" from archive index`);
            }}
            onExportSelected={(fallback) => {
              const ids =
                selectedIds.size > 0
                  ? Array.from(selectedIds)
                  : [fallback.spotify_id];
              setExportSongsTarget({
                playlistName: activeCollection?.name || "Exported Songs",
                trackIds: ids,
                trackCountHint: ids.length,
              });
            }}
            onExportM3u8={() => {
              const ids =
                selectedIds.size > 1
                  ? Array.from(selectedIds)
                  : tracks.map((t) => t.spotify_id);
              setExportM3u8Target({
                playlistName: activeCollection?.name || "Library Playlist",
                trackIds: ids,
              });
            }}
            onViewDetails={(tr) => setDetailsTrack(tr)}
            onInspectSpectrum={(tr) => setSpectrumTrack(tr)}
            onNormalizeTrack={async (tr) => {
              toast.info(`Normalizing loudness for "${tr.title}"...`);
              try {
                const res = await api.tools.normalizeTrack(tr.spotify_id);
                if (res.success && res.measured_lufs !== null && res.gain_db !== null) {
                  toast.success(`Normalized "${tr.title}"`, {
                    description: `${res.measured_lufs.toFixed(1)} LUFS → ${res.target_lufs.toFixed(1)} LUFS (${res.gain_db >= 0 ? "+" : ""}${res.gain_db.toFixed(1)} dB)`,
                  });
                } else {
                  toast.warning(`Skipped loudness balance for "${tr.title}"`);
                }
              } catch (err) {
                toast.error("Volume normalization failed", {
                  description: err instanceof Error ? err.message : undefined,
                });
              }
            }}
            onReplayGainTrack={async (tr) => {
              toast.info(`Calculating ReplayGain 2.0 for "${tr.title}"...`);
              try {
                const res = await api.tools.replaygainTrack(tr.spotify_id);
                if (res.success) {
                  toast.success(`ReplayGain applied to "${tr.title}"`, {
                    description: `${res.track_gain} (peak ${res.track_peak})`,
                  });
                } else {
                  toast.warning(`Could not compute ReplayGain for "${tr.title}"`);
                }
              } catch (err) {
                toast.error("ReplayGain calculation failed", {
                  description: err instanceof Error ? err.message : undefined,
                });
              }
            }}
          />
        )
      ) : activeTab === "playlists" ? (
        loadingPlaylists ? (
          <div className="space-y-3">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-20 rounded-2xl" />
            ))}
          </div>
        ) : playlists.length === 0 ? (
          <div className="glass-panel rounded-2xl p-12 text-center space-y-2 border border-dashed border-white/[0.12]">
            <Folder className="h-8 w-8 mx-auto text-emerald-400/80" />
            <h2 className="text-base font-semibold text-white">
              No Downloaded Playlists Found
            </h2>
            <p className="text-sm text-zinc-400">
              No playlists match your filter or have been downloaded yet.
            </p>
          </div>
        ) : (
          <div className="space-y-2.5">
            {playlists.map((coll) => (
              <CollectionCard
                key={coll.name}
                collection={coll}
                type="playlist"
                onBrowse={(c) => handleBrowseCollection(c, "playlist")}
                onRename={(c) => setRenamingName(c.name)}
                onOpenFolder={(c) =>
                  void api.settings
                    .openFolder(c.folder_path || undefined)
                    .catch((err) =>
                      toast.error("Folder not found", {
                        description: err instanceof Error ? err.message : undefined,
                      })
                    )
                }
                onExportSongs={(c) =>
                  setExportSongsTarget({
                    playlistName: c.name,
                    collectionName: c.name,
                    collectionType: "playlist",
                    trackCountHint: c.track_count,
                  })
                }
                onExportM3u8={(c) =>
                  setExportM3u8Target({
                    playlistName: c.name,
                    collectionName: c.name,
                    collectionType: "playlist",
                  })
                }
              />
            ))}
          </div>
        )
      ) : loadingAlbums ? (
        <div className="space-y-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-20 rounded-2xl" />
          ))}
        </div>
      ) : albums.length === 0 ? (
        <div className="glass-panel rounded-2xl p-12 text-center space-y-2 border border-dashed border-white/[0.12]">
          <Disc3 className="h-8 w-8 mx-auto text-emerald-400/80" />
          <h2 className="text-base font-semibold text-white">
            No Downloaded Albums Found
          </h2>
          <p className="text-sm text-zinc-400 max-w-md mx-auto">
            Download a Spotify album link to browse complete discographies
            sorted cleanly by track number.
          </p>
        </div>
      ) : (
        <div className="space-y-2.5">
          {albums.map((coll) => (
            <CollectionCard
              key={coll.name}
              collection={coll}
              type="album"
              onBrowse={(c) => handleBrowseCollection(c, "album")}
              onOpenFolder={(c) =>
                void api.settings
                  .openFolder(c.folder_path || undefined)
                  .catch((err) =>
                    toast.error("Folder not found", {
                      description: err instanceof Error ? err.message : undefined,
                    })
                  )
              }
              onExportSongs={(c) =>
                setExportSongsTarget({
                  playlistName: c.name,
                  collectionName: c.name,
                  collectionType: "album",
                  trackCountHint: c.track_count,
                })
              }
              onExportM3u8={(c) =>
                setExportM3u8Target({
                  playlistName: c.name,
                  collectionName: c.name,
                  collectionType: "album",
                })
              }
            />
          ))}
        </div>
      )}

      {/* Modals */}
      <RenameCollectionModal
        oldName={renamingName}
        collectionType="playlist"
        onRenamed={(newName) => {
          if (activeCollection && activeCollection.name === renamingName) {
            setActiveCollection({ ...activeCollection, name: newName });
          }
        }}
        onClose={() => setRenamingName(null)}
      />

      <TrackDetailsModal
        track={detailsTrack}
        onClose={() => setDetailsTrack(null)}
      />

      <TrackSpectrumModal
        track={spectrumTrack}
        onClose={() => setSpectrumTrack(null)}
      />

      <ExportM3u8Modal
        target={exportM3u8Target}
        onClose={() => setExportM3u8Target(null)}
      />

      <ExportSongsModal
        target={exportSongsTarget}
        onClose={() => setExportSongsTarget(null)}
      />

      {/* Delete File Confirmation */}
      <AnimatePresence>
        {deletingDiskTrack && (
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setDeletingDiskTrack(null)}
              className="fixed inset-0 bg-black/75 backdrop-blur-sm"
            />
            <motion.div
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.95 }}
              className="relative z-10 w-full max-w-md rounded-2xl glass-panel p-6 shadow-2xl space-y-4"
            >
              <h2 className="text-base font-semibold text-white">
                Delete Audio File from Disk?
              </h2>
              <p className="text-xs text-zinc-400 leading-relaxed">
                This permanently deletes{" "}
                <strong className="text-zinc-200">
                  {deletingDiskTrack.title}
                </strong>{" "}
                by {deletingDiskTrack.artist} from disk and removes it from your
                library index.
              </p>
              <div className="flex justify-end gap-2 pt-2 border-t border-white/[0.06]">
                <Button
                  type="button"
                  variant="ghost"
                  onClick={() => setDeletingDiskTrack(null)}
                >
                  Cancel
                </Button>
                <Button
                  type="button"
                  variant="destructive"
                  onClick={async () => {
                    const tr = deletingDiskTrack;
                    setDeletingDiskTrack(null);
                    await api.library.deleteTrack(tr.spotify_id, true);
                    invalidateLibrary();
                    toast.success(`Deleted "${tr.title}" from disk`);
                  }}
                >
                  Delete File
                </Button>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>
    </div>
  );
}
