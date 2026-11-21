import { useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  CheckSquare,
  ChevronDown,
  ChevronRight,
  CopyCheck,
  HardDrive,
  Link2,
  Loader2,
  Search,
  Square,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";
import { api } from "@/api/endpoints";
import type { DuplicateGroup, DuplicateMergeResponse } from "@/api/types";
import { Badge, QualityBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn, formatBytes } from "@/lib/utils";
import { useAppStore } from "@/stores/appStore";

export function DuplicateMergerPanel() {
  const queryClient = useQueryClient();
  const activeToolProgress = useAppStore((s) => s.activeToolProgress);

  const [useAcoustic, setUseAcoustic] = useState(true);
  const [scanning, setScanning] = useState(false);
  const [mergingMode, setMergingMode] = useState<"hardlink" | "merge" | null>(
    null
  );
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false);

  const [groups, setGroups] = useState<DuplicateGroup[] | null>(null);
  const [selectedKeys, setSelectedKeys] = useState<Set<string>>(new Set());
  const [expandedKeys, setExpandedKeys] = useState<Set<string>>(new Set());
  const [query, setQuery] = useState("");
  const [mergeStats, setMergeStats] = useState<DuplicateMergeResponse | null>(
    null
  );

  const handleScan = async () => {
    if (scanning) return;
    setScanning(true);
    setMergeStats(null);
    setConfirmDeleteOpen(false);
    try {
      const res = await api.tools.scanDuplicates({
        use_acoustic_fingerprint: useAcoustic,
      });
      setGroups(res.groups);
      setSelectedKeys(new Set(res.groups.map((g) => g.key)));
      setExpandedKeys(
        new Set(res.groups.slice(0, 3).map((g) => g.key))
      );
      toast.success(`Found ${res.summary.total_groups} duplicate group(s)`, {
        description: `${res.summary.redundant_files} extra copy/copies · ${formatBytes(res.summary.reclaimable_bytes)} reclaimable`,
      });
    } catch (err) {
      toast.error("Duplicate scan failed", {
        description: err instanceof Error ? err.message : undefined,
      });
    } finally {
      setScanning(false);
    }
  };

  const filteredGroups = useMemo(() => {
    if (!groups) return [];
    const q = query.trim().toLowerCase();
    if (!q) return groups;
    return groups.filter((g) => {
      const hay = `${g.title} ${g.artist} ${g.match_reason} ${g.master.file_path}`.toLowerCase();
      return hay.includes(q);
    });
  }, [groups, query]);

  const summary = useMemo(() => {
    const list = groups || [];
    const redundant = list.reduce((acc, g) => acc + g.duplicates.length, 0);
    const reclaimable = list.reduce(
      (acc, g) => acc + (g.reclaimable_bytes || 0),
      0
    );
    return {
      totalGroups: list.length,
      redundantFiles: redundant,
      reclaimableBytes: reclaimable,
    };
  }, [groups]);

  const toggleSelect = (key: string) => {
    setSelectedKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const toggleExpand = (key: string) => {
    setExpandedKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const executeMerge = async (mode: "hardlink" | "merge") => {
    if (!groups || selectedKeys.size === 0 || mergingMode) return;
    setConfirmDeleteOpen(false);
    setMergingMode(mode);
    const keysToProcess = Array.from(selectedKeys);
    try {
      const res = await api.tools.mergeDuplicates({
        mode,
        group_keys: keysToProcess,
      });
      setMergeStats(res);
      const processedSet = new Set(keysToProcess);
      setGroups((prev) =>
        prev ? prev.filter((g) => !processedSet.has(g.key)) : prev
      );
      setSelectedKeys(new Set());
      void queryClient.invalidateQueries({ queryKey: ["library"] });
      void queryClient.invalidateQueries({ queryKey: ["playlists"] });
      toast.success(
        mode === "hardlink"
          ? `Hard-linked ${res.hardlinked} file(s)`
          : `Merged ${res.files_merged} duplicate(s)`,
        {
          description: `Reclaimed ${formatBytes(res.reclaimed_bytes)} across ${res.groups_processed} group(s)`,
        }
      );
    } catch (err) {
      toast.error("Duplicate consolidation failed", {
        description: err instanceof Error ? err.message : undefined,
      });
    } finally {
      setMergingMode(null);
    }
  };

  const scanProgress =
    scanning && activeToolProgress?.tool === "duplicates_scan"
      ? activeToolProgress
      : null;

  return (
    <div className="space-y-5">
      <div className="glass-panel rounded-2xl p-5 flex flex-wrap items-center justify-between gap-4">
        <div className="space-y-1.5 max-w-2xl">
          <div className="flex items-center gap-2">
            <CopyCheck className="h-4 w-4 text-emerald-bright" />
            <h2 className="text-base font-semibold text-white">
              Smart Duplicate & Acoustic Fingerprint Merger
            </h2>
          </div>
          <p className="text-xs text-zinc-400 leading-relaxed">
            Clusters duplicates across folders via ISRC, normalized tags, and
            64-bit acoustic fingerprinting. Use <strong>NTFS Hard-Link</strong>{" "}
            to keep files visible in every playlist folder using zero extra disk
            space, or <strong>Clean Merge</strong> to remove redundant copies
            while keeping archive records & .m3u8 playlists intact.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-2 rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2 text-xs text-zinc-200 cursor-pointer">
            <input
              type="checkbox"
              checked={useAcoustic}
              onChange={(e) => setUseAcoustic(e.target.checked)}
              className="h-4 w-4 accent-emerald-500"
            />
            Acoustic Fingerprinting
          </label>

          <Button
            type="button"
            disabled={scanning}
            onClick={() => void handleScan()}
          >
            {scanning ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Search className="h-4 w-4" />
            )}
            {scanning ? "Scanning..." : "Scan Library for Duplicates"}
          </Button>
        </div>
      </div>

      {scanProgress && (
        <div className="glass-panel rounded-2xl p-4 space-y-2 border-emerald-500/30">
          <div className="flex items-center justify-between text-xs font-mono text-emerald-300 tabular-nums">
            <span className="truncate">{scanProgress.message}</span>
            <span>
              {scanProgress.current}/{scanProgress.total} (
              {Math.round(scanProgress.percent)}%)
            </span>
          </div>
          <div className="h-2 w-full rounded-full bg-black/50 overflow-hidden">
            <div
              className="h-full bg-emerald-bright transition-all"
              style={{
                width: `${Math.max(4, Math.min(100, scanProgress.percent))}%`,
              }}
            />
          </div>
        </div>
      )}

      {mergeStats && (
        <div className="rounded-2xl border border-emerald-500/35 bg-emerald-500/10 p-4 text-xs flex flex-wrap items-center justify-between gap-3">
          <div className="space-y-0.5">
            <div className="font-semibold text-emerald-300">
              Consolidation Complete ({mergeStats.mode})
            </div>
            <div className="text-zinc-200 font-mono">
              {mergeStats.groups_processed} groups · {mergeStats.files_merged}{" "}
              files consolidated · {mergeStats.hardlinked} hard-linked ·{" "}
              {formatBytes(mergeStats.reclaimed_bytes)} reclaimed
              {mergeStats.errors > 0 ? ` · ${mergeStats.errors} error(s)` : ""}
            </div>
          </div>
        </div>
      )}

      {groups !== null ? (
        <>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div className="glass-panel rounded-2xl p-4">
              <div className="text-xs text-zinc-400">Duplicate Groups</div>
              <div className="mt-1 text-2xl font-bold text-white tabular-nums">
                {summary.totalGroups}
              </div>
            </div>
            <div className="glass-panel rounded-2xl p-4">
              <div className="text-xs text-zinc-400">Redundant Files</div>
              <div className="mt-1 text-2xl font-bold text-amber-300 tabular-nums">
                {summary.redundantFiles}
              </div>
            </div>
            <div className="glass-panel rounded-2xl p-4 border-emerald-500/20">
              <div className="text-xs text-emerald-300/90">
                Reclaimable Disk Space
              </div>
              <div className="mt-1 text-2xl font-bold text-emerald-300 tabular-nums">
                {formatBytes(summary.reclaimableBytes)}
              </div>
            </div>
          </div>

          <div className="glass-panel rounded-2xl p-4 space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  onClick={() =>
                    setSelectedKeys(new Set(groups.map((g) => g.key)))
                  }
                  disabled={groups.length === 0}
                >
                  Select All ({groups.length})
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  onClick={() => setSelectedKeys(new Set())}
                  disabled={selectedKeys.size === 0}
                >
                  Clear ({selectedKeys.size})
                </Button>

                <div className="relative w-56">
                  <Search className="h-3.5 w-3.5 text-zinc-500 absolute left-3 top-1/2 -translate-y-1/2" />
                  <Input
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    placeholder="Filter duplicates..."
                    className="pl-8 h-9 text-xs"
                  />
                </div>
              </div>

              <div className="flex flex-wrap items-center gap-2">
                <Button
                  type="button"
                  size="sm"
                  disabled={selectedKeys.size === 0 || mergingMode !== null}
                  onClick={() => void executeMerge("hardlink")}
                >
                  {mergingMode === "hardlink" ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Link2 className="h-3.5 w-3.5" />
                  )}
                  Hard-Link Merge ({selectedKeys.size})
                </Button>

                <Button
                  type="button"
                  size="sm"
                  variant="destructive"
                  disabled={selectedKeys.size === 0 || mergingMode !== null}
                  onClick={() => setConfirmDeleteOpen((v) => !v)}
                >
                  {mergingMode === "merge" ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Trash2 className="h-3.5 w-3.5" />
                  )}
                  Clean Delete Merge
                </Button>
              </div>
            </div>

            {confirmDeleteOpen && (
              <div className="rounded-xl border border-red-500/40 bg-red-500/10 p-3.5 flex flex-wrap items-center justify-between gap-3 text-xs">
                <span className="text-red-200">
                  Permanently delete redundant files in{" "}
                  <strong>{selectedKeys.size}</strong> selected group(s)? Master
                  files stay safe and archive records + .m3u8 files are
                  re-linked automatically.
                </span>
                <div className="flex items-center gap-2">
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    onClick={() => setConfirmDeleteOpen(false)}
                  >
                    Cancel
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="destructive"
                    onClick={() => void executeMerge("merge")}
                  >
                    Confirm Delete Merge
                  </Button>
                </div>
              </div>
            )}

            <div className="space-y-2.5 max-h-[540px] overflow-y-auto pr-1">
              {filteredGroups.length === 0 ? (
                <div className="py-10 text-center text-xs text-zinc-500">
                  No duplicate groups remaining. Your library is clean!
                </div>
              ) : (
                filteredGroups.map((group) => {
                  const selected = selectedKeys.has(group.key);
                  const expanded = expandedKeys.has(group.key);
                  return (
                    <div
                      key={group.key}
                      className={cn(
                        "rounded-xl border transition-colors",
                        selected
                          ? "border-emerald-500/35 bg-emerald-500/[0.04]"
                          : "border-white/[0.07] bg-white/[0.02]"
                      )}
                    >
                      <div className="flex items-center justify-between gap-3 p-3">
                        <div className="flex items-center gap-2.5 min-w-0 flex-1">
                          <button
                            type="button"
                            onClick={() => toggleSelect(group.key)}
                            className="text-zinc-400 hover:text-emerald-300 shrink-0 cursor-pointer"
                            aria-label={`Select group ${group.title}`}
                          >
                            {selected ? (
                              <CheckSquare className="h-4 w-4 text-emerald-bright" />
                            ) : (
                              <Square className="h-4 w-4" />
                            )}
                          </button>

                          <button
                            type="button"
                            onClick={() => toggleExpand(group.key)}
                            className="text-zinc-400 hover:text-white shrink-0 cursor-pointer"
                            aria-label="Toggle duplicate files"
                          >
                            {expanded ? (
                              <ChevronDown className="h-4 w-4" />
                            ) : (
                              <ChevronRight className="h-4 w-4" />
                            )}
                          </button>

                          <div
                            className="min-w-0 flex-1 cursor-pointer"
                            onClick={() => toggleExpand(group.key)}
                          >
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="text-sm font-medium text-white truncate">
                                {group.title || "Untitled Track"}
                              </span>
                              <Badge variant="violet" className="text-[10px]">
                                {group.match_reason}
                              </Badge>
                            </div>
                            <div className="text-[11px] text-zinc-400 truncate">
                              {group.artist} · {1 + group.duplicates.length}{" "}
                              copies
                            </div>
                          </div>
                        </div>

                        <div className="text-right shrink-0">
                          <div className="font-mono text-xs font-semibold text-emerald-300 tabular-nums">
                            {formatBytes(group.reclaimable_bytes)} saveable
                          </div>
                          <div className="text-[10px] text-zinc-500">
                            {group.duplicates.length} duplicate(s)
                          </div>
                        </div>
                      </div>

                      {expanded && (
                        <div className="border-t border-white/[0.06] px-3 pb-3 pt-2 space-y-1.5 text-xs">
                          <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-emerald-500/[0.08] border border-emerald-500/25 px-3 py-2">
                            <div className="flex items-center gap-2 min-w-0 flex-1">
                              <Badge variant="emerald" className="text-[10px] shrink-0">
                                MASTER KEPT
                              </Badge>
                              <QualityBadge badge={group.master.quality_badge} />
                              <span className="font-mono text-[11px] text-zinc-200 truncate">
                                {group.master.file_path}
                              </span>
                            </div>
                            <span className="font-mono text-[11px] text-zinc-300 tabular-nums shrink-0">
                              {formatBytes(group.master.size_bytes)}
                            </span>
                          </div>

                          {group.duplicates.map((dup) => (
                            <div
                              key={dup.file_path}
                              className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-black/25 border border-white/[0.05] px-3 py-2"
                            >
                              <div className="flex items-center gap-2 min-w-0 flex-1">
                                <Badge
                                  variant={dup.is_hardlinked ? "sky" : "gold"}
                                  className="text-[10px] shrink-0"
                                >
                                  {dup.is_hardlinked ? "HARD-LINKED" : "DUPLICATE"}
                                </Badge>
                                <QualityBadge badge={dup.quality_badge} />
                                <span className="font-mono text-[11px] text-zinc-400 truncate">
                                  {dup.file_path}
                                </span>
                              </div>
                              <span className="font-mono text-[11px] text-zinc-400 tabular-nums shrink-0">
                                {formatBytes(dup.size_bytes)}
                              </span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  );
                })
              )}
            </div>
          </div>
        </>
      ) : (
        <div className="glass-panel rounded-2xl p-10 text-center space-y-2">
          <HardDrive className="h-8 w-8 text-zinc-600 mx-auto" />
          <div className="text-sm font-medium text-zinc-200">
            Ready to detect duplicate songs
          </div>
          <p className="text-xs text-zinc-400 max-w-md mx-auto">
            Click <strong>Scan Library for Duplicates</strong> to find redundant
            copies across singles, albums, and playlist folders.
          </p>
        </div>
      )}
    </div>
  );
}
