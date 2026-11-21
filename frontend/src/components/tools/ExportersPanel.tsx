import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Disc3, FileMusic, FolderOutput, ListMusic, Search } from "lucide-react";
import { api } from "@/api/endpoints";
import {
  ExportM3u8Modal,
  type ExportM3u8Target,
} from "@/components/playlists/ExportM3u8Modal";
import {
  ExportSongsModal,
  type ExportSongsTarget,
} from "@/components/playlists/ExportSongsModal";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { cn, formatBytes } from "@/lib/utils";

type SourceTab = "saved" | "playlists" | "albums";

export function ExportersPanel() {
  const [sourceTab, setSourceTab] = useState<SourceTab>("saved");
  const [query, setQuery] = useState("");
  const [songsTarget, setSongsTarget] = useState<ExportSongsTarget | null>(
    null
  );
  const [m3u8Target, setM3u8Target] = useState<ExportM3u8Target | null>(null);

  const { data: savedData, isLoading: loadingSaved } = useQuery({
    queryKey: ["playlists", "all"],
    queryFn: () => api.playlists.list(),
    staleTime: 30000,
  });

  const { data: libPlaylists, isLoading: loadingLibPlaylists } = useQuery({
    queryKey: ["library", "playlists", "export"],
    queryFn: () => api.library.playlists({}),
    staleTime: 30000,
  });

  const { data: libAlbums, isLoading: loadingLibAlbums } = useQuery({
    queryKey: ["library", "albums", "export"],
    queryFn: () => api.library.albums({}),
    staleTime: 30000,
  });

  const filteredSaved = useMemo(() => {
    const items = savedData?.playlists || [];
    const q = query.trim().toLowerCase();
    return q
      ? items.filter((p) => p.name.toLowerCase().includes(q))
      : items;
  }, [query, savedData?.playlists]);

  const filteredLibPlaylists = useMemo(() => {
    const items = libPlaylists?.playlists || [];
    const q = query.trim().toLowerCase();
    return q
      ? items.filter((c) => c.name.toLowerCase().includes(q))
      : items;
  }, [libPlaylists?.playlists, query]);

  const filteredLibAlbums = useMemo(() => {
    const items = libAlbums?.albums || [];
    const q = query.trim().toLowerCase();
    return q
      ? items.filter(
          (c) =>
            c.name.toLowerCase().includes(q) ||
            (c.artist || "").toLowerCase().includes(q)
        )
      : items;
  }, [libAlbums?.albums, query]);

  const isLoading =
    sourceTab === "saved"
      ? loadingSaved
      : sourceTab === "playlists"
        ? loadingLibPlaylists
        : loadingLibAlbums;

  return (
    <div className="space-y-5">
      <div className="glass-panel rounded-2xl p-5 flex flex-wrap items-center justify-between gap-4">
        <div className="space-y-1 max-w-2xl">
          <div className="flex items-center gap-2">
            <FolderOutput className="h-4 w-4 text-emerald-bright" />
            <h2 className="text-base font-semibold text-white">
              Device Song Exporter & Portable .m3u8 Generator
            </h2>
          </div>
          <p className="text-xs text-zinc-400 leading-relaxed">
            Copy or batch-transcode collections (Original, ALAC `.m4a` for
            Apple, MP3 320, FLAC, Opus 256) to USB drives or SD cards, and build
            portable `.m3u8` playlists for Android/DAP players.
          </p>
        </div>

        <div className="relative w-full sm:w-64">
          <Search className="h-3.5 w-3.5 text-zinc-500 absolute left-3 top-1/2 -translate-y-1/2" />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Filter playlists or albums..."
            className="pl-8 h-9 text-xs"
          />
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {(
          [
            [
              "saved",
              `Saved Spotify Playlists (${savedData?.playlists.length ?? 0})`,
              ListMusic,
            ],
            [
              "playlists",
              `Library Playlist Folders (${libPlaylists?.playlists.length ?? 0})`,
              FolderOutput,
            ],
            [
              "albums",
              `Library Albums (${libAlbums?.albums.length ?? 0})`,
              Disc3,
            ],
          ] as const
        ).map(([id, label, Icon]) => (
          <button
            key={id}
            type="button"
            onClick={() => setSourceTab(id)}
            className={cn(
              "inline-flex items-center gap-2 rounded-full px-3.5 py-2 text-xs font-medium transition-colors cursor-pointer border",
              sourceTab === id
                ? "bg-emerald-500/20 text-emerald-300 border-emerald-500/40"
                : "bg-white/[0.03] text-zinc-400 border-white/[0.07] hover:text-zinc-200"
            )}
          >
            <Icon className="h-3.5 w-3.5" />
            {label}
          </button>
        ))}
      </div>

      <div className="glass-panel rounded-2xl p-4">
        {isLoading ? (
          <div className="space-y-2.5">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-14 w-full rounded-xl" />
            ))}
          </div>
        ) : sourceTab === "saved" ? (
          filteredSaved.length === 0 ? (
            <div className="py-10 text-center text-xs text-zinc-500">
              No saved playlists found. Save a playlist from the Playlists tab
              first.
            </div>
          ) : (
            <div className="divide-y divide-white/[0.06]">
              {filteredSaved.map((pl) => (
                <div
                  key={pl.id}
                  className="flex flex-wrap items-center justify-between gap-3 py-3 px-2"
                >
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-white truncate">
                        {pl.name}
                      </span>
                      <Badge variant="emerald" className="text-[10px]">
                        {pl.downloaded_count}/{pl.total_tracks} ready
                      </Badge>
                    </div>
                    <div className="text-[11px] text-zinc-400">
                      Spotify Saved Playlist
                    </div>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <Button
                      type="button"
                      size="sm"
                      disabled={pl.downloaded_count === 0}
                      onClick={() =>
                        setSongsTarget({
                          playlistId: pl.id,
                          playlistName: pl.name,
                          trackCountHint: pl.downloaded_count,
                        })
                      }
                    >
                      <FolderOutput className="h-3.5 w-3.5" />
                      Export Songs
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant="secondary"
                      disabled={pl.downloaded_count === 0}
                      onClick={() =>
                        setM3u8Target({
                          playlistId: pl.id,
                          playlistName: pl.name,
                        })
                      }
                    >
                      <FileMusic className="h-3.5 w-3.5" />
                      Export .m3u8
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )
        ) : (
          (() => {
            const list =
              sourceTab === "playlists"
                ? filteredLibPlaylists
                : filteredLibAlbums;
            const ctype = sourceTab === "playlists" ? "playlist" : "album";
            if (list.length === 0) {
              return (
                <div className="py-10 text-center text-xs text-zinc-500">
                  No downloaded {ctype}s found in your library.
                </div>
              );
            }
            return (
              <div className="divide-y divide-white/[0.06]">
                {list.map((col) => (
                  <div
                    key={`${ctype}:${col.name}`}
                    className="flex flex-wrap items-center justify-between gap-3 py-3 px-2"
                  >
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium text-white truncate">
                          {col.name}
                        </span>
                        <Badge variant="sky" className="text-[10px] tabular-nums">
                          {col.track_count} tracks ·{" "}
                          {formatBytes(col.total_size_bytes)}
                        </Badge>
                      </div>
                      <div className="text-[11px] text-zinc-400 truncate">
                        {col.artist ? `${col.artist} · ` : ""}
                        {col.genre || ctype}
                      </div>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <Button
                        type="button"
                        size="sm"
                        onClick={() =>
                          setSongsTarget({
                            playlistName: col.name,
                            collectionName: col.name,
                            collectionType: ctype,
                            trackCountHint: col.track_count,
                          })
                        }
                      >
                        <FolderOutput className="h-3.5 w-3.5" />
                        Export Songs
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        variant="secondary"
                        onClick={() =>
                          setM3u8Target({
                            playlistName: col.name,
                            collectionName: col.name,
                            collectionType: ctype,
                          })
                        }
                      >
                        <FileMusic className="h-3.5 w-3.5" />
                        Export .m3u8
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            );
          })()
        )}
      </div>

      <ExportSongsModal
        target={songsTarget}
        onClose={() => setSongsTarget(null)}
      />
      <ExportM3u8Modal
        target={m3u8Target}
        onClose={() => setM3u8Target(null)}
      />
    </div>
  );
}
