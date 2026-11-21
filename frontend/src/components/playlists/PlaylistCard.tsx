import { useState } from "react";
import {
  ChevronRight,
  Copy,
  Disc3,
  FileMusic,
  FolderOutput,
  MoreHorizontal,
  Pencil,
  Pin,
  RefreshCw,
  Trash2,
} from "lucide-react";
import { apiUrl } from "@/api/client";
import type { SavedPlaylist } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { PlaylistSyncProgress } from "@/stores/appStore";

interface PlaylistCardProps {
  playlist: SavedPlaylist;
  syncing: boolean;
  syncProgress?: PlaylistSyncProgress;
  onOpen: (pl: SavedPlaylist) => void;
  onToggleWatch: (pl: SavedPlaylist) => void;
  onSync: (pl: SavedPlaylist) => void;
  onEdit: (pl: SavedPlaylist) => void;
  onCopyLink: (pl: SavedPlaylist) => void;
  onExportM3u8: (pl: SavedPlaylist) => void;
  onExportSongs: (pl: SavedPlaylist) => void;
  onDelete: (pl: SavedPlaylist) => void;
}

export function PlaylistCard({
  playlist,
  syncing,
  syncProgress,
  onOpen,
  onToggleWatch,
  onSync,
  onEdit,
  onCopyLink,
  onExportM3u8,
  onExportSongs,
  onDelete,
}: PlaylistCardProps) {
  const [menuOpen, setMenuOpen] = useState(false);

  const coverSrc = playlist.local_cover
    ? apiUrl(
        `/api/media/cover/collection?name=${encodeURIComponent(playlist.name)}`
      )
    : playlist.cover_url || "";

  const pct = Math.min(100, Math.max(0, playlist.progress_percent || 0));

  return (
    <div
      onClick={() => onOpen(playlist)}
      className="group relative glass-panel rounded-2xl p-3.5 sm:px-4 sm:py-3.5 flex flex-col md:flex-row md:items-center gap-3.5 hover:border-white/20 hover:bg-white/[0.05] transition-all cursor-pointer"
    >
      {/* Left: Cover + Metadata */}
      <div className="flex items-center gap-3.5 min-w-0 flex-1">
        <div className="h-14 w-14 shrink-0 overflow-hidden rounded-xl bg-elevated border border-white/10 shadow-md">
          {coverSrc ? (
            <img
              src={coverSrc}
              alt={playlist.name}
              loading="lazy"
              className="h-full w-full object-cover group-hover:scale-105 transition-transform duration-300"
            />
          ) : (
            <div className="flex h-full w-full items-center justify-center text-zinc-500">
              <Disc3 className="h-6 w-6" />
            </div>
          )}
        </div>

        <div className="min-w-0 flex-1 space-y-1.5">
          <div className="flex items-center gap-2 flex-wrap">
            <h3 className="truncate text-sm sm:text-base font-semibold text-white">
              {playlist.name || "Untitled Playlist"}
            </h3>
            {playlist.auto_sync && (
              <Badge variant="emerald" className="gap-1">
                <Pin className="h-3 w-3" />
                Auto-Sync
              </Badge>
            )}
            {syncing && syncProgress && syncProgress.total > 0 && (
              <Badge variant="sky" className="font-mono tabular-nums">
                Syncing {syncProgress.current}/{syncProgress.total}
              </Badge>
            )}
          </div>

          <div className="flex items-center gap-2 text-xs text-zinc-400 font-mono tabular-nums">
            <span>{playlist.total_tracks} tracks</span>
            <span>·</span>
            <span className="text-emerald-300">
              {playlist.downloaded_count} downloaded
            </span>
            <span>·</span>
            <span>{playlist.pending_count} pending</span>
            <span className="text-zinc-300">({pct.toFixed(1)}%)</span>
          </div>

          <div className="h-1.5 w-full max-w-md overflow-hidden rounded-full bg-white/[0.08]">
            <div
              className="h-full rounded-full bg-gradient-to-r from-emerald-brand to-emerald-bright transition-all duration-300"
              style={{ width: `${pct}%` }}
            />
          </div>
        </div>
      </div>

      {/* Right: Action Toolbar */}
      <div
        className="flex flex-wrap items-center gap-1.5 shrink-0"
        onClick={(e) => e.stopPropagation()}
      >
        <Button
          type="button"
          size="sm"
          onClick={() => onOpen(playlist)}
        >
          <span>Browse</span>
          <ChevronRight className="h-3.5 w-3.5" />
        </Button>

        <Button
          type="button"
          size="icon"
          variant={playlist.auto_sync ? "default" : "secondary"}
          onClick={() => onToggleWatch(playlist)}
          className={cn(
            "h-8 w-8",
            playlist.auto_sync &&
              "bg-emerald-500/20 text-emerald-300 border border-emerald-500/50 hover:bg-emerald-500/30 shadow-none"
          )}
          title={
            playlist.auto_sync
              ? "Auto-Sync ON — click to unpin"
              : "Pin playlist for scheduled Auto-Sync"
          }
        >
          <Pin className="h-3.5 w-3.5" />
        </Button>

        <Button
          type="button"
          size="icon"
          variant="secondary"
          disabled={syncing}
          onClick={() => onSync(playlist)}
          className="h-8 w-8"
          title="Sync playlist with online source"
        >
          <RefreshCw className={cn("h-3.5 w-3.5", syncing && "animate-spin")} />
        </Button>

        <Button
          type="button"
          size="icon"
          variant="secondary"
          onClick={() => onEdit(playlist)}
          className="h-8 w-8"
          title="Edit playlist details"
        >
          <Pencil className="h-3.5 w-3.5" />
        </Button>

        <Button
          type="button"
          size="icon"
          variant="secondary"
          onClick={() => onCopyLink(playlist)}
          className="h-8 w-8"
          title="Copy Spotify URL"
        >
          <Copy className="h-3.5 w-3.5" />
        </Button>

        <Button
          type="button"
          size="icon"
          variant="ghost"
          onClick={() => onDelete(playlist)}
          className="h-8 w-8 text-zinc-400 hover:text-red-300 hover:bg-red-500/15"
          title="Remove from Saved Playlists"
        >
          <Trash2 className="h-3.5 w-3.5" />
        </Button>

        <div className="relative">
          <Button
            type="button"
            size="icon"
            variant="ghost"
            onClick={() => setMenuOpen((o) => !o)}
            onBlur={() => window.setTimeout(() => setMenuOpen(false), 160)}
            className="h-8 w-8"
            title="More options"
          >
            <MoreHorizontal className="h-4 w-4" />
          </Button>

          {menuOpen && (
            <div className="absolute right-0 top-9 z-30 w-48 rounded-xl glass-panel py-1.5 shadow-2xl border border-white/12 text-xs">
              <button
                type="button"
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => {
                  setMenuOpen(false);
                  onExportM3u8(playlist);
                }}
                className="flex w-full items-center gap-2 px-3 py-2 text-zinc-200 hover:bg-white/10 cursor-pointer"
              >
                <FileMusic className="h-3.5 w-3.5 text-emerald-400" />
                Export Playlist (.m3u8)
              </button>
              <button
                type="button"
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => {
                  setMenuOpen(false);
                  onExportSongs(playlist);
                }}
                className="flex w-full items-center gap-2 px-3 py-2 text-zinc-200 hover:bg-white/10 cursor-pointer"
              >
                <FolderOutput className="h-3.5 w-3.5 text-sky-300" />
                Export Songs to Folder...
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
