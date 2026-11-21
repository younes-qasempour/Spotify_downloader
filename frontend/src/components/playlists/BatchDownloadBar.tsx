import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  CheckSquare,
  ChevronDown,
  Download,
  Pause,
  Play,
  RotateCcw,
  SlidersHorizontal,
  Square,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface BatchDownloadBarProps {
  pendingCount: number;
  selectedCount: number;
  batchSize: number;
  onBatchSizeChange: (size: number) => void;
  paused: boolean;
  busy: boolean;
  onDownloadBatch: (size: number) => void;
  onDownloadSelected: () => void;
  onTogglePause: () => void;
  onStopQueue: () => void;
  onResetQueued: () => void;
}

const PRESETS = [25, 50, 100, 200];

export function BatchDownloadBar({
  pendingCount,
  selectedCount,
  batchSize,
  onBatchSizeChange,
  paused,
  busy,
  onDownloadBatch,
  onDownloadSelected,
  onTogglePause,
  onStopQueue,
  onResetQueued,
}: BatchDownloadBarProps) {
  const [drawerOpen, setDrawerOpen] = useState(false);

  const clampedBatch = Math.max(1, Math.min(5000, batchSize || 50));
  const nextCount =
    pendingCount > 0 ? Math.min(clampedBatch, pendingCount) : clampedBatch;

  return (
    <div className="glass-panel rounded-2xl p-3.5 space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            size="sm"
            disabled={busy || pendingCount === 0}
            onClick={() => onDownloadBatch(clampedBatch)}
          >
            <Download className="h-3.5 w-3.5" />
            {pendingCount === 0
              ? "All Tracks Downloaded"
              : `Download Next Batch (${nextCount}) · ${pendingCount} Remaining`}
          </Button>

          <Button
            type="button"
            size="sm"
            variant="secondary"
            disabled={busy || selectedCount === 0}
            onClick={onDownloadSelected}
          >
            <CheckSquare className="h-3.5 w-3.5" />
            Download Selected{selectedCount > 0 ? ` (${selectedCount})` : ""}
          </Button>

          <Button
            type="button"
            size="sm"
            variant="secondary"
            onClick={onTogglePause}
          >
            {paused ? (
              <>
                <Play className="h-3.5 w-3.5" />
                Resume Queue
              </>
            ) : (
              <>
                <Pause className="h-3.5 w-3.5" />
                Pause Queue
              </>
            )}
          </Button>

          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={onStopQueue}
          >
            <Square className="h-3.5 w-3.5" />
            Stop
          </Button>

          <Button
            type="button"
            size="icon"
            variant="ghost"
            onClick={onResetQueued}
            className="h-8 w-8"
            title="Reset queued tracks back to pending"
          >
            <RotateCcw className="h-3.5 w-3.5" />
          </Button>
        </div>

        <Button
          type="button"
          size="sm"
          variant={drawerOpen ? "secondary" : "ghost"}
          onClick={() => setDrawerOpen((o) => !o)}
        >
          <SlidersHorizontal className="h-3.5 w-3.5" />
          <span>Batch Options</span>
          <ChevronDown
            className={cn(
              "h-3.5 w-3.5 transition-transform duration-150",
              drawerOpen && "rotate-180"
            )}
          />
        </Button>
      </div>

      <AnimatePresence initial={false}>
        {drawerOpen && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.16 }}
            className="overflow-hidden"
          >
            <div className="flex flex-wrap items-center gap-2 pt-2.5 border-t border-white/[0.06] text-xs">
              <span className="text-zinc-400 font-medium">Batch Size:</span>

              <input
                type="number"
                min={1}
                max={5000}
                value={clampedBatch}
                onChange={(e) => {
                  const val = Number.parseInt(e.target.value, 10);
                  if (!Number.isNaN(val)) {
                    onBatchSizeChange(Math.max(1, Math.min(5000, val)));
                  }
                }}
                aria-label="Custom batch size"
                className="h-8 w-20 rounded-lg border border-white/15 bg-white/[0.06] px-2.5 text-center font-mono text-xs font-semibold text-white focus:border-emerald-500 focus:outline-none"
              />

              {PRESETS.map((preset) => {
                const active = clampedBatch === preset;
                return (
                  <button
                    key={preset}
                    type="button"
                    onClick={() => onBatchSizeChange(preset)}
                    className={cn(
                      "h-8 rounded-lg px-3 font-mono text-xs font-medium border transition-colors cursor-pointer",
                      active
                        ? "bg-emerald-500/20 text-emerald-300 border-emerald-500/60 font-semibold"
                        : "bg-white/[0.04] text-zinc-300 border-white/10 hover:bg-white/[0.09]"
                    )}
                  >
                    {preset}
                  </button>
                );
              })}

              <button
                type="button"
                onClick={() => onBatchSizeChange(Math.max(1, pendingCount))}
                disabled={pendingCount <= 0}
                className={cn(
                  "h-8 rounded-lg px-3 text-xs font-medium border transition-colors cursor-pointer disabled:opacity-40",
                  pendingCount > 0 && clampedBatch === pendingCount
                    ? "bg-emerald-500/20 text-emerald-300 border-emerald-500/60 font-semibold"
                    : "bg-white/[0.04] text-zinc-300 border-white/10 hover:bg-white/[0.09]"
                )}
              >
                All Pending ({pendingCount})
              </button>

              <span className="ml-auto hidden lg:inline text-[11px] text-zinc-500">
                Download pending songs in controlled batches to preserve VIP quota.
              </span>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
