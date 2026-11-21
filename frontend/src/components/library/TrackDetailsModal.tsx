import { AnimatePresence, motion } from "framer-motion";
import { Copy, Disc3, FolderOpen, X } from "lucide-react";
import { toast } from "sonner";
import { apiUrl } from "@/api/client";
import { api } from "@/api/endpoints";
import type { LibraryTrack } from "@/api/types";
import { Badge, QualityBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { formatBytes, formatDuration } from "@/lib/utils";

interface TrackDetailsModalProps {
  track: LibraryTrack | null;
  onClose: () => void;
}

export function TrackDetailsModal({ track, onClose }: TrackDetailsModalProps) {
  return (
    <AnimatePresence>
      {track && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="fixed inset-0 bg-black/75 backdrop-blur-sm"
          />

          <motion.div
            initial={{ opacity: 0, scale: 0.96, y: 10 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.96, y: 10 }}
            className="relative z-10 w-full max-w-lg rounded-2xl glass-panel p-6 shadow-2xl space-y-4"
          >
            <div className="flex items-start justify-between gap-3">
              <div className="flex items-center gap-3.5 min-w-0">
                <div className="h-14 w-14 shrink-0 overflow-hidden rounded-xl bg-elevated border border-white/10">
                  <img
                    src={apiUrl(track.cover_url_local)}
                    alt={track.title}
                    className="h-full w-full object-cover"
                    onError={(e) => {
                      e.currentTarget.style.display = "none";
                    }}
                  />
                </div>
                <div className="min-w-0">
                  <h2 className="text-base font-semibold text-white truncate">
                    {track.title}
                  </h2>
                  <p className="text-xs text-zinc-400 truncate">
                    {track.artist}
                  </p>
                </div>
              </div>
              <button
                type="button"
                onClick={onClose}
                className="rounded-lg p-1.5 text-zinc-400 hover:bg-white/10 hover:text-white cursor-pointer"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <QualityBadge
                badge={track.quality_badge}
                sourceType={track.source_type}
              />
              {track.source_type && (
                <Badge variant="default">Source: {track.source_type}</Badge>
              )}
              {track.genres.map((g) => (
                <Badge key={g} variant="emerald">
                  {g}
                </Badge>
              ))}
            </div>

            <div className="grid grid-cols-2 gap-3 rounded-xl bg-white/[0.03] border border-white/[0.07] p-3.5 text-xs">
              <div>
                <div className="text-zinc-500">Album</div>
                <div className="text-zinc-200 mt-0.5 truncate">
                  {track.album || "—"}
                </div>
              </div>
              <div>
                <div className="text-zinc-500">Collection</div>
                <div className="text-zinc-200 mt-0.5 truncate">
                  {track.collection_name || "Singles"} ({track.collection_type || "track"})
                </div>
              </div>
              <div>
                <div className="text-zinc-500">Track / Disc #</div>
                <div className="font-mono text-zinc-200 mt-0.5 tabular-nums">
                  {track.track_number || 1} / Disc {track.disc_number || 1}
                </div>
              </div>
              <div>
                <div className="text-zinc-500">Duration · Size</div>
                <div className="font-mono text-zinc-200 mt-0.5 tabular-nums">
                  {formatDuration(track.duration_ms)} · {formatBytes(track.file_size)}
                </div>
              </div>
              {track.isrc && (
                <div>
                  <div className="text-zinc-500">ISRC</div>
                  <div className="font-mono text-zinc-200 mt-0.5">
                    {track.isrc}
                  </div>
                </div>
              )}
              {track.downloaded_at && (
                <div>
                  <div className="text-zinc-500">Downloaded</div>
                  <div className="font-mono text-zinc-200 mt-0.5">
                    {track.downloaded_at}
                  </div>
                </div>
              )}
            </div>

            <div className="space-y-1.5">
              <div className="text-xs font-medium text-zinc-400 flex items-center gap-1.5">
                <Disc3 className="h-3.5 w-3.5" />
                Location on Disk
              </div>
              <div className="rounded-xl bg-black/40 border border-white/[0.07] p-3 font-mono text-[11px] text-zinc-300 break-all">
                {track.file_path || "Unavailable"}
              </div>
            </div>

            <div className="flex flex-wrap items-center justify-end gap-2 pt-2 border-t border-white/[0.06]">
              {track.file_path && (
                <>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={() =>
                      void navigator.clipboard
                        .writeText(track.file_path)
                        .then(() => toast.success("Copied file path"))
                    }
                  >
                    <Copy className="h-3.5 w-3.5" />
                    Copy Path
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="secondary"
                    onClick={() =>
                      void api.settings
                        .openFolder(track.file_path, true)
                        .catch((err) =>
                          toast.error("File not found", {
                            description:
                              err instanceof Error ? err.message : undefined,
                          })
                        )
                    }
                  >
                    <FolderOpen className="h-3.5 w-3.5" />
                    Show in Explorer
                  </Button>
                </>
              )}
              <Button type="button" size="sm" onClick={onClose}>
                Close
              </Button>
            </div>
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  );
}
