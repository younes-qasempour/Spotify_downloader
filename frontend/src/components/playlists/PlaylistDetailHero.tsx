import { useEffect } from "react";
import {
  ArrowLeft,
  Disc3,
  FileMusic,
  FolderOpen,
  FolderOutput,
  Pencil,
  Pin,
  RefreshCw,
} from "lucide-react";
import { apiUrl } from "@/api/client";
import type { SavedPlaylist } from "@/api/types";
import { Button } from "@/components/ui/button";
import { extractAmbientColor } from "@/lib/colorExtract";
import { cn } from "@/lib/utils";
import { useAppStore, type PlaylistSyncProgress } from "@/stores/appStore";
import { usePlayerStore } from "@/stores/playerStore";

interface PlaylistDetailHeroProps {
  playlist: SavedPlaylist;
  syncing: boolean;
  syncProgress?: PlaylistSyncProgress;
  onBack: () => void;
  onToggleWatch: () => void;
  onSync: () => void;
  onEdit: () => void;
  onOpenFolder: () => void;
  onExportM3u8: () => void;
  onExportSongs: () => void;
}

export function PlaylistDetailHero({
  playlist,
  syncing,
  syncProgress,
  onBack,
  onToggleWatch,
  onSync,
  onEdit,
  onOpenFolder,
  onExportM3u8,
  onExportSongs,
}: PlaylistDetailHeroProps) {
  const setAmbientColor = useAppStore((s) => s.setAmbientColor);
  const resetAmbientColor = useAppStore((s) => s.resetAmbientColor);
  const activePlayerTrack = usePlayerStore((s) => s.currentTrack);

  const coverSrc = playlist.local_cover
    ? apiUrl(
        `/api/media/cover/collection?name=${encodeURIComponent(playlist.name)}`
      )
    : playlist.cover_url || "";

  useEffect(() => {
    if (!coverSrc || activePlayerTrack) return;
    let cancelled = false;
    void extractAmbientColor(coverSrc).then((rgb) => {
      if (!cancelled && rgb) setAmbientColor(rgb);
    });
    return () => {
      cancelled = true;
      if (!usePlayerStore.getState().currentTrack) {
        resetAmbientColor();
      }
    };
  }, [activePlayerTrack, coverSrc, resetAmbientColor, setAmbientColor]);

  const pct = Math.min(100, Math.max(0, playlist.progress_percent || 0));

  return (
    <div className="relative overflow-hidden rounded-2xl glass-panel p-5 sm:p-6">
      {/* Blurred Ambient Art Backdrop */}
      {coverSrc && (
        <img
          src={coverSrc}
          alt=""
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 h-full w-full scale-125 object-cover opacity-25 blur-2xl"
        />
      )}
      <div className="pointer-events-none absolute inset-0 bg-gradient-to-b from-black/35 via-panel/80 to-panel/95" />

      <div className="relative z-10 space-y-4">
        <div className="flex items-center justify-between gap-3">
          <Button type="button" variant="secondary" size="sm" onClick={onBack}>
            <ArrowLeft className="h-3.5 w-3.5" />
            Back to Playlists
          </Button>

          {playlist.last_synced_at && (
            <span className="text-[11px] font-mono text-zinc-400">
              Last synced: {playlist.last_synced_at}
            </span>
          )}
        </div>

        <div className="flex flex-col sm:flex-row sm:items-center gap-4">
          <div className="h-24 w-24 shrink-0 overflow-hidden rounded-2xl bg-elevated border border-white/15 shadow-2xl">
            {coverSrc ? (
              <img
                src={coverSrc}
                alt={playlist.name}
                className="h-full w-full object-cover"
              />
            ) : (
              <div className="flex h-full w-full items-center justify-center text-zinc-500">
                <Disc3 className="h-9 w-9" />
              </div>
            )}
          </div>

          <div className="min-w-0 flex-1 space-y-2">
            <h2 className="text-xl sm:text-2xl font-bold tracking-tight text-white truncate">
              {playlist.name}
            </h2>

            <div className="flex flex-wrap items-center gap-2.5 text-xs font-mono tabular-nums text-zinc-300">
              <span>{playlist.total_tracks} Total</span>
              <span className="text-zinc-500">·</span>
              <span className="text-emerald-300">
                {playlist.downloaded_count} Downloaded
              </span>
              <span className="text-zinc-500">·</span>
              <span className="text-sky-300">
                {playlist.pending_count} Pending
              </span>
              <span className="text-zinc-400">({pct.toFixed(1)}%)</span>
            </div>

            <div className="h-1.5 w-full max-w-md overflow-hidden rounded-full bg-white/12">
              <div
                className="h-full rounded-full bg-gradient-to-r from-emerald-brand to-emerald-bright transition-all duration-300"
                style={{ width: `${pct}%` }}
              />
            </div>
          </div>
        </div>

        {/* Action Toolbar */}
        <div className="flex flex-wrap items-center gap-2 pt-1">
          <Button
            type="button"
            size="sm"
            variant={playlist.auto_sync ? "default" : "secondary"}
            onClick={onToggleWatch}
            className={cn(
              playlist.auto_sync &&
                "bg-emerald-500/20 text-emerald-300 border border-emerald-500/50 hover:bg-emerald-500/30 shadow-none"
            )}
          >
            <Pin className="h-3.5 w-3.5" />
            <span>Auto-Sync: {playlist.auto_sync ? "On" : "Off"}</span>
          </Button>

          <Button
            type="button"
            size="sm"
            variant="secondary"
            disabled={syncing}
            onClick={onSync}
          >
            <RefreshCw className={cn("h-3.5 w-3.5", syncing && "animate-spin")} />
            <span>
              {syncing && syncProgress && syncProgress.total > 0
                ? `Syncing ${syncProgress.current}/${syncProgress.total}`
                : syncing
                  ? "Syncing..."
                  : "Sync"}
            </span>
          </Button>

          <Button type="button" size="sm" variant="secondary" onClick={onEdit}>
            <Pencil className="h-3.5 w-3.5" />
            Edit
          </Button>

          <Button
            type="button"
            size="sm"
            variant="secondary"
            onClick={onOpenFolder}
          >
            <FolderOpen className="h-3.5 w-3.5" />
            Open Folder
          </Button>

          <Button
            type="button"
            size="sm"
            variant="secondary"
            onClick={onExportM3u8}
          >
            <FileMusic className="h-3.5 w-3.5" />
            Export M3U8
          </Button>

          <Button
            type="button"
            size="sm"
            variant="secondary"
            onClick={onExportSongs}
          >
            <FolderOutput className="h-3.5 w-3.5" />
            Export Songs
          </Button>
        </div>
      </div>
    </div>
  );
}
