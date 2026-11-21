import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import {
  CheckCircle2,
  FolderOpen,
  FolderOutput,
  FolderSearch,
  X,
} from "lucide-react";
import { toast } from "sonner";
import { api } from "@/api/endpoints";
import type { ExportSongsResponse } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { isDesktopApp, pickDirectory } from "@/lib/desktop";
import { useAppStore } from "@/stores/appStore";

export interface ExportSongsTarget {
  playlistId?: string;
  playlistName: string;
  collectionName?: string;
  collectionType?: "playlist" | "album";
  trackIds?: string[];
  trackCountHint?: number;
}

interface ExportSongsModalProps {
  target: ExportSongsTarget | null;
  onClose: () => void;
}

type TargetFormat = "original" | "alac" | "mp3" | "flac" | "opus";

export function ExportSongsModal({ target, onClose }: ExportSongsModalProps) {
  const { data: settingsData } = useQuery({
    queryKey: ["settings"],
    queryFn: () => api.settings.get(),
    staleTime: 60000,
  });

  const activeToolProgress = useAppStore((s) => s.activeToolProgress);

  const [destinationDir, setDestinationDir] = useState("");
  const [targetFormat, setTargetFormat] = useState<TargetFormat>("original");
  const [createSubfolder, setCreateSubfolder] = useState(true);
  const [generateM3u8, setGenerateM3u8] = useState(true);
  const [skipExisting, setSkipExisting] = useState(true);
  const [exporting, setExporting] = useState(false);
  const [result, setResult] = useState<ExportSongsResponse | null>(null);

  useEffect(() => {
    if (!target) return;
    setResult(null);
    if (!destinationDir && settingsData?.config.download.output_dir) {
      setDestinationDir(`${settingsData.config.download.output_dir}\\Exports`);
    }
  }, [destinationDir, settingsData?.config.download.output_dir, target]);

  const handleExport = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!target || !destinationDir.trim() || exporting) return;
    setExporting(true);
    setResult(null);
    try {
      const res = await api.tools.exportSongs({
        destination_dir: destinationDir.trim(),
        playlist_name: target.playlistName,
        playlist_id: target.playlistId,
        collection_name: target.collectionName,
        collection_type: target.collectionType,
        track_ids: target.trackIds,
        create_playlist_subfolder: createSubfolder,
        target_format: targetFormat,
        generate_m3u8: generateM3u8,
        skip_existing: skipExisting,
      });
      setResult(res);
      if (res.cancelled) {
        toast.info("Export cancelled");
      } else {
        toast.success(`Exported ${res.exported} track(s)`, {
          description: `${res.skipped} skipped, ${res.failed} failed`,
        });
      }
    } catch (err) {
      toast.error("Export failed", {
        description: err instanceof Error ? err.message : undefined,
      });
    } finally {
      setExporting(false);
    }
  };

  const isRunningExport =
    exporting && activeToolProgress?.tool === "export_songs";

  return (
    <AnimatePresence>
      {target && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={exporting ? undefined : onClose}
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
                  <FolderOutput className="h-4 w-4" />
                </div>
                <div>
                  <h2 className="text-base font-semibold text-white">
                    Export Songs to Folder / Device
                  </h2>
                  <p className="text-xs text-zinc-400">
                    {target.playlistName}
                    {target.trackCountHint
                      ? ` · ${target.trackCountHint} track(s)`
                      : ""}
                  </p>
                </div>
              </div>
              <button
                type="button"
                disabled={exporting}
                onClick={onClose}
                className="rounded-lg p-1.5 text-zinc-400 hover:bg-white/10 hover:text-white disabled:opacity-40 cursor-pointer"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="space-y-1.5">
              <label className="text-xs font-medium text-zinc-300">
                Destination Folder / USB Path
              </label>
              <div className="flex items-center gap-2">
                <Input
                  value={destinationDir}
                  onChange={(e) => setDestinationDir(e.target.value)}
                  placeholder="D:\USB_Music or C:\Users\...\Export"
                  required
                  className="flex-1"
                />
                {isDesktopApp() && (
                  <Button
                    type="button"
                    size="sm"
                    variant="secondary"
                    onClick={async () => {
                      const chosen = await pickDirectory(
                        "Select Export Destination Folder",
                        destinationDir
                      );
                      if (chosen) setDestinationDir(chosen);
                    }}
                  >
                    <FolderSearch className="h-3.5 w-3.5" />
                    Browse
                  </Button>
                )}
              </div>
            </div>

            <div className="space-y-1.5">
              <label className="text-xs font-medium text-zinc-300">
                Output Audio Format
              </label>
              <select
                value={targetFormat}
                onChange={(e) => setTargetFormat(e.target.value as TargetFormat)}
                className="h-10 w-full rounded-xl border border-white/10 bg-elevated px-3 text-sm text-zinc-100 focus:border-emerald-500/60 focus:outline-none cursor-pointer"
              >
                <option value="original">
                  Original / Native Stream (Fastest Copy)
                </option>
                <option value="mp3">MP3 320 kbps CBR (Car / Universal)</option>
                <option value="alac">
                  Apple Lossless ALAC (.m4a — iPhone / Apple Music)
                </option>
                <option value="flac">Lossless FLAC</option>
                <option value="opus">Opus 256 kbps (Compact Hi-Fi)</option>
              </select>
            </div>

            <div className="space-y-2 rounded-xl bg-white/[0.03] border border-white/[0.06] p-3.5 text-xs text-zinc-300">
              <label className="flex items-center gap-2.5 cursor-pointer">
                <input
                  type="checkbox"
                  checked={createSubfolder}
                  onChange={(e) => setCreateSubfolder(e.target.checked)}
                  className="h-4 w-4 rounded accent-emerald-500"
                />
                Create playlist subfolder inside destination
              </label>
              <label className="flex items-center gap-2.5 cursor-pointer">
                <input
                  type="checkbox"
                  checked={generateM3u8}
                  onChange={(e) => setGenerateM3u8(e.target.checked)}
                  className="h-4 w-4 rounded accent-emerald-500"
                />
                Generate portable .m3u8 playlist inside export folder
              </label>
              <label className="flex items-center gap-2.5 cursor-pointer">
                <input
                  type="checkbox"
                  checked={skipExisting}
                  onChange={(e) => setSkipExisting(e.target.checked)}
                  className="h-4 w-4 rounded accent-emerald-500"
                />
                Skip tracks that already exist in destination
              </label>
            </div>

            {isRunningExport && activeToolProgress && (
              <div className="space-y-1.5 rounded-xl bg-emerald-500/10 border border-emerald-500/25 p-3">
                <div className="flex items-center justify-between text-xs text-emerald-300 font-mono tabular-nums">
                  <span className="truncate">{activeToolProgress.message}</span>
                  <span>
                    {activeToolProgress.current}/{activeToolProgress.total} (
                    {Math.round(activeToolProgress.percent)}%)
                  </span>
                </div>
                <div className="h-1.5 w-full rounded-full bg-black/40 overflow-hidden">
                  <div
                    className="h-full bg-emerald-bright transition-all"
                    style={{
                      width: `${Math.max(4, Math.min(100, activeToolProgress.percent))}%`,
                    }}
                  />
                </div>
              </div>
            )}

            {result && (
              <div className="rounded-xl border border-emerald-500/35 bg-emerald-500/10 p-3.5 text-xs space-y-2">
                <div className="flex items-center gap-2 font-medium text-emerald-300">
                  <CheckCircle2 className="h-4 w-4 shrink-0" />
                  <span>
                    Export {result.cancelled ? "Cancelled" : "Complete"}:{" "}
                    {result.exported} exported · {result.skipped} skipped ·{" "}
                    {result.failed} failed
                  </span>
                </div>
                <div className="font-mono text-[11px] text-zinc-200 break-all">
                  {result.export_dir}
                </div>
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  onClick={() => void api.settings.openFolder(result.export_dir)}
                >
                  <FolderOpen className="h-3.5 w-3.5" />
                  Open Export Folder
                </Button>
              </div>
            )}

            <div className="flex items-center justify-end gap-2 pt-2 border-t border-white/[0.06]">
              {exporting ? (
                <Button
                  type="button"
                  variant="destructive"
                  onClick={() => void api.tools.cancel("export_songs")}
                >
                  Cancel Export
                </Button>
              ) : (
                <>
                  <Button type="button" variant="ghost" onClick={onClose}>
                    Close
                  </Button>
                  <Button type="submit" disabled={!destinationDir.trim()}>
                    Start Export
                  </Button>
                </>
              )}
            </div>
          </motion.form>
        </div>
      )}
    </AnimatePresence>
  );
}
