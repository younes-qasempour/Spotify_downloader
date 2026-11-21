import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { FolderSync, Loader2, Sparkles, Tags, Wrench } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/api/endpoints";
import type {
  CleanLibraryResponse,
  OrganizeLibraryResponse,
  RepairLibraryResponse,
  RetagGenresResponse,
} from "@/api/types";
import { Button } from "@/components/ui/button";
import { useAppStore } from "@/stores/appStore";

export function MaintenanceToolsPanel() {
  const queryClient = useQueryClient();
  const activeToolProgress = useAppStore((s) => s.activeToolProgress);

  const [organizing, setOrganizing] = useState(false);
  const [organizeStats, setOrganizeStats] =
    useState<OrganizeLibraryResponse | null>(null);

  const [cleaning, setCleaning] = useState(false);
  const [cleanStats, setCleanStats] = useState<CleanLibraryResponse | null>(
    null
  );

  const [repairing, setRepairing] = useState(false);
  const [repairStats, setRepairStats] = useState<RepairLibraryResponse | null>(
    null
  );

  const [retagging, setRetagging] = useState(false);
  const [retagStats, setRetagStats] = useState<RetagGenresResponse | null>(
    null
  );

  const handleOrganize = async () => {
    if (organizing) return;
    setOrganizing(true);
    try {
      const res = await api.tools.organizeLibrary({
        enforce_single_folder: true,
      });
      setOrganizeStats(res);
      void queryClient.invalidateQueries({ queryKey: ["library"] });
      void queryClient.invalidateQueries({ queryKey: ["playlists"] });
      void queryClient.invalidateQueries({ queryKey: ["settings"] });
      toast.success("Single Folder & DB Organization Complete", {
        description: `${res.files_moved} file(s) consolidated · ${res.duplicate_db_rows_removed} duplicate DB row(s) removed`,
      });
    } catch (err) {
      toast.error("Library organization failed", {
        description: err instanceof Error ? err.message : undefined,
      });
    } finally {
      setOrganizing(false);
    }
  };

  const handleClean = async () => {
    if (cleaning) return;
    setCleaning(true);
    try {
      const res = await api.tools.cleanLibrary();
      setCleanStats(res);
      void queryClient.invalidateQueries({ queryKey: ["library"] });
      toast.success("Library Cleanup Complete", {
        description: `${res.purged_corrupt_files} corrupt file(s) purged · ${res.purged_db_records} stale DB record(s) removed`,
      });
    } catch (err) {
      toast.error("Library cleanup failed", {
        description: err instanceof Error ? err.message : undefined,
      });
    } finally {
      setCleaning(false);
    }
  };

  const handleRepair = async () => {
    if (repairing) return;
    setRepairing(true);
    setRepairStats(null);
    try {
      const res = await api.tools.repairLibrary();
      setRepairStats(res);
      void queryClient.invalidateQueries({ queryKey: ["library"] });
      toast.success("Library Auto-Repair Complete", {
        description: `${res.healed_covers} cover(s) healed · ${res.healed_lyrics} lyric(s) healed`,
      });
    } catch (err) {
      toast.error("Library repair failed", {
        description: err instanceof Error ? err.message : undefined,
      });
    } finally {
      setRepairing(false);
    }
  };

  const handleRetagGenres = async () => {
    if (retagging) return;
    setRetagging(true);
    setRetagStats(null);
    try {
      const res = await api.tools.retagGenres();
      setRetagStats(res);
      void queryClient.invalidateQueries({ queryKey: ["library"] });
      toast.success("Genre Retagging Complete", {
        description: `${res.retagged} track(s) updated · ${res.already_tagged} already tagged`,
      });
    } catch (err) {
      toast.error("Genre retagging failed", {
        description: err instanceof Error ? err.message : undefined,
      });
    } finally {
      setRetagging(false);
    }
  };

  const repairProgress =
    repairing && activeToolProgress?.tool === "repair_library"
      ? activeToolProgress
      : null;
  const retagProgress =
    retagging && activeToolProgress?.tool === "retag_genres"
      ? activeToolProgress
      : null;

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
      {/* Consolidate Single Folder & Organize DB */}
      <div className="glass-panel rounded-2xl p-6 space-y-4 flex flex-col justify-between">
        <div className="space-y-3">
          <div className="flex items-start gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-sky-500/15 text-sky-300 border border-sky-500/25">
              <FolderSync className="h-5 w-5" />
            </div>
            <div>
              <h2 className="text-base font-semibold text-white">
                Consolidate Single Folder & Organize DB
              </h2>
              <p className="text-xs text-zinc-400 mt-0.5 leading-relaxed">
                Moves any downloaded tracks in subfolders or temp directories into
                your single music folder, enforces flat downloads, removes duplicate
                or dead DB rows, and compacts the SQLite database.
              </p>
            </div>
          </div>

          {organizeStats && (
            <div className="rounded-xl bg-white/[0.03] border border-white/[0.06] p-3 text-xs space-y-1 font-mono">
              <div className="flex justify-between text-zinc-300">
                <span>Files Consolidated</span>
                <span className="text-sky-300 font-bold tabular-nums">
                  {organizeStats.files_moved}
                </span>
              </div>
              <div className="flex justify-between text-zinc-300">
                <span>Duplicate DB Rows Removed</span>
                <span className="text-emerald-300 font-bold tabular-nums">
                  {organizeStats.duplicate_db_rows_removed}
                </span>
              </div>
              <div className="flex justify-between text-zinc-300">
                <span>Ghost DB Rows Purged</span>
                <span className="text-white font-bold tabular-nums">
                  {organizeStats.missing_db_rows_removed}
                </span>
              </div>
              <div className="flex justify-between text-zinc-300">
                <span>Metadata Records Enriched</span>
                <span className="text-white font-bold tabular-nums">
                  {organizeStats.metadata_enriched}
                </span>
              </div>
            </div>
          )}
        </div>

        <Button
          type="button"
          disabled={organizing}
          onClick={() => void handleOrganize()}
          className="w-full"
        >
          {organizing ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <FolderSync className="h-4 w-4" />
          )}
          {organizing
            ? "Consolidating & Organizing..."
            : "Consolidate Folder & Organize DB"}
        </Button>
      </div>

      {/* Clean Corrupt Files & Cache */}
      <div className="glass-panel rounded-2xl p-6 space-y-4 flex flex-col justify-between">
        <div className="space-y-3">
          <div className="flex items-start gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-amber-500/15 text-amber-300 border border-amber-500/25">
              <Sparkles className="h-5 w-5" />
            </div>
            <div>
              <h2 className="text-base font-semibold text-white">
                Clean Corrupt Files & Cache
              </h2>
              <p className="text-xs text-zinc-400 mt-0.5 leading-relaxed">
                Purges broken HTML downloads, deletes dead DB entries, migrates
                stray folder artwork into cache, and organizes loose `.lrc`
                files.
              </p>
            </div>
          </div>

          {cleanStats && (
            <div className="rounded-xl bg-white/[0.03] border border-white/[0.06] p-3 text-xs space-y-1 font-mono">
              <div className="flex justify-between text-zinc-300">
                <span>Corrupt Audio Purged</span>
                <span className="text-white font-bold tabular-nums">
                  {cleanStats.purged_corrupt_files}
                </span>
              </div>
              <div className="flex justify-between text-zinc-300">
                <span>Stale DB Records Removed</span>
                <span className="text-white font-bold tabular-nums">
                  {cleanStats.purged_db_records}
                </span>
              </div>
              <div className="flex justify-between text-zinc-300">
                <span>Relocated Folder Covers</span>
                <span className="text-white font-bold tabular-nums">
                  {cleanStats.relocated_covers}
                </span>
              </div>
              <div className="flex justify-between text-zinc-300">
                <span>Reorganized .lrc Lyrics</span>
                <span className="text-white font-bold tabular-nums">
                  {cleanStats.reorganized_lyrics}
                </span>
              </div>
            </div>
          )}
        </div>

        <Button
          type="button"
          disabled={cleaning}
          onClick={() => void handleClean()}
          className="w-full"
        >
          {cleaning ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Sparkles className="h-4 w-4" />
          )}
          {cleaning ? "Cleaning Library..." : "Clean Library & Purge Corrupt"}
        </Button>
      </div>

      {/* Auto-Repair Covers & Lyrics */}
      <div className="glass-panel rounded-2xl p-6 space-y-4 flex flex-col justify-between">
        <div className="space-y-3">
          <div className="flex items-start gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-emerald-500/15 text-emerald-300 border border-emerald-500/25">
              <Wrench className="h-5 w-5" />
            </div>
            <div>
              <h2 className="text-base font-semibold text-white">
                Auto-Repair Covers & Lyrics
              </h2>
              <p className="text-xs text-zinc-400 mt-0.5 leading-relaxed">
                Audits every audio file for missing front cover art or lyrics,
                fetches them via Spotify/LRCLIB, and losslessly embeds them.
              </p>
            </div>
          </div>

          {repairProgress && (
            <div className="rounded-xl bg-emerald-500/10 border border-emerald-500/25 p-3 space-y-1.5">
              <div className="flex items-center justify-between text-[11px] font-mono text-emerald-300 tabular-nums">
                <span className="truncate">{repairProgress.message}</span>
                <span>{Math.round(repairProgress.percent)}%</span>
              </div>
              <div className="h-1.5 w-full rounded-full bg-black/40 overflow-hidden">
                <div
                  className="h-full bg-emerald-bright transition-all"
                  style={{
                    width: `${Math.max(4, Math.min(100, repairProgress.percent))}%`,
                  }}
                />
              </div>
            </div>
          )}

          {repairStats && (
            <div className="rounded-xl bg-white/[0.03] border border-white/[0.06] p-3 text-xs space-y-1 font-mono">
              <div className="flex justify-between text-zinc-300">
                <span>Tracks Scanned</span>
                <span className="text-white font-bold tabular-nums">
                  {repairStats.scanned}
                </span>
              </div>
              <div className="flex justify-between text-zinc-300">
                <span>Covers Healed / Missing</span>
                <span className="text-emerald-300 font-bold tabular-nums">
                  {repairStats.healed_covers} / {repairStats.missing_covers_found}
                </span>
              </div>
              <div className="flex justify-between text-zinc-300">
                <span>Lyrics Healed / Missing</span>
                <span className="text-emerald-300 font-bold tabular-nums">
                  {repairStats.healed_lyrics} / {repairStats.missing_lyrics_found}
                </span>
              </div>
              <div className="flex justify-between text-zinc-300">
                <span>Errors</span>
                <span className="text-red-300 font-bold tabular-nums">
                  {repairStats.errors}
                </span>
              </div>
            </div>
          )}
        </div>

        <Button
          type="button"
          disabled={repairing}
          onClick={() => void handleRepair()}
          className="w-full"
        >
          {repairing ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Wrench className="h-4 w-4" />
          )}
          {repairing ? "Repairing Library..." : "Scan & Auto-Repair Library"}
        </Button>
      </div>

      {/* Batch Retag Missing Genres */}
      <div className="glass-panel rounded-2xl p-6 space-y-4 flex flex-col justify-between">
        <div className="space-y-3">
          <div className="flex items-start gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-violet-500/15 text-violet-300 border border-violet-500/25">
              <Tags className="h-5 w-5" />
            </div>
            <div>
              <h2 className="text-base font-semibold text-white">
                Batch Retag Missing Genres
              </h2>
              <p className="text-xs text-zinc-400 mt-0.5 leading-relaxed">
                Detects library files lacking genre metadata, resolves clean
                genres from iTunes/MusicBrainz/Spotify, and updates both file
                tags and the archive DB.
              </p>
            </div>
          </div>

          {retagProgress && (
            <div className="rounded-xl bg-violet-500/10 border border-violet-500/25 p-3 space-y-1.5">
              <div className="flex items-center justify-between text-[11px] font-mono text-violet-300 tabular-nums">
                <span className="truncate">{retagProgress.message}</span>
                <span>{Math.round(retagProgress.percent)}%</span>
              </div>
              <div className="h-1.5 w-full rounded-full bg-black/40 overflow-hidden">
                <div
                  className="h-full bg-violet-400 transition-all"
                  style={{
                    width: `${Math.max(4, Math.min(100, retagProgress.percent))}%`,
                  }}
                />
              </div>
            </div>
          )}

          {retagStats && (
            <div className="rounded-xl bg-white/[0.03] border border-white/[0.06] p-3 text-xs space-y-1 font-mono">
              <div className="flex justify-between text-zinc-300">
                <span>Tracks Scanned</span>
                <span className="text-white font-bold tabular-nums">
                  {retagStats.scanned}
                </span>
              </div>
              <div className="flex justify-between text-zinc-300">
                <span>Retagged</span>
                <span className="text-emerald-300 font-bold tabular-nums">
                  {retagStats.retagged}
                </span>
              </div>
              <div className="flex justify-between text-zinc-300">
                <span>Already Tagged</span>
                <span className="text-zinc-200 font-bold tabular-nums">
                  {retagStats.already_tagged}
                </span>
              </div>
              <div className="flex justify-between text-zinc-300">
                <span>Errors</span>
                <span className="text-red-300 font-bold tabular-nums">
                  {retagStats.errors}
                </span>
              </div>
            </div>
          )}
        </div>

        <Button
          type="button"
          disabled={retagging}
          onClick={() => void handleRetagGenres()}
          className="w-full"
        >
          {retagging ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Tags className="h-4 w-4" />
          )}
          {retagging ? "Retagging Genres..." : "Scan & Retag Missing Genres"}
        </Button>
      </div>
    </div>
  );
}
