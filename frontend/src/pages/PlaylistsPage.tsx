import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import {
  CheckCircle2,
  ClipboardPaste,
  Info,
  KeyRound,
  Link2,
  ListMusic,
  Play,
  Plus,
  RefreshCw,
  Search,
  X,
} from "lucide-react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { api } from "@/api/endpoints";
import type { SavedPlaylist } from "@/api/types";
import { EditPlaylistModal } from "@/components/playlists/EditPlaylistModal";
import {
  ExportM3u8Modal,
  type ExportM3u8Target,
} from "@/components/playlists/ExportM3u8Modal";
import {
  ExportSongsModal,
  type ExportSongsTarget,
} from "@/components/playlists/ExportSongsModal";
import { PlaylistCard } from "@/components/playlists/PlaylistCard";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { useAppStore } from "@/stores/appStore";

interface ScheduleOption {
  key: string;
  label: string;
  on_startup: boolean;
  interval_hours: number;
}

const SCHEDULE_OPTIONS: ScheduleOption[] = [
  { key: "6h", label: "Watch Sync: Every 6h", on_startup: true, interval_hours: 6 },
  { key: "1h", label: "Watch Sync: Every 1h", on_startup: true, interval_hours: 1 },
  { key: "3h", label: "Watch Sync: Every 3h", on_startup: true, interval_hours: 3 },
  { key: "12h", label: "Watch Sync: Every 12h", on_startup: true, interval_hours: 12 },
  { key: "24h", label: "Watch Sync: Every 24h", on_startup: true, interval_hours: 24 },
  { key: "startup", label: "Watch Sync: Startup Only", on_startup: true, interval_hours: 0 },
  { key: "manual", label: "Watch Sync: Manual Only", on_startup: false, interval_hours: 0 },
];

