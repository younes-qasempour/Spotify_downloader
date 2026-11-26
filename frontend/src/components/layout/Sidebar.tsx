import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import {
  ArrowUpDown,
  ChevronLeft,
  ChevronRight,
  Cpu,
  Disc3,
  Download,
  Folder,
  HardDrive,
  Library,
  ListMusic,
  Loader2,
  Pin,
  Play,
  Plus,
  RefreshCw,
  Search,
  Settings,
  Wrench,
  X,
} from "lucide-react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { apiUrl } from "@/api/client";
import { api } from "@/api/endpoints";
import type { PlayerTrack } from "@/api/types";
import { cn } from "@/lib/utils";
import { useAppStore } from "@/stores/appStore";
import { usePlayerStore } from "@/stores/playerStore";

interface NavItem {
  to: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  end?: boolean;
  badge?: number | string;
}

type SidebarFilter = "all" | "playlists" | "saved" | "albums";
type SidebarSort = "recent" | "alpha" | "tracks";

interface SidebarCollectionItem {
  key: string;
  name: string;
  kind: "saved" | "library-playlist" | "album";
  savedId?: string;
  artist?: string;
  autoSync: boolean;
  downloadedCount: number;
  totalTracks: number;
  progressPercent: number;
  trackCount: number;
  sizeStr?: string;
  sortTimestamp: string;
  coverSrc: string;
}

const SORT_LABELS: Record<SidebarSort, string> = {
  recent: "Sort: Recent (Pinned First)",
  alpha: "Sort: A–Z",
  tracks: "Sort: Most Tracks",
};

const NEXT_SORT: Record<SidebarSort, SidebarSort> = {
  recent: "alpha",
  alpha: "tracks",
  tracks: "recent",
};

interface SidebarCollectionRowProps {
  item: SidebarCollectionItem;
  isActive: boolean;
  isLoadingPlay: boolean;
  onSelect: () => void;
  onQuickPlay: (e: React.MouseEvent) => void;
}

function SidebarCollectionRow({
  item,
  isActive,
  isLoadingPlay,
  onSelect,
  onQuickPlay,
}: SidebarCollectionRowProps) {
  const [imgFailed, setImgFailed] = useState(false);

  const showProgressBar =
    item.kind === "saved" &&
    item.totalTracks > 0 &&
    item.downloadedCount < item.totalTracks;

  const secondaryText =
    item.kind === "saved"
      ? `${item.downloadedCount}/${item.totalTracks} tracks${item.sizeStr ? ` · ${item.sizeStr}` : ""}`
      : item.kind === "album"
        ? `${item.artist ? `${item.artist} · ` : ""}${item.trackCount} tracks`
        : `${item.trackCount} songs${item.sizeStr ? ` · ${item.sizeStr}` : ""}`;

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onSelect}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect();
        }
      }}
      className={cn(
        "group/row flex w-full items-center gap-2.5 rounded-xl px-2 py-1.5 text-left transition-colors cursor-pointer border",
        isActive
          ? "bg-emerald-500/12 border-emerald-500/30"
          : "border-transparent hover:bg-white/[0.05]"
      )}
    >
      {/* Thumbnail + Hover Quick Play */}
      <div className="relative h-9 w-9 shrink-0 overflow-hidden rounded-lg bg-elevated border border-white/[0.08]">
        {item.coverSrc && !imgFailed ? (
          <img
            src={item.coverSrc}
            alt={item.name}
            onError={() => setImgFailed(true)}
            className="h-full w-full object-cover"
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center text-zinc-500">
            {item.kind === "album" ? (
              <Disc3 className="h-4 w-4" />
            ) : item.kind === "library-playlist" ? (
              <Folder className="h-4 w-4" />
            ) : (
              <ListMusic className="h-4 w-4" />
            )}
          </div>
        )}

        <button
          type="button"
          onClick={onQuickPlay}
          title={`Play ${item.name}`}
          aria-label={`Play ${item.name}`}
          className={cn(
            "absolute inset-0 flex items-center justify-center bg-black/65 text-white transition-opacity cursor-pointer",
            isLoadingPlay
              ? "opacity-100"
              : "opacity-0 group-hover/row:opacity-100 focus:opacity-100"
          )}
        >
          {isLoadingPlay ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin text-emerald-bright" />
          ) : (
            <Play className="h-3.5 w-3.5 fill-current text-emerald-bright translate-x-[0.5px]" />
          )}
        </button>
      </div>

      {/* Title, Badges, Subtitle & Micro Progress */}
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1 min-w-0">
          <span
            className={cn(
              "truncate text-xs font-medium",
              isActive
                ? "text-emerald-300"
                : "text-zinc-200 group-hover/row:text-white"
            )}
          >
            {item.name}
          </span>
          {item.autoSync && (
            <Pin
              className="h-2.5 w-2.5 shrink-0 text-emerald-400"
              aria-label="Auto-Sync Pinned"
            />
          )}
          {item.kind === "album" && (
            <span className="shrink-0 rounded bg-white/[0.06] px-1 py-0 text-[9px] font-medium uppercase tracking-wide text-zinc-400">
              Album
            </span>
          )}
          {item.kind === "library-playlist" && (
            <span className="shrink-0 rounded bg-white/[0.06] px-1 py-0 text-[9px] font-medium uppercase tracking-wide text-zinc-400">
              Offline
            </span>
          )}
        </div>

        <div className="truncate text-[11px] text-zinc-500 font-mono tabular-nums">
          {secondaryText}
        </div>

        {showProgressBar && (
          <div className="mt-1 h-[2px] w-full overflow-hidden rounded-full bg-white/[0.08]">
            <div
              className="h-full rounded-full bg-emerald-bright/85 transition-[width] duration-300"
              style={{
                width: `${Math.max(3, Math.min(100, item.progressPercent))}%`,
              }}
            />
          </div>
        )}
      </div>
    </div>
  );
}

