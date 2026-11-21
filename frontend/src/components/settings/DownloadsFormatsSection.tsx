import { useEffect, useState } from "react";
import { FolderOpen, FolderSearch, Lock, Save, Sliders } from "lucide-react";
import { api } from "@/api/endpoints";
import type { SettingsResponse } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { isDesktopApp, pickDirectory, pickFile } from "@/lib/desktop";
import { cn } from "@/lib/utils";

interface DownloadsFormatsSectionProps {
  settings: SettingsResponse;
  onPatch: (values: Record<string, unknown>, toastMsg?: string) => Promise<void>;
  patching: boolean;
}

const TARGET_FORMATS = [
  { id: "original", label: "Original / Native Stream", hint: "FLAC / MP3 lossless passthrough" },
  { id: "alac", label: "Apple Lossless ALAC (.m4a)", hint: "For iPhone & Apple Music" },
  { id: "mp3", label: "MP3 320 kbps CBR", hint: "Universal car / hardware compatibility" },
  { id: "flac", label: "Lossless FLAC", hint: "Convert any stream to FLAC" },
  { id: "opus", label: "Opus 256 kbps", hint: "Compact archival transparency" },
] as const;

const TOKENS = ["{artist}", "{title}", "{album}", "{track_number}", "{playlist}"];

