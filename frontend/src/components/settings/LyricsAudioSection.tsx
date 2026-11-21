import { useEffect, useState } from "react";
import { FileText, Subtitles, Volume2 } from "lucide-react";
import type { SettingsResponse } from "@/api/types";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface LyricsAudioSectionProps {
  settings: SettingsResponse;
  onPatch: (values: Record<string, unknown>, toastMsg?: string) => Promise<void>;
  patching: boolean;
}

const LYRICS_MODES = [
  {
    id: "embedded_only",
    title: "Embedded Only (Clean Folders)",
    desc: "Stores synced & unsynced lyrics cleanly inside audio tags with no extra .lrc files.",
  },
  {
    id: "separate_folder",
    title: "Dedicated lyrics/ Subfolder",
    desc: "Saves external .lrc files neatly into a lyrics/ subfolder beside your music.",
  },
  {
    id: "same_folder",
    title: "Alongside Audio Files",
    desc: "Places Track.lrc right next to Track.flac for DAPs that require matching stems.",
  },
] as const;

export function LyricsAudioSection({
  settings,
  onPatch,
  patching,
}: LyricsAudioSectionProps) {
  const dl = settings.config.download;
  const ui = settings.config.ui;

  const [targetLufs, setTargetLufs] = useState(dl.target_lufs ?? -9.0);

  useEffect(() => {
    setTargetLufs(dl.target_lufs ?? -9.0);
  }, [dl.target_lufs]);

  return (
    <div className="space-y-5">
      {/* Lyrics Storage Mode */}
      <div className="glass-panel rounded-2xl p-6 space-y-4">
        <div className="flex items-center gap-2.5">
          <Subtitles className="h-4 w-4 text-emerald-bright" />
          <div>
            <h2 className="text-base font-semibold text-white">
              Lyrics & Sidecar Output Mode
            </h2>
            <p className="text-xs text-zinc-400">
              Controls how synced LRC files and embedded lyric tags are written.
            </p>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {LYRICS_MODES.map((m) => {
            const active = dl.lyrics_mode === m.id;
            return (
              <button
                key={m.id}
                type="button"
                disabled={patching}
                onClick={() =>
                  void onPatch(
                    { "download.lyrics_mode": m.id },
                    `Lyrics mode set to ${m.title}`
                  )
                }
                className={cn(
                  "rounded-2xl border p-4 text-left transition-all cursor-pointer",
                  active
                    ? "border-emerald-500/50 bg-emerald-500/[0.09]"
                    : "border-white/10 bg-white/[0.02] hover:bg-white/[0.05]"
                )}
              >
                <div className="text-xs font-semibold text-white">{m.title}</div>
                <p className="text-[11px] text-zinc-400 mt-1.5 leading-relaxed">
                  {m.desc}
                </p>
              </button>
            );
          })}
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 pt-1">
          <label className="flex items-center justify-between rounded-xl border border-white/[0.07] bg-white/[0.02] px-3.5 py-2.5 text-xs text-zinc-200 cursor-pointer">
            <span>Embed Lyrics inside Audio Tags</span>
            <input
              type="checkbox"
              checked={dl.embed_lyrics}
              onChange={(e) =>
                void onPatch({ "download.embed_lyrics": e.target.checked })
              }
              className="h-4 w-4 accent-emerald-500"
            />
          </label>

          <label className="flex items-center justify-between rounded-xl border border-white/[0.07] bg-white/[0.02] px-3.5 py-2.5 text-xs text-zinc-200 cursor-pointer">
            <span>Embed High-Res Front Cover Artwork</span>
            <input
              type="checkbox"
              checked={dl.embed_cover_art}
              onChange={(e) =>
                void onPatch({ "download.embed_cover_art": e.target.checked })
              }
              className="h-4 w-4 accent-emerald-500"
            />
          </label>

          <label className="flex items-center justify-between rounded-xl border border-white/[0.07] bg-white/[0.02] px-3.5 py-2.5 text-xs text-zinc-200 cursor-pointer">
            <span>Auto-Generate Companion .m3u8 Playlists</span>
            <input
              type="checkbox"
              checked={dl.generate_m3u8}
              onChange={(e) =>
                void onPatch({ "download.generate_m3u8": e.target.checked })
              }
              className="h-4 w-4 accent-emerald-500"
            />
          </label>

          <label className="flex items-center justify-between rounded-xl border border-white/[0.07] bg-white/[0.02] px-3.5 py-2.5 text-xs text-zinc-200 cursor-pointer">
            <span>Clipboard Spotify URL Auto-Detect</span>
            <input
              type="checkbox"
              checked={ui.clipboard_auto_detect}
              onChange={(e) =>
                void onPatch({ "ui.clipboard_auto_detect": e.target.checked })
              }
              className="h-4 w-4 accent-emerald-500"
            />
          </label>
        </div>
      </div>

      {/* Loudness & ReplayGain Automation */}
      <div className="glass-panel rounded-2xl p-6 space-y-4">
        <div className="flex items-center gap-2.5">
          <Volume2 className="h-4 w-4 text-emerald-bright" />
          <div>
            <h3 className="text-base font-semibold text-white">
              Automatic Download Loudness & ReplayGain 2.0
            </h3>
            <p className="text-xs text-zinc-400">
              Automatically level volume or write ReplayGain tags immediately as
              tracks finish downloading.
            </p>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <label className="flex items-center justify-between rounded-xl border border-white/[0.07] bg-white/[0.02] px-3.5 py-2.5 text-xs text-zinc-200 cursor-pointer">
            <span>Auto-Boost & Balance Volume (EBU R128)</span>
            <input
              type="checkbox"
              checked={dl.normalize_volume}
              onChange={(e) =>
                void onPatch({ "download.normalize_volume": e.target.checked })
              }
              className="h-4 w-4 accent-emerald-500"
            />
          </label>

          <label className="flex items-center justify-between rounded-xl border border-white/[0.07] bg-white/[0.02] px-3.5 py-2.5 text-xs text-zinc-200 cursor-pointer">
            <span>Tag ReplayGain 2.0 on Download</span>
            <input
              type="checkbox"
              checked={dl.replaygain_tagging}
              onChange={(e) =>
                void onPatch({ "download.replaygain_tagging": e.target.checked })
              }
              className="h-4 w-4 accent-emerald-500"
            />
          </label>
        </div>

        <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] p-4 space-y-3">
          <div className="flex items-center justify-between text-xs">
            <span className="font-medium text-zinc-200 flex items-center gap-1.5">
              <FileText className="h-3.5 w-3.5 text-zinc-400" />
              Default Target Loudness (LUFS)
            </span>
            <span className="font-mono font-bold text-emerald-300 tabular-nums">
              {targetLufs.toFixed(1)} LUFS
            </span>
          </div>
          <div className="flex items-center gap-3">
            <input
              type="range"
              min={-16}
              max={-6}
              step={0.5}
              value={targetLufs}
              onChange={(e) => setTargetLufs(Number(e.target.value))}
              className="flex-1 accent-emerald-500 cursor-pointer"
            />
            <Button
              type="button"
              size="sm"
              variant="secondary"
              disabled={patching}
              onClick={() =>
                void onPatch(
                  { "download.target_lufs": targetLufs },
                  `Default loudness target saved (${targetLufs.toFixed(1)} LUFS)`
                )
              }
            >
              Save LUFS
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
