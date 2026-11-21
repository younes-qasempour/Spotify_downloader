import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Disc3,
  FolderCog,
  FolderOpen,
  Radio,
  Smartphone,
  Subtitles,
  Wrench,
  type LucideIcon,
} from "lucide-react";
import { toast } from "sonner";
import { api } from "@/api/endpoints";
import type { SettingsResponse } from "@/api/types";
import { DownloadsFormatsSection } from "@/components/settings/DownloadsFormatsSection";
import { FfmpegMaintenanceSection } from "@/components/settings/FfmpegMaintenanceSection";
import { LyricsAudioSection } from "@/components/settings/LyricsAudioSection";
import { MobileSyncSection } from "@/components/settings/MobileSyncSection";
import { SourcesSettingsSection } from "@/components/settings/SourcesSettingsSection";
import { SpotifySettingsSection } from "@/components/settings/SpotifySettingsSection";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

type SettingsSection =
  | "sources"
  | "spotify"
  | "downloads"
  | "lyrics"
  | "ffmpeg"
  | "mobile";

const SECTIONS: Array<{ id: SettingsSection; label: string; icon: LucideIcon }> =
  [
    { id: "sources", label: "Audio Sources & Auth", icon: Radio },
    { id: "spotify", label: "Spotify API", icon: Disc3 },
    { id: "downloads", label: "Downloads & Formats", icon: FolderCog },
    { id: "lyrics", label: "Lyrics & Loudness", icon: Subtitles },
    { id: "ffmpeg", label: "FFmpeg & Maintenance", icon: Wrench },
    { id: "mobile", label: "Android & Mobile Sync", icon: Smartphone },
  ];

function isValidSection(raw: string | null): raw is SettingsSection {
  return SECTIONS.some((s) => s.id === raw);
}

export function SettingsPage() {
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const rawSection = searchParams.get("section");
  const activeSection: SettingsSection = isValidSection(rawSection)
    ? rawSection
    : "sources";

  const [patching, setPatching] = useState(false);

  const { data, isLoading } = useQuery({
    queryKey: ["settings"],
    queryFn: () => api.settings.get(),
  });

  const handlePatch = async (
    values: Record<string, unknown>,
    toastMsg?: string
  ) => {
    if (patching) return;
    setPatching(true);
    try {
      const res = await api.settings.patch(values);
      const cleanSettings: SettingsResponse = {
        config: res.config,
        secrets_set: res.secrets_set,
        derived: res.derived,
      };
      queryClient.setQueryData(["settings"], cleanSettings);
      void queryClient.invalidateQueries({ queryKey: ["queue"] });
      if (toastMsg) {
        toast.success(toastMsg);
      }
    } catch (err) {
      toast.error("Could not update settings", {
        description: err instanceof Error ? err.message : undefined,
      });
    } finally {
      setPatching(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Live Overview Header */}
      <div className="glass-panel rounded-2xl p-5 flex flex-wrap items-center justify-between gap-4">
        {isLoading || !data ? (
          <div className="space-y-2 w-full">
            <Skeleton className="h-5 w-60" />
            <Skeleton className="h-4 w-96" />
          </div>
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-3 text-xs">
              <div className="rounded-xl bg-white/[0.03] border border-white/[0.07] px-3.5 py-2">
                <span className="text-zinc-400">Engine: </span>
                <span className="font-mono font-semibold text-white">
                  {data.derived.effective_source_engine === "melobot"
                    ? "MeloBot Telegram"
                    : "Musilon VIP CDN"}
                </span>
              </div>
              <div className="rounded-xl bg-white/[0.03] border border-white/[0.07] px-3.5 py-2">
                <span className="text-zinc-400">Workers: </span>
                <span className="font-mono font-semibold text-white tabular-nums">
                  {data.derived.effective_concurrency}
                </span>
              </div>
              <div className="rounded-xl bg-white/[0.03] border border-white/[0.07] px-3.5 py-2 max-w-xs truncate">
                <span className="text-zinc-400">Folder: </span>
                <span className="font-mono text-zinc-200">
                  {data.config.download.output_dir || "Default"}
                </span>
              </div>
              <Badge variant="emerald" className="uppercase font-mono text-[10px]">
                {data.config.download.preferred_quality === "flac"
                  ? "FLAC Priority"
                  : "MP3 320 Priority"}{" "}
                · {(data.config.download.target_format || "original").toUpperCase()}
              </Badge>
            </div>

            <Button
              type="button"
              size="sm"
              variant="secondary"
              onClick={() => void api.settings.openFolder()}
            >
              <FolderOpen className="h-3.5 w-3.5" />
              Open Downloads Folder
            </Button>
          </>
        )}
      </div>

      {/* Category Pills */}
      <div className="flex flex-wrap items-center gap-2">
        {SECTIONS.map((sec) => {
          const Icon = sec.icon;
          const active = activeSection === sec.id;
          return (
            <button
              key={sec.id}
              type="button"
              onClick={() => setSearchParams({ section: sec.id }, { replace: true })}
              className={cn(
                "inline-flex items-center gap-2 rounded-full px-4 py-2 text-xs font-medium transition-all cursor-pointer border",
                active
                  ? "bg-emerald-500/20 text-emerald-300 border-emerald-500/45 shadow-sm shadow-emerald-500/10"
                  : "bg-white/[0.03] text-zinc-400 border-white/[0.07] hover:bg-white/[0.06] hover:text-zinc-200"
              )}
            >
              <Icon className="h-3.5 w-3.5" />
              {sec.label}
            </button>
          );
        })}
      </div>

      {isLoading || !data ? (
        <div className="glass-panel rounded-2xl p-6 space-y-4">
          <Skeleton className="h-6 w-52" />
          <Skeleton className="h-24 w-full rounded-xl" />
          <Skeleton className="h-24 w-full rounded-xl" />
        </div>
      ) : (
        <>
          {activeSection === "sources" && (
            <SourcesSettingsSection
              settings={data}
              onPatch={handlePatch}
              patching={patching}
            />
          )}
          {activeSection === "spotify" && (
            <SpotifySettingsSection settings={data} />
          )}
          {activeSection === "downloads" && (
            <DownloadsFormatsSection
              settings={data}
              onPatch={handlePatch}
              patching={patching}
            />
          )}
          {activeSection === "lyrics" && (
            <LyricsAudioSection
              settings={data}
              onPatch={handlePatch}
              patching={patching}
            />
          )}
          {activeSection === "ffmpeg" && <FfmpegMaintenanceSection />}
          {activeSection === "mobile" && (
            <MobileSyncSection
              settings={data}
              onPatch={handlePatch}
              patching={patching}
            />
          )}
        </>
      )}
    </div>
  );
}