interface CollapsedCollectionThumbProps {
  item: SidebarCollectionItem;
  isActive: boolean;
  onSelect: () => void;
}

function CollapsedCollectionThumb({
  item,
  isActive,
  onSelect,
}: CollapsedCollectionThumbProps) {
  const [imgFailed, setImgFailed] = useState(false);

  const tooltip =
    item.kind === "saved"
      ? `${item.name} (${item.downloadedCount}/${item.totalTracks} tracks)`
      : item.kind === "album"
        ? `${item.name}${item.artist ? ` — ${item.artist}` : ""} (${item.trackCount} tracks)`
        : `${item.name} (${item.trackCount} songs)`;

  return (
    <button
      type="button"
      onClick={onSelect}
      title={tooltip}
      aria-label={item.name}
      className={cn(
        "relative h-9 w-9 shrink-0 overflow-hidden rounded-lg bg-elevated border transition-all cursor-pointer",
        isActive
          ? "ring-2 ring-emerald-bright border-emerald-bright/60 scale-105"
          : "border-white/[0.08] hover:border-white/25 hover:scale-105"
      )}
    >
      {item.coverSrc && !imgFailed ? (
        <img
          src={item.coverSrc}
          alt={item.name}
          onError={() => setImgFailed(true)}
          className="h-full w-full object-cover"
        />
      ) : (
        <div className="flex h-full w-full items-center justify-center text-zinc-400">
          {item.kind === "album" ? (
            <Disc3 className="h-4 w-4" />
          ) : (
            <ListMusic className="h-4 w-4" />
          )}
        </div>
      )}
    </button>
  );
}

