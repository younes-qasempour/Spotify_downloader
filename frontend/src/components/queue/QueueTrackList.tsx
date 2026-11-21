import { useEffect, useState } from "react";
import {
  Copy,
  FolderOpen,
  Link,
  Play,
  RotateCcw,
  Trash2,
  XCircle,
} from "lucide-react";
import type { QueueItem } from "@/api/types";
import { QueueTrackRow } from "@/components/queue/QueueTrackRow";
import { useVirtualList } from "@/hooks/useVirtualList";
import type { LiveTrackProgress } from "@/stores/appStore";

interface QueueTrackListProps {
  items: QueueItem[];
  selectedIds: Set<string>;
  liveProgress: Record<string, LiveTrackProgress>;
  onRowClick: (trackId: string, index: number, e: React.MouseEvent) => void;
  onCheckboxClick: (trackId: string, index: number, e: React.MouseEvent) => void;
  onDoubleClick: (item: QueueItem) => void;
  onPlay: (item: QueueItem) => void;
  onRetry: (trackId: string) => void;
  onCancel: (trackId: string) => void;
  onRemove: (trackId: string) => void;
  onRevealInExplorer: (item: QueueItem) => void;
  onCopyTitle: (item: QueueItem) => void;
  onCopyLink: (item: QueueItem) => void;
}

interface ContextMenuState {
  item: QueueItem;
  x: number;
  y: number;
}

const ITEM_HEIGHT = 68;

