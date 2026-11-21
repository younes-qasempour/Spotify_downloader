import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { X } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/api/endpoints";
import type { PlaylistTrackRow } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

interface EditTrackModalProps {
  playlistId: string;
  track: PlaylistTrackRow | null;
  onClose: () => void;
}

export function EditTrackModal({
  playlistId,
  track,
  onClose,
}: EditTrackModalProps) {
  const queryClient = useQueryClient();
  const [title, setTitle] = useState("");
  const [artist, setArtist] = useState("");
  const [album, setAlbum] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!track) return;
    setTitle(track.title || "");
    setArtist(track.artist || "");
    setAlbum(track.album || "");
  }, [track]);

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!track || !title.trim() || saving) return;
    setSaving(true);
    try {
      await api.playlists.updateTrack(playlistId, track.spotify_id, {
        title: title.trim(),
        artist: artist.trim(),
        album: album.trim(),
      });
      void queryClient.invalidateQueries({ queryKey: ["playlists"] });
      toast.success(`Updated "${title.trim()}"`);
      onClose();
    } catch (err) {
      toast.error("Failed to update track", {
        description: err instanceof Error ? err.message : undefined,
      });
    } finally {
      setSaving(false);
    }
  };

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

          <motion.form
            onSubmit={handleSave}
            initial={{ opacity: 0, scale: 0.96, y: 10 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.96, y: 10 }}
            className="relative z-10 w-full max-w-md rounded-2xl glass-panel p-6 shadow-2xl space-y-4"
          >
            <div className="flex items-start justify-between gap-3">
              <div>
                <h2 className="text-base font-semibold text-white">
                  Edit Track Metadata
                </h2>
                <p className="text-xs text-zinc-400">
                  Update song title, artist credits, or album name in this playlist.
                </p>
              </div>
              <button
                type="button"
                onClick={onClose}
                className="rounded-lg p-1.5 text-zinc-400 hover:bg-white/10 hover:text-white cursor-pointer"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="space-y-1.5">
              <label className="text-xs font-medium text-zinc-300">
                Track Title
              </label>
              <Input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                required
              />
            </div>

            <div className="space-y-1.5">
              <label className="text-xs font-medium text-zinc-300">
                Artist(s)
              </label>
              <Input
                value={artist}
                onChange={(e) => setArtist(e.target.value)}
              />
            </div>

            <div className="space-y-1.5">
              <label className="text-xs font-medium text-zinc-300">Album</label>
              <Input value={album} onChange={(e) => setAlbum(e.target.value)} />
            </div>

            <div className="flex items-center justify-end gap-2 pt-2 border-t border-white/[0.06]">
              <Button type="button" variant="ghost" onClick={onClose}>
                Cancel
              </Button>
              <Button type="submit" disabled={saving || !title.trim()}>
                {saving ? "Saving..." : "Save Track"}
              </Button>
            </div>
          </motion.form>
        </div>
      )}
    </AnimatePresence>
  );
}