export function Sidebar() {
  const navigate = useNavigate();
  const location = useLocation();

  const collapsed = useAppStore((s) => s.sidebarCollapsed);
  const mobileOpen = useAppStore((s) => s.mobileNavOpen);
  const toggleSidebar = useAppStore((s) => s.toggleSidebar);
  const setMobileNavOpen = useAppStore((s) => s.setMobileNavOpen);
  const wsStatus = useAppStore((s) => s.wsStatus);
  const backendVersion = useAppStore((s) => s.backendVersion);
  const activeToolProgress = useAppStore((s) => s.activeToolProgress);

  const [filter, setFilter] = useState<SidebarFilter>("all");
  const [sortBy, setSortBy] = useState<SidebarSort>("recent");
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [playingKey, setPlayingKey] = useState<string | null>(null);

  const { data: queueData } = useQuery({
    queryKey: ["queue"],
    queryFn: () => api.queue.list(),
    refetchInterval: wsStatus === "connected" ? false : 15000,
  });

  const {
    data: playlistsData,
    isLoading: loadingSaved,
    isFetching: fetchingSaved,
    isError: errorSaved,
    refetch: refetchSaved,
  } = useQuery({
    queryKey: ["playlists"],
    queryFn: () => api.playlists.list(),
    staleTime: 30000,
  });

  const {
    data: libraryPlaylistsData,
    isLoading: loadingLibPlaylists,
    isFetching: fetchingLibPlaylists,
    isError: errorLibPlaylists,
    refetch: refetchLibPlaylists,
  } = useQuery({
    queryKey: ["library", "playlists", "sidebar"],
    queryFn: () => api.library.playlists({ sort: "recent" }),
    staleTime: 30000,
  });

  const {
    data: libraryAlbumsData,
    isLoading: loadingLibAlbums,
    isFetching: fetchingLibAlbums,
    isError: errorLibAlbums,
    refetch: refetchLibAlbums,
  } = useQuery({
    queryKey: ["library", "albums", "sidebar"],
    queryFn: () => api.library.albums({ sort: "recent" }),
    staleTime: 30000,
  });

  const libraryLoading =
    loadingSaved ||
    loadingLibPlaylists ||
    loadingLibAlbums ||
    fetchingSaved ||
    fetchingLibPlaylists ||
    fetchingLibAlbums ||
    wsStatus === "connecting";
  const libraryError = errorSaved || errorLibPlaylists || errorLibAlbums;

  const retrySidebarLibrary = () => {
    void refetchSaved();
    void refetchLibPlaylists();
    void refetchLibAlbums();
  };

  const { data: libraryStats } = useQuery({
    queryKey: ["library", "stats"],
    queryFn: () => api.library.stats(),
    staleTime: 30000,
  });

  const { data: settingsData } = useQuery({
    queryKey: ["settings"],
    queryFn: () => api.settings.get(),
    staleTime: 60000,
  });

  const activeQueueCount =
    (queueData?.stats.active ?? 0) + (queueData?.stats.queued ?? 0);

  const navItems: NavItem[] = [
    {
      to: "/",
      label: "Queue",
      icon: Download,
      end: true,
      badge: activeQueueCount > 0 ? activeQueueCount : undefined,
    },
    {
      to: "/playlists",
      label: "Saved Playlists",
      icon: ListMusic,
      badge: playlistsData?.summary.total_playlists || undefined,
    },
    {
      to: "/library",
      label: "Library",
      icon: Library,
      badge: libraryStats?.total_tracks || undefined,
    },
    {
      to: "/tools",
      label: "Audio Tools",
      icon: Wrench,
    },
    {
      to: "/settings",
      label: "Settings",
      icon: Settings,
    },
  ];

  const allItems = useMemo<SidebarCollectionItem[]>(() => {
    const saved = playlistsData?.playlists ?? [];
    const libPlaylists = libraryPlaylistsData?.playlists ?? [];
    const libAlbums = libraryAlbumsData?.albums ?? [];

    const libPlaylistByNormName = new Map(
      libPlaylists.map((pl) => [pl.name.trim().toLowerCase(), pl])
    );

    const merged: SidebarCollectionItem[] = [];
    const seenSavedNames = new Set<string>();

    for (const pl of saved) {
      const norm = pl.name.trim().toLowerCase();
      seenSavedNames.add(norm);
      const libMatch = libPlaylistByNormName.get(norm);
      const coverSrc = pl.local_cover
        ? apiUrl(`/api/media/cover/collection?name=${encodeURIComponent(pl.name)}`)
        : pl.cover_url
          ? pl.cover_url
          : libMatch?.cover_url_local
            ? apiUrl(libMatch.cover_url_local)
            : "";

      merged.push({
        key: `saved:${pl.id}`,
        name: pl.name,
        kind: "saved",
        savedId: pl.id,
        autoSync: Boolean(pl.auto_sync),
        downloadedCount: pl.downloaded_count,
        totalTracks: pl.total_tracks,
        progressPercent: pl.progress_percent,
        trackCount: Math.max(pl.total_tracks, libMatch?.track_count ?? 0),
        sizeStr: libMatch?.size_str,
        sortTimestamp:
          pl.last_synced_at ||
          libMatch?.latest_download ||
          pl.updated_at ||
          pl.created_at ||
          "",
        coverSrc,
      });
    }

    for (const pl of libPlaylists) {
      const norm = pl.name.trim().toLowerCase();
      if (seenSavedNames.has(norm)) continue;
      merged.push({
        key: `lib-pl:${norm}`,
        name: pl.name,
        kind: "library-playlist",
        autoSync: false,
        downloadedCount: pl.track_count,
        totalTracks: pl.track_count,
        progressPercent: 100,
        trackCount: pl.track_count,
        sizeStr: pl.size_str,
        sortTimestamp: pl.latest_download || "",
        coverSrc: pl.cover_url_local ? apiUrl(pl.cover_url_local) : "",
      });
    }

    for (const alb of libAlbums) {
      const norm = alb.name.trim().toLowerCase();
      merged.push({
        key: `lib-alb:${norm}`,
        name: alb.name,
        kind: "album",
        artist: alb.artist,
        autoSync: false,
        downloadedCount: alb.track_count,
        totalTracks: alb.track_count,
        progressPercent: 100,
        trackCount: alb.track_count,
        sizeStr: alb.size_str,
        sortTimestamp: alb.latest_download || "",
        coverSrc: alb.cover_url_local ? apiUrl(alb.cover_url_local) : "",
      });
    }

    return merged;
  }, [playlistsData?.playlists, libraryPlaylistsData?.playlists, libraryAlbumsData?.albums]);

  const counts = useMemo(() => {
    let playlistsCount = 0;
    let savedCount = 0;
    let albumsCount = 0;
    for (const item of allItems) {
      if (item.kind === "saved") {
        savedCount += 1;
        playlistsCount += 1;
      } else if (item.kind === "library-playlist") {
        playlistsCount += 1;
      } else {
        albumsCount += 1;
      }
    }
    return {
      all: allItems.length,
      playlists: playlistsCount,
      saved: savedCount,
      albums: albumsCount,
    };
  }, [allItems]);

  const filteredItems = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    const list = allItems.filter((item) => {
      if (filter === "playlists" && item.kind === "album") return false;
      if (filter === "saved" && item.kind !== "saved") return false;
      if (filter === "albums" && item.kind !== "album") return false;
      if (!q) return true;
      return (
        item.name.toLowerCase().includes(q) ||
        (item.artist ? item.artist.toLowerCase().includes(q) : false)
      );
    });

    const sorted = [...list];
    sorted.sort((a, b) => {
      if (sortBy === "alpha") {
        return a.name.localeCompare(b.name);
      }
      if (sortBy === "tracks") {
        if (b.trackCount !== a.trackCount) {
          return b.trackCount - a.trackCount;
        }
        return a.name.localeCompare(b.name);
      }
      // "recent": autoSync pinned first, then most recent timestamp, then A–Z
      if (a.autoSync !== b.autoSync) {
        return Number(b.autoSync) - Number(a.autoSync);
      }
      const tsCmp = b.sortTimestamp.localeCompare(a.sortTimestamp);
      if (tsCmp !== 0) return tsCmp;
      return a.name.localeCompare(b.name);
    });
    return sorted;
  }, [allItems, filter, searchQuery, sortBy]);

  const locationParams = useMemo(
    () => new URLSearchParams(location.search),
    [location.search]
  );

  const isItemActive = (item: SidebarCollectionItem): boolean => {
    if (item.kind === "saved" && item.savedId) {
      return location.pathname === `/playlists/${item.savedId}`;
    }
    if (location.pathname !== "/library") return false;
    const col = locationParams.get("collection");
    const type = locationParams.get("type") || "playlist";
    const expectedType = item.kind === "album" ? "album" : "playlist";
    return Boolean(col && col === item.name && type === expectedType);
  };

  const handleSelectItem = (item: SidebarCollectionItem, isMobile: boolean) => {
    if (item.kind === "saved" && item.savedId) {
      navigate(`/playlists/${item.savedId}`);
    } else {
      const targetTab = item.kind === "album" ? "albums" : "playlists";
      const targetType = item.kind === "album" ? "album" : "playlist";
      navigate(
        `/library?tab=${targetTab}&collection=${encodeURIComponent(item.name)}&type=${targetType}`
      );
    }
    if (isMobile) setMobileNavOpen(false);
  };

  const handleQuickPlay = async (
    item: SidebarCollectionItem,
    e: React.MouseEvent
  ) => {
    e.stopPropagation();
    if (playingKey === item.key) return;
    setPlayingKey(item.key);
    try {
      let playable: PlayerTrack[] = [];
      if (item.kind === "saved" && item.savedId) {
        const res = await api.playlists.detail(item.savedId, { reconcile: true });
        playable = res.tracks
          .filter((t) => t.status === "downloaded" || t.file_exists)
          .map((tr) => ({
            id: tr.spotify_id,
            title: tr.title,
            artist: tr.artist,
            album: tr.album,
            durationSec: Math.round((tr.duration_ms || 0) / 1000),
            audioUrl: `/api/media/audio/${encodeURIComponent(tr.spotify_id)}`,
            coverUrl: `/api/media/cover/track/${encodeURIComponent(tr.spotify_id)}`,
            qualityBadge: tr.quality_badge,
            sourceType: tr.source_type,
          }));
      } else {
        const targetType = item.kind === "album" ? "album" : "playlist";
        const res = await api.library.collectionTracks({
          name: item.name,
          type: targetType,
          sort: item.kind === "album" ? "track_number" : "title",
        });
        playable = res.tracks.map((tr) => ({
          id: tr.spotify_id,
          title: tr.title,
          artist: tr.artist,
          album: tr.album,
          durationSec: Math.round((tr.duration_ms || 0) / 1000),
          audioUrl: tr.audio_url,
          coverUrl: tr.cover_url_local,
          qualityBadge: tr.quality_badge,
          sourceType: tr.source_type,
        }));
      }

      if (playable.length === 0) {
        toast.info(`"${item.name}" has no downloaded tracks yet`);
        return;
      }
      usePlayerStore.getState().playTrackList(playable, 0);
    } catch (err) {
      toast.error(`Failed to play "${item.name}"`, {
        description: err instanceof Error ? err.message : undefined,
      });
    } finally {
      setPlayingKey((cur) => (cur === item.key ? null : cur));
    }
  };

  const engineLabel =
    settingsData?.derived.effective_source_engine === "melobot"
      ? "MeloBot TG"
      : "Musilon VIP";

  const renderSidebarContent = (isCompact: boolean, isMobile = false) => (
    <div className="flex h-full flex-col bg-panel/95 border-r border-white/[0.07] select-none">
      {/* Brand Header */}
      <div
        className={cn(
          "flex h-14 shrink-0 items-center border-b border-white/[0.06] px-3.5",
          isCompact ? "justify-center" : "justify-between"
        )}
      >
        <div className="flex items-center gap-2.5 min-w-0">
          <img
            src="/flacify-icon.png"
            alt="Flacify"
            className="h-7 w-7 shrink-0 rounded-lg object-cover shadow-md shadow-emerald-500/20"
            onError={(e) => {
              e.currentTarget.style.display = "none";
            }}
          />
          {!isCompact && (
            <div className="flex items-center gap-2 min-w-0">
              <span className="font-semibold tracking-tight text-white truncate">
                Flacify
              </span>
              <span className="rounded-md bg-emerald-500/15 px-1.5 py-0.5 text-[10px] font-mono font-medium text-emerald-300 border border-emerald-500/25">
                v{backendVersion || "2.0"}
              </span>
            </div>
          )}
        </div>

        {isMobile ? (
          <button
            type="button"
            onClick={() => setMobileNavOpen(false)}
            className="rounded-lg p-1.5 text-zinc-400 hover:bg-white/8 hover:text-white cursor-pointer"
            aria-label="Close navigation"
          >
            <X className="h-4 w-4" />
          </button>
        ) : (
          !isCompact && (
            <button
              type="button"
              onClick={toggleSidebar}
              className="rounded-lg p-1.5 text-zinc-400 hover:bg-white/8 hover:text-white transition-colors cursor-pointer"
              title="Collapse sidebar"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
          )
        )}
      </div>

      {isCompact && !isMobile && (
        <div className="flex shrink-0 justify-center py-2 border-b border-white/[0.05]">
          <button
            type="button"
            onClick={toggleSidebar}
            className="rounded-lg p-1.5 text-zinc-400 hover:bg-white/8 hover:text-white transition-colors cursor-pointer"
            title="Expand sidebar"
          >
            <ChevronRight className="h-4 w-4" />
          </button>
        </div>
      )}

      {/* Primary Navigation */}
      <nav className="shrink-0 px-2.5 pt-3 pb-2 space-y-1">
        {navItems.map((item) => {
          const Icon = item.icon;
          return (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              onClick={() => {
                if (isMobile) setMobileNavOpen(false);
              }}
              title={isCompact ? item.label : undefined}
              className={({ isActive }) =>
                cn(
                  "relative flex items-center gap-3 rounded-xl px-3 py-2 text-sm font-medium transition-colors",
                  isCompact && "justify-center px-2",
                  isActive
                    ? "text-white"
                    : "text-zinc-400 hover:text-zinc-100 hover:bg-white/[0.04]"
                )
              }
            >
              {({ isActive }) => (
                <>
                  {isActive && (
                    <motion.span
                      layoutId={
                        isMobile
                          ? "sidebar-active-pill-mobile"
                          : "sidebar-active-pill"
                      }
                      transition={{
                        type: "spring",
                        stiffness: 380,
                        damping: 32,
                      }}
                      className="absolute inset-0 rounded-xl bg-white/[0.08] border border-white/[0.08]"
                    />
                  )}
                  <Icon
                    className={cn(
                      "relative z-10 h-4 w-4 shrink-0 transition-colors",
                      isActive ? "text-emerald-bright" : "text-zinc-400"
                    )}
                  />
                  {!isCompact && (
                    <>
                      <span className="relative z-10 flex-1 truncate">
                        {item.label}
                      </span>
                      {item.badge !== undefined && (
                        <span
                          className={cn(
                            "relative z-10 rounded-full px-2 py-0.5 text-[11px] font-mono tabular-nums",
                            isActive
                              ? "bg-emerald-500/20 text-emerald-300"
                              : "bg-white/[0.06] text-zinc-400"
                          )}
                        >
                          {item.badge}
                        </span>
                      )}
                    </>
                  )}
                </>
              )}
            </NavLink>
          );
        })}
      </nav>

      {/* Expanded "Your Library" Panel */}
      {!isCompact ? (
        <div className="mt-1 flex-1 min-h-0 flex flex-col border-t border-white/[0.06] pt-2.5 px-2.5">
          {/* Header Row */}
          <div className="flex shrink-0 items-center justify-between gap-1 px-1.5 mb-2">
            <div className="flex items-center gap-1.5 min-w-0">
              <span className="text-[11px] font-semibold uppercase tracking-wider text-zinc-400 truncate">
                Your Library
              </span>
              <span className="rounded-full bg-white/[0.06] px-1.5 py-0.5 text-[10px] font-mono text-zinc-400 tabular-nums">
                {filteredItems.length}
              </span>
            </div>

            <div className="flex items-center gap-0.5 shrink-0">
              <button
                type="button"
                onClick={() => {
                  setSearchOpen((prev) => {
                    if (prev) setSearchQuery("");
                    return !prev;
                  });
                }}
                title="Filter playlists & albums"
                aria-label="Filter playlists & albums"
                className={cn(
                  "rounded-md p-1 transition-colors cursor-pointer",
                  searchOpen || searchQuery
                    ? "bg-emerald-500/20 text-emerald-300"
                    : "text-zinc-400 hover:bg-white/[0.08] hover:text-white"
                )}
              >
                <Search className="h-3.5 w-3.5" />
              </button>

              <button
                type="button"
                onClick={() => setSortBy((s) => NEXT_SORT[s])}
                title={SORT_LABELS[sortBy]}
                aria-label={SORT_LABELS[sortBy]}
                className={cn(
                  "rounded-md p-1 transition-colors cursor-pointer",
                  sortBy !== "recent"
                    ? "bg-emerald-500/15 text-emerald-300"
                    : "text-zinc-400 hover:bg-white/[0.08] hover:text-white"
                )}
              >
                <ArrowUpDown className="h-3.5 w-3.5" />
              </button>

              <button
                type="button"
                onClick={() => {
                  navigate("/playlists");
                  if (isMobile) setMobileNavOpen(false);
                }}
                title="Save new Spotify playlist"
                aria-label="Save new Spotify playlist"
                className="rounded-md p-1 text-zinc-400 hover:bg-white/[0.08] hover:text-white transition-colors cursor-pointer"
              >
                <Plus className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>

          {/* Inline Search Input */}
          {searchOpen && (
            <div className="shrink-0 px-1 mb-2">
              <div className="relative flex items-center">
                <Search className="pointer-events-none absolute left-2 h-3 w-3 text-zinc-500" />
                <input
                  type="text"
                  autoFocus
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="Filter playlists & albums..."
                  className="h-7 w-full rounded-lg border border-white/10 bg-black/35 pl-7 pr-7 text-[11px] text-zinc-100 placeholder:text-zinc-500 focus:border-emerald-500/50 focus:outline-none"
                />
                {searchQuery && (
                  <button
                    type="button"
                    onClick={() => setSearchQuery("")}
                    aria-label="Clear filter"
                    className="absolute right-1.5 rounded p-0.5 text-zinc-400 hover:text-white cursor-pointer"
                  >
                    <X className="h-3 w-3" />
                  </button>
                )}
              </div>
            </div>
          )}

          {/* Filter Pills */}
          <div className="flex shrink-0 items-center gap-1 px-1 mb-2 overflow-x-auto no-scrollbar">
            {(
              [
                ["all", "All", counts.all],
                ["playlists", "Playlists", counts.playlists],
                ["saved", "Saved", counts.saved],
                ["albums", "Albums", counts.albums],
              ] as Array<[SidebarFilter, string, number]>
            ).map(([key, label, count]) => {
              const active = filter === key;
              return (
                <button
                  key={key}
                  type="button"
                  onClick={() => setFilter(key)}
                  title={`${label} (${count})`}
                  className={cn(
                    "shrink-0 rounded-full px-2 py-0.5 text-[10px] font-medium transition-colors cursor-pointer border",
                    active
                      ? "bg-emerald-500/20 text-emerald-300 border-emerald-500/35"
                      : "bg-white/[0.04] text-zinc-400 border-white/[0.06] hover:text-zinc-200 hover:bg-white/[0.07]"
                  )}
                >
                  {label}
                </button>
              );
            })}
          </div>

          {/* Scrollable Collections List */}
          <div className="flex-1 min-h-0 overflow-y-auto space-y-1 pr-0.5 pb-4">
            {allItems.length === 0 && libraryLoading ? (
              <div className="space-y-1.5 px-1">
                {Array.from({ length: 5 }).map((_, idx) => (
                  <div
                    key={idx}
                    className="flex items-center gap-2.5 rounded-xl px-2 py-1.5"
                  >
                    <div className="h-9 w-9 shrink-0 rounded-lg bg-white/[0.06] animate-pulse" />
                    <div className="flex-1 space-y-1.5 min-w-0">
                      <div className="h-3 w-3/4 rounded bg-white/[0.06] animate-pulse" />
                      <div className="h-2.5 w-1/2 rounded bg-white/[0.04] animate-pulse" />
                    </div>
                  </div>
                ))}
              </div>
            ) : allItems.length === 0 && libraryError ? (
              <div className="rounded-xl border border-dashed border-white/[0.08] px-3 py-4 text-center space-y-2">
                <p className="text-xs text-zinc-400">Could not load library</p>
                <button
                  type="button"
                  onClick={retrySidebarLibrary}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-white/[0.06] hover:bg-white/[0.12] border border-white/10 px-2.5 py-1 text-[11px] font-medium text-zinc-200 transition-colors cursor-pointer"
                >
                  <RefreshCw className="h-3 w-3" />
                  Retry
                </button>
              </div>
            ) : filteredItems.length === 0 ? (
              <div className="rounded-xl border border-dashed border-white/[0.07] px-3 py-4 text-center text-xs text-zinc-500">
                {searchQuery
                  ? `No matches for "${searchQuery}"`
                  : "Save a Spotify playlist or download an album to see it here."}
              </div>
            ) : (
              filteredItems.map((item) => (
                <SidebarCollectionRow
                  key={item.key}
                  item={item}
                  isActive={isItemActive(item)}
                  isLoadingPlay={playingKey === item.key}
                  onSelect={() => handleSelectItem(item, isMobile)}
                  onQuickPlay={(e) => void handleQuickPlay(item, e)}
                />
              ))
            )}
          </div>
        </div>
      ) : (
        /* Collapsed Mode Cover-Art Shortcut Strip */
        <div className="mt-1 flex-1 min-h-0 flex flex-col items-center border-t border-white/[0.06] py-2 px-2 overflow-y-auto gap-2">
          {allItems.map((item) => (
            <CollapsedCollectionThumb
              key={item.key}
              item={item}
              isActive={isItemActive(item)}
              onSelect={() => handleSelectItem(item, isMobile)}
            />
          ))}
        </div>
      )}

      {/* Footer Status Strip */}
      <div className="shrink-0 border-t border-white/[0.06] p-3 space-y-2">
        {!isCompact && activeToolProgress && (
          <div className="rounded-lg bg-emerald-500/10 border border-emerald-500/20 px-2.5 py-1.5">
            <div className="flex items-center justify-between text-[10px] font-medium text-emerald-300">
              <span className="truncate">{activeToolProgress.tool}</span>
              <span className="font-mono tabular-nums">
                {Math.round(activeToolProgress.percent)}%
              </span>
            </div>
            <div className="mt-1 h-1 w-full overflow-hidden rounded-full bg-black/40">
              <div
                className="h-full rounded-full bg-emerald-bright transition-all duration-300"
                style={{
                  width: `${Math.max(4, Math.min(100, activeToolProgress.percent))}%`,
                }}
              />
            </div>
          </div>
        )}

        {!isCompact && libraryStats && (
          <button
            type="button"
            onClick={() => {
              navigate("/library");
              if (isMobile) setMobileNavOpen(false);
            }}
            className="flex w-full items-center justify-between gap-2 rounded-lg bg-white/[0.03] hover:bg-white/[0.06] border border-white/[0.05] px-2.5 py-1.5 text-[11px] text-zinc-400 hover:text-zinc-200 transition-colors cursor-pointer"
            title="Open Offline Library"
          >
            <span className="inline-flex items-center gap-1.5 truncate">
              <HardDrive className="h-3 w-3 shrink-0 text-emerald-400" />
              <span className="font-mono tabular-nums">
                {libraryStats.total_tracks.toLocaleString()} songs
              </span>
            </span>
            <span className="font-mono tabular-nums text-zinc-300 shrink-0">
              {libraryStats.size_str}
            </span>
          </button>
        )}

        <div
          className={cn(
            "flex items-center gap-2 text-xs text-zinc-400",
            isCompact ? "justify-center" : "justify-between"
          )}
          title={`WebSocket: ${wsStatus} | Engine: ${engineLabel}`}
        >
          <div className="flex items-center gap-2 min-w-0">
            <span
              className={cn(
                "h-2 w-2 shrink-0 rounded-full",
                wsStatus === "connected"
                  ? "bg-emerald-bright shadow-[0_0_8px_rgba(30,215,96,0.85)]"
                  : wsStatus === "connecting"
                    ? "bg-amber-400 animate-pulse"
                    : "bg-red-400"
              )}
            />
            {!isCompact && (
              <span className="truncate text-[11px]">
                {wsStatus === "connected"
                  ? "Live"
                  : wsStatus === "connecting"
                    ? "Connecting"
                    : "Offline"}
              </span>
            )}
          </div>

          {!isCompact && (
            <span className="inline-flex items-center gap-1 rounded-md bg-white/[0.05] px-2 py-0.5 text-[10px] font-medium text-zinc-300 border border-white/[0.06]">
              <Cpu className="h-3 w-3 text-emerald-400" />
              {engineLabel}
            </span>
          )}
        </div>
      </div>
    </div>
  );

  return (
    <>
      {/* Desktop Collapsible Sidebar */}
      <aside
        className={cn(
          "hidden lg:block shrink-0 transition-[width] duration-200 ease-out h-full z-20",
          collapsed ? "w-[72px]" : "w-[268px]"
        )}
      >
        {renderSidebarContent(collapsed, false)}
      </aside>

      {/* Mobile Drawer */}
      <AnimatePresence>
        {mobileOpen && (
          <div className="fixed inset-0 z-50 lg:hidden flex">
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setMobileNavOpen(false)}
              className="fixed inset-0 bg-black/70 backdrop-blur-sm"
            />
            <motion.div
              initial={{ x: -280 }}
              animate={{ x: 0 }}
              exit={{ x: -280 }}
              transition={{ type: "spring", stiffness: 360, damping: 34 }}
              className="relative z-10 w-[280px] max-w-[85vw] h-full"
            >
              {renderSidebarContent(false, true)}
            </motion.div>
          </div>
        )}
      </AnimatePresence>
    </>
  );
}
