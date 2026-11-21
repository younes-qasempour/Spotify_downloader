import { Ban, Copy, Link, RotateCcw, Trash2, X } from "lucide-react";
import { Button } from "@/components/ui/button";

interface QueueBatchBarProps {
  selectedCount: number;
  hasRetryable: boolean;
  hasCancellable: boolean;
  onRetrySelected: () => void;
  onCancelSelected: () => void;
  onRemoveSelected: () => void;
  onCopyTitles: () => void;
  onCopyLinks: () => void;
  onClearSelection: () => void;
}

export function QueueBatchBar({
  selectedCount,
  hasRetryable,
  hasCancellable,
  onRetrySelected,
  onCancelSelected,
  onRemoveSelected,
  onCopyTitles,
  onCopyLinks,
  onClearSelection,
}: QueueBatchBarProps) {
  if (selectedCount <= 0) return null;

  return (
    <div className="glass-panel rounded-xl px-4 py-2.5 flex flex-wrap items-center justify-between gap-2 border border-emerald-500/35 bg-emerald-500/[0.06]">
      <div className="flex items-center gap-2.5 text-xs">
        <span className="font-semibold font-mono tabular-nums text-emerald-300">
          {selectedCount} track{selectedCount === 1 ? "" : "s"} selected
        </span>
        <button
          type="button"
          onClick={onClearSelection}
          className="inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-zinc-400 hover:bg-white/8 hover:text-white cursor-pointer"
        >
          <X className="h-3 w-3" />
          Clear
        </button>
      </div>

      <div className="flex flex-wrap items-center gap-1.5">
        {hasRetryable && (
          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={onRetrySelected}
          >
            <RotateCcw className="h-3.5 w-3.5" />
            Retry
          </Button>
        )}

        {hasCancellable && (
          <Button
            type="button"
            variant="secondary"
            size="sm"
            onClick={onCancelSelected}
          >
            <Ban className="h-3.5 w-3.5" />
            Cancel
          </Button>
        )}

        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={onCopyTitles}
        >
          <Copy className="h-3.5 w-3.5" />
          Copy Titles
        </Button>

        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={onCopyLinks}
        >
          <Link className="h-3.5 w-3.5" />
          Copy Links
        </Button>

        <Button
          type="button"
          variant="destructive"
          size="sm"
          onClick={onRemoveSelected}
        >
          <Trash2 className="h-3.5 w-3.5" />
          Remove
        </Button>
      </div>
    </div>
  );
}
