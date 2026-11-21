import {
  CheckSquare,
  Pause,
  Play,
  RotateCcw,
  Search,
  Square,
  Trash2,
  X,
} from "lucide-react";
import type { QueueStats } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

export type QueueStatusFilter =
  | "all"
  | "active"
  | "queued"
  | "completed"
  | "failed";

interface QueueControlsStripProps {
  stats?: QueueStats;
  paused: boolean;
  isLoading: boolean;
  statusFilter: QueueStatusFilter;
  onStatusFilterChange: (status: QueueStatusFilter) => void;
  searchQuery: string;
  onSearchChange: (q: string) => void;
  searchInputRef: React.RefObject<HTMLInputElement | null>;
  filteredCount: number;
  allVisibleSelected: boolean;
  onToggleSelectAll: () => void;
  onStartAll: () => void;
  onTogglePause: () => void;
  onStopAll: () => void;
  onRetryFailed: () => void;
  onClearCompleted: () => void;
}

const FILTER_TABS: Array<{ id: QueueStatusFilter; label: string }> = [
  { id: "all", label: "All Tracks" },
  { id: "active", label: "Active" },
  { id: "queued", label: "Queued" },
  { id: "completed", label: "Completed" },
  { id: "failed", label: "Failed / Stopped" },
];

export function QueueControlsStrip({
  stats,
  paused,
  isLoading,
  statusFilter,
  onStatusFilterChange,
  searchQuery,
  onSearchChange,
  searchInputRef,
  filteredCount,
  allVisibleSelected,
  onToggleSelectAll,
  onStartAll,
  onTogglePause,
  onStopAll,
  onRetryFailed,
  onClearCompleted,
}: QueueControlsStripProps) {
  const total = stats?.total ?? 0;
  const active = stats?.active ?? 0;
  const queued = stats?.queued ?? 0;
  const completed = stats?.completed ?? 0;
  const failed = stats?.failed ?? 0;
  const overallPct = stats?.overall_progress_percent ?? 0;

  const metricCards: Array<{
    id: QueueStatusFilter;
    label: string;
    value: number;
    tone: string;
  }> = [
    { id: "all", label: "Total", value: total, tone: "text-white" },
    { id: "active", label: "Active", value: active, tone: "text-emerald-bright" },
    { id: "queued", label: "Queued", value: queued, tone: "text-sky-300" },
    { id: "completed", label: "Completed", value: completed, tone: "text-emerald-300" },
    { id: "failed", label: "Failed", value: failed, tone: "text-red-300" },
  ];

  return (
    <div className="space-y-3">
      {/* KPI Metrics + Master Action Buttons */}
      <div className="flex flex-col xl:flex-row gap-3 items-stretch xl:items-center justify-between">
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-2.5 flex-1">
          {metricCards.map((card) => {
            const isSelected = statusFilter === card.id;
            return (
              <button
                key={card.id}
                type="button"
                onClick={() => onStatusFilterChange(card.id)}
                className={cn(
                  "glass-panel rounded-xl px-3.5 py-2.5 text-left transition-all cursor-pointer",
                  isSelected
                    ? "border-emerald-500/45 bg-emerald-500/[0.08]"
                    : "hover:border-white/15 hover:bg-white/[0.04]"
                )}
              >
                <div className="text-[10px] font-semibold uppercase tracking-wider text-zinc-400">
                  {card.label}
                </div>
                {isLoading ? (
                  <Skeleton className="h-6 w-10 mt-1" />
                ) : (
                  <div
                    className={cn(
                      "text-xl font-semibold font-mono tabular-nums mt-0.5",
                      card.tone
                    )}
                  >
                    {card.value}
                  </div>
                )}
              </button>
            );
          })}
        </div>

        <div className="flex flex-wrap items-center gap-2 shrink-0">
          <Button
            type="button"
            size="sm"
            onClick={onStartAll}
            disabled={total === 0}
          >
            <Play className="h-3.5 w-3.5" />
            Start All
          </Button>

          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={onTogglePause}
            disabled={total === 0}
          >
            {paused ? (
              <>
                <Play className="h-3.5 w-3.5" />
                Resume
              </>
            ) : (
              <>
                <Pause className="h-3.5 w-3.5" />
                Pause
              </>
            )}
          </Button>

          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={onStopAll}
            disabled={total === 0}
          >
            <Square className="h-3.5 w-3.5" />
            Stop
          </Button>

          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={onRetryFailed}
            disabled={failed === 0}
          >
            <RotateCcw className="h-3.5 w-3.5" />
            Retry Failed{failed > 0 ? ` (${failed})` : ""}
          </Button>

          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={onClearCompleted}
            disabled={completed === 0}
          >
            <Trash2 className="h-3.5 w-3.5" />
            Clear Done
          </Button>
        </div>
      </div>

      {/* Master Overall Progress Bar & Filter Row (when queue has items) */}
      {total > 0 && (
        <div className="glass-panel rounded-2xl p-3.5 space-y-3">
          <div className="space-y-1.5">
            <div className="flex items-center justify-between text-xs">
              <span className="font-medium text-zinc-200 font-mono tabular-nums">
                Overall Progress: {overallPct}% ({completed}/{total} completed)
              </span>
              <span className="text-zinc-400 font-mono tabular-nums">
                {active} active
                {paused ? " · paused" : ""}
                {failed > 0 ? ` · ${failed} failed` : ""}
              </span>
            </div>
            <div className="h-1.5 w-full overflow-hidden rounded-full bg-white/[0.07]">
              <div
                className="h-full rounded-full bg-gradient-to-r from-emerald-brand to-emerald-bright transition-all duration-300"
                style={{ width: `${Math.min(100, Math.max(0, overallPct))}%` }}
              />
            </div>
          </div>

          <div className="flex flex-col md:flex-row gap-2.5 items-stretch md:items-center justify-between pt-1 border-t border-white/[0.06]">
            <div className="flex flex-wrap items-center gap-1.5">
              {filteredCount > 0 && (
                <button
                  type="button"
                  onClick={onToggleSelectAll}
                  className={cn(
                    "inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium border transition-colors cursor-pointer mr-1",
                    allVisibleSelected
                      ? "bg-emerald-500/15 text-emerald-300 border-emerald-500/35"
                      : "bg-white/[0.04] text-zinc-300 border-white/10 hover:bg-white/[0.08]"
                  )}
                  title="Select or deselect all visible rows (Ctrl+A)"
                >
                  <CheckSquare className="h-3.5 w-3.5" />
                  <span>{allVisibleSelected ? "Deselect All" : "Select All"}</span>
                </button>
              )}

              {FILTER_TABS.map((tab) => {
                const isActive = statusFilter === tab.id;
                return (
                  <button
                    key={tab.id}
                    type="button"
                    onClick={() => onStatusFilterChange(tab.id)}
                    className={cn(
                      "rounded-lg px-2.5 py-1.5 text-xs font-medium transition-colors cursor-pointer",
                      isActive
                        ? "bg-white/12 text-white border border-white/15"
                        : "text-zinc-400 hover:text-zinc-200 hover:bg-white/[0.04] border border-transparent"
                    )}
                  >
                    {tab.label}
                  </button>
                );
              })}
            </div>

            <div className="w-full md:w-72">
              <Input
                ref={searchInputRef}
                value={searchQuery}
                onChange={(e) => onSearchChange(e.target.value)}
                leadingIcon={<Search className="h-3.5 w-3.5" />}
                placeholder="Filter queue (Ctrl+F)..."
                className="h-8 text-xs"
                trailingSlot={
                  searchQuery ? (
                    <button
                      type="button"
                      onClick={() => onSearchChange("")}
                      className="rounded p-1 text-zinc-400 hover:text-white cursor-pointer"
                      aria-label="Clear search"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  ) : undefined
                }
              />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
