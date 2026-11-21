import {
  CheckCircle2,
  Disc3,
  FolderOpen,
  MoreHorizontal,
  Play,
  RotateCcw,
  Trash2,
  XCircle,
} from "lucide-react";
import { apiUrl } from "@/api/client";
import type { QueueItem } from "@/api/types";
import { Badge, QualityBadge } from "@/components/ui/badge";
import { cn, formatDuration } from "@/lib/utils";
import type { LiveTrackProgress } from "@/stores/appStore";

interface QueueTrackRowProps {
  item: QueueItem;
  index: number;
  selected: boolean;
  liveProgress?: LiveTrackProgress;
  onRowClick: (trackId: string, index: number, e: React.MouseEvent) => void;
  onCheckboxClick: (trackId: string, index: number, e: React.MouseEvent) => void;
  onDoubleClick: (item: QueueItem) => void;
  onContextMenu: (item: QueueItem, x: number, y: number) => void;
  onPlay: (item: QueueItem) => void;
  onRetry: (trackId: string) => void;
  onCancel: (trackId: string) => void;
  onRemove: (trackId: string) => void;
  onRevealInExplorer: (item: QueueItem) => void;
}

const ACTIVE_STATUS_SET = new Set([
  "resolving",
  "resolving (ytm fallback)",
  "downloading",
  "tagging",
  "fetching lyrics",
]);

const RETRYABLE_SET = new Set(["failed", "cancelled", "stopped"]);
const CANCELLABLE_SET = new Set([
  "queued",
  "downloading",
  "resolving",
  "resolving (ytm fallback)",
  "paused",
]);

