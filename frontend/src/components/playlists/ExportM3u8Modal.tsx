import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { CheckCircle2, FileMusic, FolderOpen, FolderSearch, X } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/api/endpoints";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { isDesktopApp, saveFile } from "@/lib/desktop";
import { cn } from "@/lib/utils";

export interface ExportM3u8Target {
  playlistId?: string;
  playlistName: string;
  collectionName?: string;
  collectionType?: "playlist" | "album";
  trackIds?: string[];
}

interface ExportM3u8ModalProps {
  target: ExportM3u8Target | null;
  onClose: () => void;
}

type PathMode = "filename" | "relative" | "absolute" | "android_prefix";

const PATH_MODES: Array<{ id: PathMode; title: string; desc: string }> = [
  {
    id: "filename",
    title: "Portable Filename Only (Recommended)",
    desc: "Best for Android (Poweramp, Musicolet, VLC) & USB DAPs when .m3u8 sits beside songs.",
  },
  {
    id: "android_prefix",
    title: "Android Custom Folder Prefix",
    desc: "Prefixes track paths with your phone's internal storage music path.",
  },
  {
    id: "relative",
    title: "Relative Paths",
    desc: "Relative file paths resolved from the exported .m3u8 file location.",
  },
  {
    id: "absolute",
    title: "Desktop Absolute Paths",
    desc: "Full local filesystem paths (foobar2000, VLC, PotPlayer on PC).",
  },
];

export function ExportM3u8Modal({ target, onClose }: ExportM3u8ModalProps) {
  const [pathMode, setPathMode] = useState<PathMode>("filename");
  const [androidPrefix, setAndroidPrefix] = useState("/storage/emulated/0/Music");
  const [destPath, setDestPath] = useState("");
  const [exporting, setExporting] = useState(false);
  const [exportedPath, setExportedPath] = useState<string | null>(null);

  useEffect(() => {
    if (!target) return;
    setExportedPath(null);
    setDestPath("");
  }, [target]);

  const handleExport = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!target || exporting) return;
    setExporting(true);
    try {
      const res = await api.tools.exportM3u8({
        playlist_id: target.playlistId,
        collection_name: target.collectionName,
        collection_type: target.collectionType,
        playlist_name: target.playlistName,
        track_ids: target.trackIds,
        dest_path: destPath.trim() || undefined,
        path_mode: pathMode,
        android_prefix: androidPrefix.trim() || "/storage/emulated/0/Music",
      });
      setExportedPath(res.m3u8_path);
      toast.success("Playlist exported to .m3u8", {
        description: res.m3u8_path,
      });
    } catch (err) {
      toast.error("Failed to export .m3u8", {
        description: err instanceof Error ? err.message : undefined,
      });
    } finally {
      setExporting(false);
    }
  };

  return (
    <AnimatePresence>
      {target && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="fixed inset-0 bg-black/75 backdrop-blur-sm"
          />

          <motion.form
            onSubmit={handleExport}
            initial={{ opacity: 0, scale: 0.96, y: 10 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.96, y: 10 }}
            className="relative z-10 w-full max-w-lg rounded-2xl glass-panel p-6 shadow-2xl space-y-4"
          >
            <div className="flex items-start justify-between gap-3">
              <div className="flex items-center gap-2.5">
                <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-emerald-500/15 text-emerald-300 border border-emerald-500/30">
                  <FileMusic className="h-4 w-4" />
                </div>
                <div>
                  <h2 className="text-base font-semibold text-white">
                    Export Playlist (.m3u8)
                  </h2>
                  <p className="text-xs text-zinc-400 truncate max-w-[340px]">
                    {target.playlistName}
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

            <div className="space-y-2">
              <label className="text-xs font-medium text-zinc-300">
                Track Path Format
              </label>
              <div className="space-y-1.5">
                {PATH_MODES.map((m) => (
                  <button
                    key={m.id}
                    type="button"
                    onClick={() => setPathMode(m.id)}
                    className={cn(
                      "w-full rounded-xl border px-3.5 py-2.5 text-left transition-colors cursor-pointer",
                      pathMode === m.id
                        ? "border-emerald-500/50 bg-emerald-500/[0.08]"
                        : "border-white/10 bg-white/[0.02] hover:bg-white/[0.05]"
                    )}
                  >
                    <div className="text-xs font-semibold text-white">
                      {m.title}
                    </div>
                    <div className="text-[11px] text-zinc-400 mt-0.5">
                      {m.desc}
                    </div>
                  </button>
                ))}
              </div>
            </div>

            {pathMode === "android_prefix" && (
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-zinc-300">
                  Android Folder Prefix
                </label>
                <Input
                  value={androidPrefix}
                  onChange={(e) => setAndroidPrefix(e.target.value)}
                  placeholder="/storage/emulated/0/Music"
                />
              </div>
            )}

            <div className="space-y-1.5">
              <label className="text-xs font-medium text-zinc-300">
                Custom Output File Path (Optional)
              </label>
              <div className="flex items-center gap-2">
                <Input
                  value={destPath}
                  onChange={(e) => setDestPath(e.target.value)}
                  placeholder="Leave blank to save automatically in your downloads folder"
                  className="flex-1"
                />
                {isDesktopApp() && (
                  <Button
                    type="button"
                    size="sm"
                    variant="secondary"
                    onClick={async () => {
                      const chosen = await saveFile(
                        "Save .m3u8 Playlist",
                        destPath || `${target.playlistName}.m3u8`,
                        [{ name: "M3U8 Playlist", extensions: ["m3u8"] }]
                      );
                      if (chosen) setDestPath(chosen);
                    }}
                  >
                    <FolderSearch className="h-3.5 w-3.5" />
                    Browse
                  </Button>
                )}
              </div>
            </div>

            {exportedPath && (
              <div className="rounded-xl border border-emerald-500/35 bg-emerald-500/10 p-3 text-xs space-y-2">
                <div className="flex items-center gap-2 font-medium text-emerald-300">
                  <CheckCircle2 className="h-4 w-4 shrink-0" />
                  <span>Generated .m3u8 playlist</span>
                </div>
                <div className="font-mono text-[11px] text-zinc-200 break-all">
                  {exportedPath}
                </div>
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  onClick={() => void api.settings.openFolder(exportedPath, true)}
                >
                  <FolderOpen className="h-3.5 w-3.5" />
                  Reveal File
                </Button>
              </div>
            )}

            <div className="flex items-center justify-end gap-2 pt-2 border-t border-white/[0.06]">
              <Button type="button" variant="ghost" onClick={onClose}>
                Close
              </Button>
              <Button type="submit" disabled={exporting}>
                {exporting ? "Generating..." : "Generate .m3u8"}
              </Button>
            </div>
          </motion.form>
        </div>
      )}
    </AnimatePresence>
  );
}
