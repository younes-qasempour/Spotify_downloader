import { useState } from "react";
import {
  Disc3,
  FileMusic,
  Folder,
  FolderOpen,
  FolderOutput,
  MoreHorizontal,
  Music,
  Pencil,
} from "lucide-react";
import { apiUrl } from "@/api/client";
import type { LibraryCollection } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

interface CollectionCardProps {
  collection: LibraryCollection;
  type: "playlist" | "album";
  onBrowse: (coll: LibraryCollection) => void;
  onRename?: (coll: LibraryCollection) => void;
  onOpenFolder: (coll: LibraryCollection) => void;
  onExportSongs: (coll: LibraryCollection) => void;
  onExportM3u8: (coll: LibraryCollection) => void;
}

export function CollectionCard({
  collection,
  type,
  onBrowse,
  onRename,
  onOpenFolder,
  onExportSongs,
  onExportM3u8,
}: CollectionCardProps) {
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <div
      onClick={() => onBrowse(collection)}
      className="group glass-panel rounded-2xl p-3.5 sm:px-4 sm:py-3.5 flex flex-col md:flex-row md:items-center gap-3.5 hover:border-white/20 hover:bg-white/[0.05] transition-all cursor-pointer"
    >
      <div className="flex items-center gap-3.5 min-w-0 flex-1">
        <div className="relative h-14 w-14 shrink-0 overflow-hidden rounded-xl bg-elevated border border-white/10 flex items-center justify-center text-zinc-500">
          {type === "album" ? (
            <Disc3 className="h-6 w-6 text-zinc-500" />
          ) : (
            <Folder className="h-6 w-6 text-zinc-500" />
          )}
          <img
            src={apiUrl(collection.cover_url_local)}
            alt={collection.name}
            loading="lazy"
            className="absolute inset-0 h-full w-full object-cover group-hover:scale-105 transition-transform duration-300"
            onError={(e) => {
              e.currentTarget.style.display = "none";
            }}
          />
        </div>

        <div className="min-w-0 flex-1 space-y-1">
          <div className="flex items-center gap-2 flex-wrap">
            <h3 className="truncate text-sm sm:text-base font-semibold text-white">
              {collection.name}
            </h3>
            {collection.genre && (
              <Badge variant="emerald">{collection.genre}</Badge>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-2 text-xs text-zinc-400">
            {type === "album" && collection.artist && (
              <>
                <span className="text-zinc-200 font-medium">
                  by {collection.artist}
                </span>
                <span>·</span>
              </>
            )}
            <span className="font-mono tabular-nums">
              {collection.track_count} song{collection.track_count === 1 ? "" : "s"}
            </span>
            <span>·</span>
            <span className="font-mono tabular-nums text-zinc-300">
              {collection.size_str}
            </span>
          </div>

          {collection.folder_path && (
            <div className="truncate text-[11px] font-mono text-zinc-500">
              {collection.folder_path}
            </div>
          )}
        </div>
      </div>

      <div
        className="flex flex-wrap items-center gap-1.5 shrink-0"
        onClick={(e) => e.stopPropagation()}
      >
        <Button
          type="button"
          size="sm"
          variant="secondary"
          onClick={() => onBrowse(collection)}
        >
          <Music className="h-3.5 w-3.5" />
          Browse Tracks
        </Button>

        {onRename && type === "playlist" && (
          <Button
            type="button"
            size="icon"
            variant="secondary"
            onClick={() => onRename(collection)}
            className="h-8 w-8"
            title="Rename playlist collection"
          >
            <Pencil className="h-3.5 w-3.5" />
          </Button>
        )}

        <Button
          type="button"
          size="sm"
          onClick={() => onOpenFolder(collection)}
        >
          <FolderOpen className="h-3.5 w-3.5" />
          Open Folder
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
            <div className="absolute right-0 top-9 z-30 w-52 rounded-xl glass-panel py-1.5 shadow-2xl border border-white/12 text-xs">
              <button
                type="button"
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => {
                  setMenuOpen(false);
                  onExportSongs(collection);
                }}
                className="flex w-full items-center gap-2 px-3 py-2 text-zinc-200 hover:bg-white/10 cursor-pointer"
              >
                <FolderOutput className="h-3.5 w-3.5 text-sky-300" />
                Export Songs to Folder...
              </button>
              <button
                type="button"
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => {
                  setMenuOpen(false);
                  onExportM3u8(collection);
                }}
                className="flex w-full items-center gap-2 px-3 py-2 text-zinc-200 hover:bg-white/10 cursor-pointer"
              >
                <FileMusic className="h-3.5 w-3.5 text-emerald-400" />
                Export Playlist (.m3u8)...
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
