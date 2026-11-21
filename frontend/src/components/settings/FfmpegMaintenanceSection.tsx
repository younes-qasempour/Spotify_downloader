import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  ArrowRight,
  CopyCheck,
  Download,
  FileAudio,
  FolderOpen,
  FolderSync,
  Loader2,
  Sparkles,
  Volume2,
  Wrench,
} from "lucide-react";
import { toast } from "sonner";
import { api } from "@/api/endpoints";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useAppStore } from "@/stores/appStore";

export function FfmpegMaintenanceSection() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const activeToolProgress = useAppStore((s) => s.activeToolProgress);

  const [installingFfmpeg, setInstallingFfmpeg] = useState(false);
  const [cleaning, setCleaning] = useState(false);

  const { data: ffStatus, refetch: refetchFfmpeg } = useQuery({
    queryKey: ["ffmpeg-status"],
    queryFn: () => api.settings.ffmpegStatus(),
    staleTime: 60000,
  });

  const handleInstallFfmpeg = async () => {
    if (installingFfmpeg) return;
    setInstallingFfmpeg(true);
    try {
      const res = await api.settings.ffmpegInstall();
      void refetchFfmpeg();
      if (res.success) {
        toast.success("FFmpeg Installed & Ready", {
          description: res.path,
        });
      } else {
        toast.error("FFmpeg install failed", { description: res.message });
      }
    } catch (err) {
      toast.error("FFmpeg download error", {
        description: err instanceof Error ? err.message : undefined,
      });
    } finally {
      setInstallingFfmpeg(false);
    }
  };

  const handleQuickClean = async () => {
    if (cleaning) return;
    setCleaning(true);
    try {
      const res = await api.tools.cleanLibrary();
      void queryClient.invalidateQueries({ queryKey: ["library"] });
      toast.success("Library Cleaned", {
        description: `${res.purged_corrupt_files} corrupt file(s) purged · ${res.purged_db_records} stale DB record(s) removed`,
      });
    } catch (err) {
      toast.error("Cleanup failed", {
        description: err instanceof Error ? err.message : undefined,
      });
    } finally {
      setCleaning(false);
    }
  };

  const ffProgress =
    installingFfmpeg && activeToolProgress?.tool === "ffmpeg_install"
      ? activeToolProgress
      : null;

  return (
    <div className="space-y-5">
      {/* Standalone FFmpeg Binary */}
      <div className="glass-panel rounded-2xl p-6 space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-base font-semibold text-white">
              FFmpeg & FFprobe Engine
            </h2>
            <p className="text-xs text-zinc-400 mt-0.5">
              Powers format transcoding (ALAC/MP3/FLAC/Opus), EBU R128 loudness,
              spectograms, acoustic fingerprints, and EQ baking.
            </p>
          </div>
          <Badge variant={ffStatus?.installed ? "emerald" : "danger"}>
            {ffStatus?.installed ? "Installed" : "Not Found"}
          </Badge>
        </div>

        <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] px-3.5 py-2.5 text-xs">
          <span className="text-zinc-400">Detected Binary Path: </span>
          <span className="font-mono text-zinc-200 break-all">
            {ffStatus?.path || "Not detected on PATH or bundled bin/ folder"}
          </span>
        </div>

        {ffProgress && (
          <div className="rounded-xl bg-emerald-500/10 border border-emerald-500/25 p-3 space-y-1.5">
            <div className="flex items-center justify-between text-xs font-mono text-emerald-300 tabular-nums">
              <span className="truncate">{ffProgress.message}</span>
              <span>{Math.round(ffProgress.percent)}%</span>
            </div>
            <div className="h-1.5 w-full rounded-full bg-black/40 overflow-hidden">
              <div
                className="h-full bg-emerald-bright transition-all"
                style={{
                  width: `${Math.max(4, Math.min(100, ffProgress.percent))}%`,
                }}
              />
            </div>
          </div>
        )}

        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            disabled={installingFfmpeg}
            onClick={() => void handleInstallFfmpeg()}
          >
            {installingFfmpeg ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Download className="h-3.5 w-3.5" />
            )}
            {installingFfmpeg
              ? "Downloading FFmpeg..."
              : ffStatus?.installed
                ? "Reinstall / Update Standalone FFmpeg"
                : "Download & Install Standalone FFmpeg"}
          </Button>

          <Button
            type="button"
            variant="secondary"
            onClick={() => void api.settings.openFolder()}
          >
            <FolderOpen className="h-3.5 w-3.5" />
            Open Music Folder
          </Button>

          <Button
            type="button"
            variant="secondary"
            disabled={cleaning}
            onClick={() => void handleQuickClean()}
          >
            {cleaning ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Sparkles className="h-3.5 w-3.5" />
            )}
            Clean Corrupt Files & Cache
          </Button>
        </div>
      </div>

      {/* Quick Launch into Audio Tools Studio */}
      <div className="glass-panel rounded-2xl p-6 space-y-4">
        <div className="flex items-center gap-2">
          <Wrench className="h-4 w-4 text-emerald-bright" />
          <h3 className="text-base font-semibold text-white">
            Open Audio Tools Studio Workflows
          </h3>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {(
            [
              [
                "spectrum",
                "Spectrum Audit",
                "Scan ultrasonic cutoffs & upgrade upscales",
                Activity,
              ],
              [
                "duplicates",
                "Duplicate Merger",
                "Chromaprint match & NTFS hard-linking",
                CopyCheck,
              ],
              [
                "loudness",
                "Volume & ReplayGain",
                "Batch EBU R128 loudness & ReplayGain 2.0",
                Volume2,
              ],
              [
                "maintenance",
                "Auto-Repair & Genres",
                "Heal missing covers/lyrics & retag genres",
                FolderSync,
              ],
              [
                "exporters",
                "Device & .m3u8 Export",
                "Copy/transcode collections for mobile & DAPs",
                FileAudio,
              ],
            ] as const
          ).map(([tab, title, desc, Icon]) => (
            <button
              key={tab}
              type="button"
              onClick={() => navigate(`/tools?tab=${tab}`)}
              className="group rounded-xl border border-white/[0.08] bg-white/[0.02] p-4 text-left hover:border-emerald-500/40 hover:bg-emerald-500/[0.06] transition-all cursor-pointer"
            >
              <div className="flex items-center justify-between">
                <Icon className="h-4 w-4 text-emerald-300" />
                <ArrowRight className="h-3.5 w-3.5 text-zinc-500 group-hover:text-emerald-300 transition-colors" />
              </div>
              <div className="mt-2 text-xs font-semibold text-white">
                {title}
              </div>
              <div className="mt-0.5 text-[11px] text-zinc-400">{desc}</div>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