export function PlaylistsPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const playlistSyncProgress = useAppStore((s) => s.playlistSyncProgress);

  const [urlInput, setUrlInput] = useState("");
  const [savingUrl, setSavingUrl] = useState(false);
  const [syncingAll, setSyncingAll] = useState(false);
  const [runningAutoSync, setRunningAutoSync] = useState(false);
  const [syncingIds, setSyncingIds] = useState<Set<string>>(new Set());
  const [searchQuery, setSearchQuery] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");

  const [editingPlaylist, setEditingPlaylist] = useState<SavedPlaylist | null>(null);
  const [deletingPlaylist, setDeletingPlaylist] = useState<SavedPlaylist | null>(null);
  const [exportM3u8Target, setExportM3u8Target] = useState<ExportM3u8Target | null>(null);
  const [exportSongsTarget, setExportSongsTarget] = useState<ExportSongsTarget | null>(null);
  const [authorizingSpotify, setAuthorizingSpotify] = useState(false);

  useEffect(() => {
    const t = window.setTimeout(() => setDebouncedSearch(searchQuery.trim()), 150);
    return () => window.clearTimeout(t);
  }, [searchQuery]);

  const { data, isLoading } = useQuery({
    queryKey: ["playlists", debouncedSearch],
    queryFn: () => api.playlists.list(debouncedSearch),
  });

  const playlists = data?.playlists ?? [];
  const summary = data?.summary;
  const schedule = data?.auto_sync_schedule;
  const spStatus = data?.spotify_status;

  const selectedScheduleKey = (() => {
    if (!schedule) return "6h";
    if (!schedule.on_startup && schedule.interval_hours === 0) return "manual";
    if (schedule.interval_hours === 0) return "startup";
    const found = SCHEDULE_OPTIONS.find((o) => o.interval_hours === schedule.interval_hours);
    return found ? found.key : "6h";
  })();

  const handleSavePlaylist = async (e: React.FormEvent) => {
    e.preventDefault();
    const cleaned = urlInput.trim();
    if (!cleaned || savingUrl) return;
    setSavingUrl(true);
    try {
      const res = await api.playlists.save(cleaned);
      setUrlInput("");
      void queryClient.invalidateQueries({ queryKey: ["playlists"] });

      if (res.was_truncated) {
        const ownerSuffix = res.owner_name ? ` (Owned by ${res.owner_name})` : "";
        toast.warning("Saved 100 Tracks (Spotify Guest Limit)", {
          description: res.api_error
            ? `${res.api_error}${ownerSuffix}`
            : `In Guest mode Spotify limits playlist embeds to 100 songs. Add Spotify keys in Settings to fetch full playlists.`,
          duration: 8500,
        });
      } else {
        toast.success(`Saved "${res.playlist.name}"`, {
          description: `${res.playlist.total_tracks} tracks stored for offline batch downloads.`,
        });
      }
    } catch (err) {
      toast.error("Could not save playlist", {
        description: err instanceof Error ? err.message : undefined,
      });
    } finally {
      setSavingUrl(false);
    }
  };

  const handleSyncAll = async () => {
    if (syncingAll) return;
    setSyncingAll(true);
    try {
      const res = await api.playlists.syncAll();
      void queryClient.invalidateQueries({ queryKey: ["playlists"] });
      toast.success(`Synced ${res.checked_count} playlist(s)`, {
        description: `${res.total_added} added, ${res.total_removed} removed${
          res.errors.length > 0 ? ` (${res.errors.length} warning)` : ""
        }`,
      });
    } catch (err) {
      toast.error("Sync All failed", {
        description: err instanceof Error ? err.message : undefined,
      });
    } finally {
      setSyncingAll(false);
    }
  };

  const handleRunAutoSync = async () => {
    if (runningAutoSync) return;
    setRunningAutoSync(true);
    try {
      const res = await api.playlists.runAutoSync();
      void queryClient.invalidateQueries({ queryKey: ["playlists"] });
      void queryClient.invalidateQueries({ queryKey: ["queue"] });
      if (res.already_running) {
        toast.info("Auto-Sync check is already running in background");
      } else {
        toast.success("Watched Auto-Sync Finished", {
          description: `Checked ${res.checked_count} pinned playlist(s), queued ${res.queued_count} new song(s).`,
        });
      }
    } catch (err) {
      toast.error("Auto-Sync failed", {
        description: err instanceof Error ? err.message : undefined,
      });
    } finally {
      setRunningAutoSync(false);
    }
  };

  const handleScheduleChange = async (key: string) => {
    const opt = SCHEDULE_OPTIONS.find((o) => o.key === key);
    if (!opt) return;
    try {
      await api.playlists.updateAutoSyncSchedule({
        on_startup: opt.on_startup,
        interval_hours: opt.interval_hours,
      });
      void queryClient.invalidateQueries({ queryKey: ["playlists"] });
      toast.success(`Updated: ${opt.label}`);
    } catch (err) {
      toast.error("Could not update Auto-Sync schedule", {
        description: err instanceof Error ? err.message : undefined,
      });
    }
  };

  const handleSyncOne = async (pl: SavedPlaylist) => {
    setSyncingIds((prev) => new Set(prev).add(pl.id));
    try {
      const res = await api.playlists.sync(pl.id, true);
      void queryClient.invalidateQueries({ queryKey: ["playlists"] });
      if (res.liked_songs_tip) {
        toast.info("Liked Songs Tip", {
          description:
            "Make sure this playlist uses your Spotify collection/tracks link for automatic Liked Songs syncing.",
        });
      } else {
        toast.success(`Synced "${pl.name}"`, {
          description: `${res.added} added, ${res.removed} removed (${res.queued_count} auto-queued).`,
        });
      }
    } catch (err) {
      toast.error(`Sync failed for "${pl.name}"`, {
        description: err instanceof Error ? err.message : undefined,
      });
    } finally {
      setSyncingIds((prev) => {
        const next = new Set(prev);
        next.delete(pl.id);
        return next;
      });
    }
  };

  const handleToggleWatch = async (pl: SavedPlaylist) => {
    try {
      const nextState = !pl.auto_sync;
      await api.playlists.toggleAutoSync(pl.id, nextState);
      void queryClient.invalidateQueries({ queryKey: ["playlists"] });
      toast.success(
        nextState
          ? `Pinned "${pl.name}" for Auto-Sync`
          : `Unpinned "${pl.name}" from Auto-Sync`
      );
    } catch (err) {
      toast.error("Failed to toggle Auto-Sync", {
        description: err instanceof Error ? err.message : undefined,
      });
    }
  };

  const handleConfirmDelete = async () => {
    if (!deletingPlaylist) return;
    try {
      await api.playlists.delete(deletingPlaylist.id);
      void queryClient.invalidateQueries({ queryKey: ["playlists"] });
      toast.info(`Removed "${deletingPlaylist.name}" from Saved Playlists`);
      setDeletingPlaylist(null);
    } catch (err) {
      toast.error("Could not delete playlist", {
        description: err instanceof Error ? err.message : undefined,
      });
    }
  };

  const handleBannerAction = async () => {
    if (!spStatus || spStatus.mode === "guest") {
      navigate("/settings");
      return;
    }
    setAuthorizingSpotify(true);
    toast.info("Opening Spotify Login", {
      description: "Approve access in the browser window to unlock full playlists.",
    });
    try {
      const res = await api.settings.authorizeSpotify();
      void queryClient.invalidateQueries({ queryKey: ["playlists"] });
      if (res.success) {
        toast.success("Spotify Authorized", { description: res.message });
      } else {
        toast.error("Spotify Authorization Failed", { description: res.message });
      }
    } catch (err) {
      toast.error("Authorization error", {
        description: err instanceof Error ? err.message : undefined,
      });
    } finally {
      setAuthorizingSpotify(false);
    }
  };

  return (
    <div className="space-y-5">
      {/* 1. Ingestion & Sync Toolbar */}
      <form
        onSubmit={handleSavePlaylist}
        className="glass-panel rounded-2xl p-4 flex flex-col xl:flex-row gap-3 items-stretch xl:items-center"
      >
        <div className="relative flex-1">
          <Input
            value={urlInput}
            onChange={(e) => setUrlInput(e.target.value)}
            leadingIcon={<Link2 className="h-4 w-4" />}
            placeholder="Paste Spotify playlist / album / Liked Songs URL to save offline..."
            trailingSlot={
              <button
                type="button"
                onClick={async () => {
                  try {
                    const txt = (await navigator.clipboard.readText()).trim();
                    if (txt) setUrlInput(txt);
                  } catch {
                    toast.error("Clipboard access denied");
                  }
                }}
                className="rounded-lg p-1.5 text-zinc-400 hover:bg-white/10 hover:text-white cursor-pointer"
                title="Paste from Clipboard"
              >
                <ClipboardPaste className="h-4 w-4" />
              </button>
            }
          />
        </div>

        <div className="flex flex-wrap items-center gap-2 shrink-0">
          <Button type="submit" disabled={savingUrl || !urlInput.trim()}>
            <Plus className="h-4 w-4" />
            {savingUrl ? "Saving..." : "Save Playlist"}
          </Button>

          <Button
            type="button"
            variant="secondary"
            disabled={syncingAll || playlists.length === 0}
            onClick={() => void handleSyncAll()}
          >
            <RefreshCw className={cn("h-4 w-4", syncingAll && "animate-spin")} />
            {syncingAll ? "Syncing All..." : "Sync All"}
          </Button>

          <select
            value={selectedScheduleKey}
            onChange={(e) => void handleScheduleChange(e.target.value)}
            aria-label="Auto-Sync Schedule"
            className="h-9 rounded-lg border border-white/10 bg-elevated px-3 text-xs font-medium text-zinc-200 focus:border-emerald-500/60 focus:outline-none cursor-pointer"
          >
            {SCHEDULE_OPTIONS.map((opt) => (
              <option key={opt.key} value={opt.key}>
                {opt.label}
              </option>
            ))}
          </select>

          <Button
            type="button"
            variant="outline"
            disabled={runningAutoSync}
            onClick={() => void handleRunAutoSync()}
            title="Run Auto-Sync check across pinned playlists now"
          >
            <Play className="h-3.5 w-3.5" />
            Run Watch Sync
          </Button>
        </div>
      </form>

      {/* 2. Spotify API Status Banner */}
      {spStatus && (
        <div
          className={cn(
            "rounded-2xl border px-4 py-2.5 flex flex-col sm:flex-row sm:items-center justify-between gap-2 text-xs",
            spStatus.mode === "connected"
              ? "border-emerald-500/30 bg-emerald-500/[0.07] text-emerald-200"
              : spStatus.mode === "keys_only"
                ? "border-sky-500/30 bg-sky-500/[0.07] text-sky-200"
                : "border-amber-500/30 bg-amber-500/[0.07] text-amber-200"
          )}
        >
          <div className="flex items-center gap-2.5">
            {spStatus.mode === "connected" ? (
              <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-400" />
            ) : spStatus.mode === "keys_only" ? (
              <KeyRound className="h-4 w-4 shrink-0 text-sky-400" />
            ) : (
              <Info className="h-4 w-4 shrink-0 text-amber-400" />
            )}
            <span>
              {spStatus.mode === "connected"
                ? `Spotify API Connected${
                    spStatus.user_name ? ` as @${spStatus.user_name}` : ""
                  }: Full pagination unlocked for your playlists.`
                : spStatus.mode === "keys_only"
                  ? "Spotify API Keys Set — Account authorization recommended to fetch playlists > 100 tracks."
                  : "Guest Mode Active (Capped at 100 tracks/playlist). Add free Spotify API keys in Settings for full 1,000+ track playlists."}
            </span>
          </div>

          <Button
            type="button"
            size="sm"
            variant="secondary"
            disabled={authorizingSpotify}
            onClick={() => void handleBannerAction()}
            className="shrink-0"
          >
            {spStatus.mode === "connected"
              ? "Switch Account"
              : spStatus.mode === "keys_only"
                ? authorizingSpotify
                  ? "Authorizing..."
                  : "Authorize Spotify Account"
                : "Configure Free API Keys"}
          </Button>
        </div>
      )}

      {/* 3. KPI Summary Strip + Filter */}
      <div className="flex flex-col lg:flex-row gap-3 items-stretch lg:items-center justify-between">
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5 flex-1">
          {[
            { label: "Saved Playlists", value: summary?.total_playlists ?? 0 },
            { label: "Total Tracks", value: summary?.total_tracks ?? 0 },
            { label: "Downloaded", value: summary?.downloaded_count ?? 0 },
            { label: "Pending", value: summary?.pending_count ?? 0 },
          ].map((stat) => (
            <div key={stat.label} className="glass-panel rounded-xl px-4 py-2.5">
              <div className="text-[10px] font-semibold uppercase tracking-wider text-zinc-400">
                {stat.label}
              </div>
              {isLoading ? (
                <Skeleton className="h-6 w-12 mt-1" />
              ) : (
                <div className="text-xl font-semibold font-mono tabular-nums text-white mt-0.5">
                  {stat.value}
                </div>
              )}
            </div>
          ))}
        </div>

        <div className="w-full lg:w-72 shrink-0">
          <Input
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            leadingIcon={<Search className="h-4 w-4" />}
            placeholder="Search saved playlists..."
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
      </div>

      {/* 4. Playlist Cards List */}
      {isLoading ? (
        <div className="space-y-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-24 rounded-2xl" />
          ))}
        </div>
      ) : playlists.length === 0 ? (
        <div className="glass-panel rounded-2xl p-12 text-center space-y-2 border border-dashed border-white/[0.12]">
          <ListMusic className="h-8 w-8 mx-auto text-emerald-400/80" />
          <h2 className="text-base font-semibold text-white">
            {debouncedSearch
              ? "No saved playlists match your search"
              : "No saved playlists yet"}
          </h2>
          <p className="text-sm text-zinc-400 max-w-md mx-auto">
            Paste a Spotify playlist, album, or Liked Songs URL above to store its
            tracks offline and download them in smart quota-safe batches.
          </p>
        </div>
      ) : (
        <div className="space-y-2.5">
          {playlists.map((pl) => (
            <PlaylistCard
              key={pl.id}
              playlist={pl}
              syncing={syncingIds.has(pl.id) || syncingAll}
              syncProgress={playlistSyncProgress[pl.id]}
              onOpen={(item) => navigate(`/playlists/${item.id}`)}
              onToggleWatch={(item) => void handleToggleWatch(item)}
              onSync={(item) => void handleSyncOne(item)}
              onEdit={(item) => setEditingPlaylist(item)}
              onCopyLink={(item) => {
                if (!item.spotify_url) {
                  toast.info("No link recorded for this playlist");
                  return;
                }
                void navigator.clipboard
                  .writeText(item.spotify_url)
                  .then(() => toast.success("Copied Spotify link"));
              }}
              onExportM3u8={(item) =>
                setExportM3u8Target({
                  playlistId: item.id,
                  playlistName: item.name,
                })
              }
              onExportSongs={(item) =>
                setExportSongsTarget({
                  playlistId: item.id,
                  playlistName: item.name,
                  trackCountHint: item.downloaded_count,
                })
              }
              onDelete={(item) => setDeletingPlaylist(item)}
            />
          ))}
        </div>
      )}

      {/* Modals */}
      <EditPlaylistModal
        playlist={editingPlaylist}
        onClose={() => setEditingPlaylist(null)}
      />

      <ExportM3u8Modal
        target={exportM3u8Target}
        onClose={() => setExportM3u8Target(null)}
      />

      <ExportSongsModal
        target={exportSongsTarget}
        onClose={() => setExportSongsTarget(null)}
      />

      {/* Delete Confirmation Modal */}
      <AnimatePresence>
        {deletingPlaylist && (
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setDeletingPlaylist(null)}
              className="fixed inset-0 bg-black/75 backdrop-blur-sm"
            />
            <motion.div
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.95 }}
              className="relative z-10 w-full max-w-md rounded-2xl glass-panel p-6 shadow-2xl space-y-4"
            >
              <h2 className="text-base font-semibold text-white">
                Remove Saved Playlist?
              </h2>
              <p className="text-xs text-zinc-400 leading-relaxed">
                Remove{" "}
                <strong className="text-zinc-200">
                  {deletingPlaylist.name}
                </strong>{" "}
                from Saved Playlists? Audio files already downloaded to disk will
                remain safely in your Library.
              </p>
              <div className="flex justify-end gap-2 pt-2 border-t border-white/[0.06]">
                <Button
                  type="button"
                  variant="ghost"
                  onClick={() => setDeletingPlaylist(null)}
                >
                  Cancel
                </Button>
                <Button
                  type="button"
                  variant="destructive"
                  onClick={() => void handleConfirmDelete()}
                >
                  Remove Playlist
                </Button>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>
    </div>
  );
}