export function DownloadsFormatsSection({
  settings,
  onPatch,
  patching,
}: DownloadsFormatsSectionProps) {
  const dl = settings.config.download;

  const [outputDir, setOutputDir] = useState(dl.output_dir || "");
  const [namingTemplate, setNamingTemplate] = useState(
    dl.naming_template || "{artist} - {title}"
  );
  const [albumTemplate, setAlbumTemplate] = useState(
    dl.album_naming_template || "{track_number}. {title}"
  );
  const [concurrency, setConcurrency] = useState(dl.concurrency || 5);
  const [cookiesFile, setCookiesFile] = useState(dl.cookies_file || "");
  const [proxy, setProxy] = useState(dl.proxy || "");

  useEffect(() => {
    setOutputDir(dl.output_dir || "");
    setNamingTemplate(dl.naming_template || "{artist} - {title}");
    setAlbumTemplate(dl.album_naming_template || "{track_number}. {title}");
    setConcurrency(dl.concurrency || 5);
    setCookiesFile(dl.cookies_file || "");
    setProxy(dl.proxy || "");
  }, [
    dl.album_naming_template,
    dl.concurrency,
    dl.cookies_file,
    dl.naming_template,
    dl.output_dir,
    dl.proxy,
  ]);

  const handleSavePathsAndNetwork = (e: React.FormEvent) => {
    e.preventDefault();
    const values: Record<string, unknown> = {
      "download.output_dir": outputDir.trim(),
      "download.naming_template": namingTemplate.trim() || "{artist} - {title}",
      "download.album_naming_template":
        albumTemplate.trim() || "{track_number}. {title}",
      "download.cookies_file": cookiesFile.trim(),
      "download.proxy": proxy.trim(),
    };
    if (!settings.derived.concurrency_locked) {
      values["download.concurrency"] = concurrency;
    }
    void onPatch(values, "Download paths & network settings saved");
  };

  return (
    <div className="space-y-5">
      {/* Quality & Output Format */}
      <div className="glass-panel rounded-2xl p-6 space-y-5">
        <div className="flex items-center gap-2.5">
          <Sliders className="h-4 w-4 text-emerald-bright" />
          <h2 className="text-base font-semibold text-white">
            Audio Quality & Format Conversion
          </h2>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <button
            type="button"
            disabled={patching}
            onClick={() =>
              void onPatch(
                { "download.preferred_quality": "flac" },
                "Preferred quality set to Lossless FLAC"
              )
            }
            className={cn(
              "rounded-2xl border p-4 text-left transition-all cursor-pointer",
              dl.preferred_quality === "flac"
                ? "border-emerald-500/50 bg-emerald-500/[0.09]"
                : "border-white/10 bg-white/[0.02] hover:bg-white/[0.05]"
            )}
          >
            <div className="flex items-center justify-between">
              <span className="text-sm font-semibold text-white">
                Lossless FLAC (16/24-bit Priority)
              </span>
              {dl.preferred_quality === "flac" && (
                <Badge variant="emerald">Active</Badge>
              )}
            </div>
            <p className="text-xs text-zinc-400 mt-1">
              Prioritizes bit-perfect CD/Hi-Res FLAC before MP3 320 or Opus.
            </p>
          </button>

          <button
            type="button"
            disabled={patching}
            onClick={() =>
              void onPatch(
                { "download.preferred_quality": "320" },
                "Preferred quality set to MP3 320 kbps"
              )
            }
            className={cn(
              "rounded-2xl border p-4 text-left transition-all cursor-pointer",
              dl.preferred_quality === "320"
                ? "border-sky-500/50 bg-sky-500/[0.09]"
                : "border-white/10 bg-white/[0.02] hover:bg-white/[0.05]"
            )}
          >
            <div className="flex items-center justify-between">
              <span className="text-sm font-semibold text-white">
                High Efficiency MP3 320 kbps Priority
              </span>
              {dl.preferred_quality === "320" && (
                <Badge variant="sky">Active</Badge>
              )}
            </div>
            <p className="text-xs text-zinc-400 mt-1">
              Smaller footprint with fast downloads, prioritizing 320k CBR.
            </p>
          </button>
        </div>

        <div className="space-y-1.5">
          <label className="text-xs font-medium text-zinc-300">
            Post-Download Target Format
          </label>
          <select
            value={dl.target_format || "original"}
            disabled={patching}
            onChange={(e) =>
              void onPatch(
                { "download.target_format": e.target.value },
                `Target output format set to ${e.target.value.toUpperCase()}`
              )
            }
            className="h-10 w-full rounded-xl border border-white/10 bg-elevated px-3 text-sm text-zinc-100 focus:border-emerald-500/60 focus:outline-none cursor-pointer"
          >
            {TARGET_FORMATS.map((fmt) => (
              <option key={fmt.id} value={fmt.id}>
                {fmt.label} — {fmt.hint}
              </option>
            ))}
          </select>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 pt-1">
          <label className="flex items-center justify-between gap-3 rounded-xl border border-white/[0.07] bg-white/[0.02] px-3.5 py-2.5 text-xs text-zinc-200 cursor-pointer">
            <div>
              <div>Organize Playlists & Albums into Subfolders</div>
              <div className="text-[11px] text-zinc-400">
                Off = all downloads saved into one single folder
              </div>
            </div>
            <input
              type="checkbox"
              checked={dl.save_in_subfolders}
              onChange={(e) =>
                void onPatch({ "download.save_in_subfolders": e.target.checked })
              }
              className="h-4 w-4 shrink-0 accent-emerald-500"
            />
          </label>

          <label className="flex items-center justify-between rounded-xl border border-white/[0.07] bg-white/[0.02] px-3.5 py-2.5 text-xs text-zinc-200 cursor-pointer">
            <span>YouTube Music Safety-Net Fallback</span>
            <input
              type="checkbox"
              checked={dl.allow_fallback}
              onChange={(e) =>
                void onPatch({ "download.allow_fallback": e.target.checked })
              }
              className="h-4 w-4 accent-emerald-500"
            />
          </label>
        </div>
      </div>

      {/* Folders, Naming & Concurrency */}
      <form
        onSubmit={handleSavePathsAndNetwork}
        className="glass-panel rounded-2xl p-6 space-y-4"
      >
        <div className="flex items-center justify-between gap-2">
          <h3 className="text-base font-semibold text-white">
            Output Directory, Templates & Network
          </h3>
          <Button
            type="button"
            size="sm"
            variant="secondary"
            onClick={() => void api.settings.openFolder(outputDir || undefined)}
          >
            <FolderOpen className="h-3.5 w-3.5" />
            Open Folder
          </Button>
        </div>

        <div className="space-y-1.5">
          <label className="text-xs font-medium text-zinc-300">
            Music Output Directory
          </label>
          <div className="flex items-center gap-2">
            <Input
              value={outputDir}
              onChange={(e) => setOutputDir(e.target.value)}
              placeholder="C:\Users\...\Music\Flacify"
              className="font-mono text-xs flex-1"
            />
            {isDesktopApp() && (
              <Button
                type="button"
                size="sm"
                variant="secondary"
                onClick={async () => {
                  const chosen = await pickDirectory(
                    "Select Music Output Folder",
                    outputDir
                  );
                  if (chosen) setOutputDir(chosen);
                }}
              >
                <FolderSearch className="h-3.5 w-3.5" />
                Browse
              </Button>
            )}
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-zinc-300">
              Single / Playlist Track Template
            </label>
            <Input
              value={namingTemplate}
              onChange={(e) => setNamingTemplate(e.target.value)}
              className="font-mono text-xs"
            />
          </div>
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-zinc-300">
              Album Track Template
            </label>
            <Input
              value={albumTemplate}
              onChange={(e) => setAlbumTemplate(e.target.value)}
              className="font-mono text-xs"
            />
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-zinc-400">
          <span>Available tokens:</span>
          {TOKENS.map((tok) => (
            <button
              key={tok}
              type="button"
              onClick={() => setNamingTemplate((v) => `${v} ${tok}`.trim())}
              className="rounded-md bg-white/[0.05] px-2 py-0.5 font-mono text-zinc-200 hover:bg-emerald-500/20 hover:text-emerald-300 cursor-pointer"
              title="Append to track naming template"
            >
              {tok}
            </button>
          ))}
        </div>

        <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] p-4 space-y-2">
          <div className="flex items-center justify-between gap-2 text-xs">
            <span className="font-medium text-zinc-200 flex items-center gap-1.5">
              Concurrent Download Workers (1–10)
              {settings.derived.concurrency_locked && (
                <Badge variant="gold" className="text-[10px]">
                  <Lock className="h-3 w-3" />
                  Locked to 1 by MeloBot
                </Badge>
              )}
            </span>
            <span className="font-mono font-bold text-emerald-300 tabular-nums">
              {settings.derived.concurrency_locked ? 1 : concurrency} worker(s)
            </span>
          </div>
          <input
            type="range"
            min={1}
            max={10}
            step={1}
            disabled={settings.derived.concurrency_locked}
            value={settings.derived.concurrency_locked ? 1 : concurrency}
            onChange={(e) => setConcurrency(Number(e.target.value))}
            className="w-full accent-emerald-500 disabled:opacity-40 cursor-pointer"
          />
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-zinc-300">
              YouTube Music cookies.txt Path (Optional)
            </label>
            <div className="flex items-center gap-2">
              <Input
                value={cookiesFile}
                onChange={(e) => setCookiesFile(e.target.value)}
                placeholder="Path to Netscape cookies.txt"
                className="font-mono text-xs flex-1"
              />
              {isDesktopApp() && (
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  onClick={async () => {
                    const chosen = await pickFile(
                      "Select YouTube cookies.txt",
                      [{ name: "Netscape Cookies", extensions: ["txt"] }],
                      cookiesFile
                    );
                    if (chosen) setCookiesFile(chosen);
                  }}
                >
                  Browse
                </Button>
              )}
            </div>
          </div>
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-zinc-300">
              HTTP / SOCKS5 Proxy URL (Optional)
            </label>
            <Input
              value={proxy}
              onChange={(e) => setProxy(e.target.value)}
              placeholder="http://127.0.0.1:7890"
              className="font-mono text-xs"
            />
          </div>
        </div>

        <div className="flex justify-end pt-2 border-t border-white/[0.06]">
          <Button type="submit" disabled={patching}>
            <Save className="h-3.5 w-3.5" />
            Save Folders, Templates & Network
          </Button>
        </div>
      </form>
    </div>
  );
}
