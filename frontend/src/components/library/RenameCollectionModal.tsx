import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { Pencil, X } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/api/endpoints";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

interface RenameCollectionModalProps {
  oldName: string | null;
  collectionType?: "playlist" | "album";
  onRenamed: (newName: string) => void;
  onClose: () => void;
}

export function RenameCollectionModal({
  oldName,
  collectionType = "playlist",
  onRenamed,
  onClose,
}: RenameCollectionModalProps) {
  const queryClient = useQueryClient();
  const [newName, setNewName] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (oldName !== null) {
      setNewName(oldName);
    }
  }, [oldName]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const cleaned = newName.trim();
    if (!oldName || !cleaned || cleaned === oldName || saving) return;
    setSaving(true);
    try {
      await api.library.renameCollection({
        old_name: oldName,
        new_name: cleaned,
        collection_type: collectionType,
      });
      void queryClient.invalidateQueries({ queryKey: ["library"] });
      void queryClient.invalidateQueries({ queryKey: ["playlists"] });
      toast.success(`Renamed to "${cleaned}"`);
      onRenamed(cleaned);
      onClose();
    } catch (err) {
      toast.error("Failed to rename collection", {
        description: err instanceof Error ? err.message : undefined,
      });
    } finally {
      setSaving(false);
    }
  };

  return (
    <AnimatePresence>
      {oldName !== null && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="fixed inset-0 bg-black/75 backdrop-blur-sm"
          />

          <motion.form
            onSubmit={handleSubmit}
            initial={{ opacity: 0, scale: 0.96, y: 10 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.96, y: 10 }}
            className="relative z-10 w-full max-w-md rounded-2xl glass-panel p-6 shadow-2xl space-y-4"
          >
            <div className="flex items-start justify-between gap-3">
              <div className="flex items-center gap-2.5">
                <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-emerald-500/15 text-emerald-300 border border-emerald-500/30">
                  <Pencil className="h-4 w-4" />
                </div>
                <div>
                  <h2 className="text-base font-semibold text-white">
                    Rename Playlist Collection
                  </h2>
                  <p className="text-xs text-zinc-400">
                    Updates archive records and moves folders cleanly on disk.
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

            <div className="space-y-1.5">
              <label className="text-xs font-medium text-zinc-300">
                New Name
              </label>
              <Input
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                placeholder="Enter playlist name..."
                required
              />
            </div>

            <div className="flex items-center justify-end gap-2 pt-2 border-t border-white/[0.06]">
              <Button type="button" variant="ghost" onClick={onClose}>
                Cancel
              </Button>
              <Button
                type="submit"
                disabled={saving || !newName.trim() || newName.trim() === oldName}
              >
                {saving ? "Renaming..." : "Rename"}
              </Button>
            </div>
          </motion.form>
        </div>
      )}
    </AnimatePresence>
  );
}
