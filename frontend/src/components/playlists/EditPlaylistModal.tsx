import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { Disc3, Heart, X } from "lucide-react";
import { toast } from "sonner";
import { apiUrl } from "@/api/client";
import { api } from "@/api/endpoints";
import type { SavedPlaylist } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

interface EditPlaylistModalProps {
  playlist: SavedPlaylist | null;
  onClose: () => void;
}

export function EditPlaylistModal({ playlist, onClose }: EditPlaylistModalProps) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [spotifyUrl, setSpotifyUrl] = useState("");
  const [coverValue, setCoverValue] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!playlist) return;
    setName(playlist.name || "");
    setSpotifyUrl(playlist.spotify_url || "");
    setCoverValue(playlist.cover_url || "");
  }, [playlist]);

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!playlist || !name.trim() || saving) return;
    setSaving(true);
    try {
      await api.playlists.update(playlist.id, {
        name: name.trim(),
        spotify_url: spotifyUrl.trim(),
        cover_url: coverValue.trim(),
      });
      void queryClient.invalidateQueries({ queryKey: ["playlists"] });
      toast.success("Playlist updated");
      onClose();
    } catch (err) {
      toast.error("Failed to update playlist", {
        description: err instanceof Error ? err.message : undefined,
      });
    } finally {
      setSaving(false);
    }
  };

  const previewSrc =
    coverValue.startsWith("http://") || coverValue.startsWith("https://")
      ? coverValue
      : playlist?.local_cover
        ? apiUrl(
            `/api/media/cover/collection?name=${encodeURIComponent(playlist.name)}`
          )
        : "";

  return (
    <AnimatePresence>
      {playlist && (
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
            className="relative z-10 w-full max-w-lg rounded-2xl glass-panel p-6 shadow-2xl space-y-4"
          >
            <div className="flex items-start justify-between gap-3">
              <div>
                <h2 className="text-base font-semibold text-white">
                  Edit Playlist Details
                </h2>
                <p className="text-xs text-zinc-400">
                  Rename playlist, adjust source link, or customize cover artwork.
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
                Playlist Name
              </label>
              <Input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Playlist name..."
                required
              />
            </div>

            <div className="space-y-1.5">
              <label className="text-xs font-medium text-zinc-300">
                Spotify Link / URL
              </label>
              <Input
                value={spotifyUrl}
                onChange={(e) => setSpotifyUrl(e.target.value)}
                placeholder="https://open.spotify.com/playlist/... or collection/tracks"
              />
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => {
                  setSpotifyUrl("https://open.spotify.com/collection/tracks");
                  if (
                    !name.trim() ||
                    ["playlist", "spotify playlist"].includes(name.trim().toLowerCase())
                  ) {
                    setName("Liked Songs");
                  }
                }}
              >
                <Heart className="h-3.5 w-3.5 text-emerald-400" />
                Use Spotify Liked Songs (collection/tracks)
              </Button>
            </div>

            <div className="space-y-1.5">
              <label className="text-xs font-medium text-zinc-300">
                Cover Artwork (URL or local file path on server)
              </label>
              <div className="flex items-center gap-3">
                <div className="h-14 w-14 shrink-0 overflow-hidden rounded-xl bg-elevated border border-white/10">
                  {previewSrc ? (
                    <img
                      src={previewSrc}
                      alt="Cover preview"
                      className="h-full w-full object-cover"
                    />
                  ) : (
                    <div className="flex h-full w-full items-center justify-center text-zinc-500">
                      <Disc3 className="h-5 w-5" />
                    </div>
                  )}
                </div>
                <Input
                  value={coverValue}
                  onChange={(e) => setCoverValue(e.target.value)}
                  placeholder="https://... or C:\path\to\cover.jpg"
                />
              </div>
            </div>

            <div className="flex items-center justify-end gap-2 pt-2 border-t border-white/[0.06]">
              <Button type="button" variant="ghost" onClick={onClose}>
                Cancel
              </Button>
              <Button type="submit" disabled={saving || !name.trim()}>
                {saving ? "Saving..." : "Save Changes"}
              </Button>
            </div>
          </motion.form>
        </div>
      )}
    </AnimatePresence>
  );
}