export function QueueTrackList({
  items,
  selectedIds,
  liveProgress,
  onRowClick,
  onCheckboxClick,
  onDoubleClick,
  onPlay,
  onRetry,
  onCancel,
  onRemove,
  onRevealInExplorer,
  onCopyTitle,
  onCopyLink,
}: QueueTrackListProps) {
  const [contextMenu, setContextMenu] = useState<ContextMenuState | null>(null);

  const { containerRef, totalHeight, startIndex, endIndex, offsetY, onScroll } =
    useVirtualList({
      count: items.length,
      itemHeight: ITEM_HEIGHT,
      overscan: 8,
    });

  useEffect(() => {
    if (!contextMenu) return;
    const close = () => setContextMenu(null);
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    window.addEventListener("click", close);
    window.addEventListener("scroll", close, true);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("click", close);
      window.removeEventListener("scroll", close, true);
      window.removeEventListener("keydown", onKey);
    };
  }, [contextMenu]);

  const handleOpenContextMenu = (item: QueueItem, rawX: number, rawY: number) => {
    const safeX = Math.max(12, Math.min(rawX, window.innerWidth - 230));
    const safeY = Math.max(12, Math.min(rawY, window.innerHeight - 280));
    setContextMenu({ item, x: safeX, y: safeY });
  };

  if (items.length === 0) {
    return (
      <div className="glass-panel rounded-2xl p-10 text-center text-sm text-zinc-400">
        No tracks match the current queue search or status filter.
      </div>
    );
  }

  const visibleItems = items.slice(startIndex, endIndex);
  const menuItem = contextMenu?.item;
  const menuStatus = menuItem ? menuItem.status.trim().toLowerCase() : "";
  const menuCompleted = menuStatus === "completed" && Boolean(menuItem?.output_path);
  const menuRetryable = ["failed", "cancelled", "stopped"].includes(menuStatus);
  const menuCancellable = [
    "queued",
    "downloading",
    "resolving",
    "resolving (ytm fallback)",
    "paused",
  ].includes(menuStatus);

  return (
    <>
      <div className="glass-panel rounded-2xl overflow-hidden">
        <div
          ref={containerRef}
          onScroll={onScroll}
          className="h-[min(56vh,620px)] min-h-[280px] overflow-y-auto relative"
        >
          <div style={{ height: totalHeight }} className="relative w-full">
            <div
              style={{ transform: `translateY(${offsetY}px)` }}
              className="absolute inset-x-0 top-0"
            >
              {visibleItems.map((item, localIdx) => {
                const absoluteIdx = startIndex + localIdx;
                return (
                  <QueueTrackRow
                    key={item.track.id}
                    item={item}
                    index={absoluteIdx}
                    selected={selectedIds.has(item.track.id)}
                    liveProgress={liveProgress[item.track.id]}
                    onRowClick={onRowClick}
                    onCheckboxClick={onCheckboxClick}
                    onDoubleClick={onDoubleClick}
                    onContextMenu={handleOpenContextMenu}
                    onPlay={onPlay}
                    onRetry={onRetry}
                    onCancel={onCancel}
                    onRemove={onRemove}
                    onRevealInExplorer={onRevealInExplorer}
                  />
                );
              })}
            </div>
          </div>
        </div>
      </div>

      {/* Context Menu Popover */}
      {contextMenu && menuItem && (
        <div
          style={{ left: contextMenu.x, top: contextMenu.y }}
          onClick={(e) => e.stopPropagation()}
          className="fixed z-50 w-52 rounded-xl glass-panel py-1.5 shadow-2xl border border-white/12 text-xs"
        >
          {menuCompleted && (
            <>
              <button
                type="button"
                onClick={() => {
                  setContextMenu(null);
                  onPlay(menuItem);
                }}
                className="flex w-full items-center gap-2.5 px-3 py-2 text-zinc-200 hover:bg-white/8 hover:text-emerald-bright cursor-pointer"
              >
                <Play className="h-3.5 w-3.5" />
                Play in Audio Dock
              </button>
              <button
                type="button"
                onClick={() => {
                  setContextMenu(null);
                  onRevealInExplorer(menuItem);
                }}
                className="flex w-full items-center gap-2.5 px-3 py-2 text-zinc-200 hover:bg-white/8 cursor-pointer"
              >
                <FolderOpen className="h-3.5 w-3.5" />
                Show in File Explorer
              </button>
              <div className="my-1 border-t border-white/[0.06]" />
            </>
          )}

          {menuRetryable && (
            <button
              type="button"
              onClick={() => {
                setContextMenu(null);
                onRetry(menuItem.track.id);
              }}
              className="flex w-full items-center gap-2.5 px-3 py-2 text-zinc-200 hover:bg-white/8 hover:text-emerald-bright cursor-pointer"
            >
              <RotateCcw className="h-3.5 w-3.5" />
              Retry Download
            </button>
          )}

          {menuCancellable && (
            <button
              type="button"
              onClick={() => {
                setContextMenu(null);
                onCancel(menuItem.track.id);
              }}
              className="flex w-full items-center gap-2.5 px-3 py-2 text-zinc-200 hover:bg-white/8 hover:text-amber-300 cursor-pointer"
            >
              <XCircle className="h-3.5 w-3.5" />
              Cancel Download
            </button>
          )}

          <button
            type="button"
            onClick={() => {
              setContextMenu(null);
              onRemove(menuItem.track.id);
            }}
            className="flex w-full items-center gap-2.5 px-3 py-2 text-red-300 hover:bg-red-500/12 cursor-pointer"
          >
            <Trash2 className="h-3.5 w-3.5" />
            Remove from Queue
          </button>

          <div className="my-1 border-t border-white/[0.06]" />

          <button
            type="button"
            onClick={() => {
              setContextMenu(null);
              onCopyTitle(menuItem);
            }}
            className="flex w-full items-center gap-2.5 px-3 py-2 text-zinc-300 hover:bg-white/8 cursor-pointer"
          >
            <Copy className="h-3.5 w-3.5" />
            Copy Title & Artist
          </button>

          <button
            type="button"
            onClick={() => {
              setContextMenu(null);
              onCopyLink(menuItem);
            }}
            className="flex w-full items-center gap-2.5 px-3 py-2 text-zinc-300 hover:bg-white/8 cursor-pointer"
          >
            <Link className="h-3.5 w-3.5" />
            Copy Spotify Link
          </button>
        </div>
      )}
    </>
  );
}