export function QueueTrackRow({
  item,
  index,
  selected,
  liveProgress,
  onRowClick,
  onCheckboxClick,
  onDoubleClick,
  onContextMenu,
  onPlay,
  onRetry,
  onCancel,
  onRemove,
  onRevealInExplorer,
}: QueueTrackRowProps) {
  const statusNorm = item.status.trim().toLowerCase();
  const isCompleted = statusNorm === "completed";
  const isActive =
    ACTIVE_STATUS_SET.has(statusNorm) || statusNorm.startsWith("resolving");
  const isRetryable = RETRYABLE_SET.has(statusNorm);
  const isCancellable = CANCELLABLE_SET.has(statusNorm);

  const pct = liveProgress ? liveProgress.percent : item.progress_percent;
  const speed = liveProgress?.speed || item.speed_str;
  const eta = liveProgress?.eta || item.eta_str;

  const coverSrc =
    isCompleted && item.output_path
      ? apiUrl(`/api/media/cover/track/${encodeURIComponent(item.track.id)}`)
      : item.track.cover_url || "";

  const statusBadgeVariant = isCompleted
    ? "emerald"
    : statusNorm === "failed"
      ? "danger"
      : statusNorm === "paused"
        ? "gold"
        : isActive
          ? "sky"
          : "default";

  return (
    <div
      onClick={(e) => onRowClick(item.track.id, index, e)}
      onDoubleClick={() => onDoubleClick(item)}
      onContextMenu={(e) => {
        e.preventDefault();
        onContextMenu(item, e.clientX, e.clientY);
      }}
      className={cn(
        "group flex h-[68px] items-center gap-3 px-3.5 border-b border-white/[0.05] transition-colors select-none cursor-default",
        selected
          ? "bg-emerald-500/[0.11]"
          : "hover:bg-white/[0.03]"
      )}
    >
      {/* Checkbox */}
      <input
        type="checkbox"
        checked={selected}
        onChange={() => {}}
        onClick={(e) => {
          e.stopPropagation();
          onCheckboxClick(item.track.id, index, e);
        }}
        aria-label={`Select ${item.track.title}`}
        className="h-4 w-4 shrink-0 rounded accent-emerald-500 cursor-pointer"
      />

      {/* Artwork */}
      <div className="relative h-11 w-11 shrink-0 overflow-hidden rounded-lg bg-elevated border border-white/[0.07]">
        {coverSrc ? (
          <img
            src={coverSrc}
            alt={item.track.title}
            loading="lazy"
            className="h-full w-full object-cover"
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center text-zinc-500">
            <Disc3 className="h-5 w-5" />
          </div>
        )}
        {isCompleted && item.output_path && (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onPlay(item);
            }}
            className="absolute inset-0 flex items-center justify-center bg-black/60 opacity-0 group-hover:opacity-100 transition-opacity text-white cursor-pointer"
            title="Play track"
          >
            <Play className="h-4 w-4 fill-current" />
          </button>
        )}
      </div>

      {/* Title, Artist & Error */}
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 min-w-0">
          <span className="truncate text-sm font-medium text-white">
            {item.track.title}
          </span>
          {item.preferred_engine && item.preferred_engine !== "auto" && (
            <span className="hidden lg:inline rounded bg-white/[0.06] px-1.5 py-0.5 text-[10px] font-mono uppercase text-zinc-400">
              {item.preferred_engine}
            </span>
          )}
        </div>
        <div className="truncate text-xs text-zinc-400">
          {item.track.artist_str}
          {item.track.album ? ` · ${item.track.album}` : ""}
        </div>
        {item.error_message && statusNorm === "failed" && (
          <div
            className="truncate text-[11px] text-red-300/90 mt-0.5"
            title={item.error_message}
          >
            {item.error_message}
          </div>
        )}
      </div>

      {/* Quality & Duration */}
      <div className="hidden md:flex items-center gap-3 shrink-0">
        {item.quality_badge && (
          <QualityBadge
            badge={item.quality_badge}
            sourceType={item.source_type}
          />
        )}
        <span className="w-12 text-right text-xs font-mono tabular-nums text-zinc-400">
          {formatDuration(item.track.duration_ms)}
        </span>
      </div>

      {/* Progress / Status */}
      <div className="w-32 sm:w-40 shrink-0 flex flex-col items-end justify-center gap-1">
        {isActive || (pct > 0 && pct < 100 && !isCompleted && !isRetryable) ? (
          <>
            <div className="flex w-full items-center justify-between text-[11px] font-mono tabular-nums">
              <span className="truncate text-sky-300 max-w-[96px]">
                {item.status}
              </span>
              <span className="text-white">{Math.round(pct)}%</span>
            </div>
            <div className="h-1.5 w-full overflow-hidden rounded-full bg-white/10">
              <div
                className="h-full rounded-full bg-emerald-bright transition-all duration-150"
                style={{ width: `${Math.min(100, Math.max(3, pct))}%` }}
              />
            </div>
            {(speed || eta) && (
              <div className="text-[10px] font-mono tabular-nums text-zinc-400 truncate max-w-full">
                {[speed, eta ? `ETA ${eta}` : ""].filter(Boolean).join(" · ")}
              </div>
            )}
          </>
        ) : (
          <Badge variant={statusBadgeVariant} className="gap-1">
            {isCompleted && <CheckCircle2 className="h-3 w-3" />}
            <span>{item.status}</span>
          </Badge>
        )}
      </div>

      {/* Row Quick Actions */}
      <div
        className="flex items-center gap-1 shrink-0"
        onClick={(e) => e.stopPropagation()}
      >
        {isCompleted && item.output_path && (
          <>
            <button
              type="button"
              onClick={() => onPlay(item)}
              className="rounded-lg p-1.5 text-zinc-400 hover:bg-white/10 hover:text-emerald-bright cursor-pointer"
              title="Play in Audio Dock"
            >
              <Play className="h-3.5 w-3.5" />
            </button>
            <button
              type="button"
              onClick={() => onRevealInExplorer(item)}
              className="hidden sm:inline-flex rounded-lg p-1.5 text-zinc-400 hover:bg-white/10 hover:text-white cursor-pointer"
              title="Show in File Explorer"
            >
              <FolderOpen className="h-3.5 w-3.5" />
            </button>
          </>
        )}

        {isRetryable && (
          <button
            type="button"
            onClick={() => onRetry(item.track.id)}
            className="rounded-lg p-1.5 text-zinc-400 hover:bg-white/10 hover:text-emerald-bright cursor-pointer"
            title="Retry download"
          >
            <RotateCcw className="h-3.5 w-3.5" />
          </button>
        )}

        {isCancellable && (
          <button
            type="button"
            onClick={() => onCancel(item.track.id)}
            className="rounded-lg p-1.5 text-zinc-400 hover:bg-white/10 hover:text-amber-300 cursor-pointer"
            title="Cancel download"
          >
            <XCircle className="h-3.5 w-3.5" />
          </button>
        )}

        <button
          type="button"
          onClick={() => onRemove(item.track.id)}
          className="rounded-lg p-1.5 text-zinc-500 hover:bg-red-500/15 hover:text-red-300 cursor-pointer"
          title="Remove from queue"
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>

        <button
          type="button"
          onClick={(e) => {
            const rect = e.currentTarget.getBoundingClientRect();
            onContextMenu(item, rect.right, rect.bottom + 4);
          }}
          className="rounded-lg p-1.5 text-zinc-400 hover:bg-white/10 hover:text-white cursor-pointer"
          title="More actions"
        >
          <MoreHorizontal className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
}
