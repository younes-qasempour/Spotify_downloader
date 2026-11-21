import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { Link2 } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { api } from "@/api/endpoints";
import type { PlayerTrack, QueueItem } from "@/api/types";
import { QueueBatchBar } from "@/components/queue/QueueBatchBar";
import {
  QueueControlsStrip,
  type QueueStatusFilter,
} from "@/components/queue/QueueControlsStrip";
import { QueueEmptyState } from "@/components/queue/QueueEmptyState";
import {
  QueueIngestionBar,
  type PreferredEngine,
} from "@/components/queue/QueueIngestionBar";
import { QueueTrackList } from "@/components/queue/QueueTrackList";
import { useAppStore } from "@/stores/appStore";
import { usePlayerStore } from "@/stores/playerStore";

const RETRYABLE_SET = new Set(["failed", "cancelled", "stopped"]);
const CANCELLABLE_SET = new Set([
  "queued",
  "downloading",
  "resolving",
  "resolving (ytm fallback)",
  "paused",
]);

function isEditableElement(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName.toLowerCase();
  return tag === "input" || tag === "textarea" || target.isContentEditable;
}

function toPlayerTrack(item: QueueItem): PlayerTrack {
  const id = item.track.id;
  return {
    id,
    title: item.track.title,
    artist: item.track.artist_str,
    album: item.track.album,
    durationSec:
      item.track.duration_sec ||
      Math.round((item.track.duration_ms || 0) / 1000),
    audioUrl: `/api/media/audio/${encodeURIComponent(id)}`,
    coverUrl: `/api/media/cover/track/${encodeURIComponent(id)}`,
    qualityBadge: item.quality_badge,
    sourceType: item.source_type,
  };
}

export function QueuePage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [urlInput, setUrlInput] = useState("");
  const [preferredEngine, setPreferredEngine] =
    useState<PreferredEngine>("auto");
  const [autoStart, setAutoStart] = useState(true);
  const [submitting, setSubmitting] = useState(false);

  const [statusFilter, setStatusFilter] = useState<QueueStatusFilter>("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [dragActive, setDragActive] = useState(false);

  const searchInputRef = useRef<HTMLInputElement | null>(null);
  const lastAnchorIndexRef = useRef<number | null>(null);
  const dragDepthRef = useRef(0);

  const liveProgress = useAppStore((s) => s.liveProgress);
  const setQueuePaused = useAppStore((s) => s.setQueuePaused);
  const setPendingPrompts = useAppStore((s) => s.setPendingPrompts);
  const setCommandPaletteOpen = useAppStore((s) => s.setCommandPaletteOpen);
  const playTrackList = usePlayerStore((s) => s.playTrackList);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebouncedQuery(searchQuery.trim());
    }, 150);
    return () => window.clearTimeout(timer);
  }, [searchQuery]);

  const { data, isLoading } = useQuery({
    queryKey: ["queue", debouncedQuery, statusFilter],
    queryFn: () => api.queue.list(debouncedQuery, statusFilter),
  });

  useEffect(() => {
    if (!data) return;
    setQueuePaused(data.paused);
    setPendingPrompts(data.pending_prompts ?? []);
  }, [data, setPendingPrompts, setQueuePaused]);

  const items = data?.items ?? [];
  const stats = data?.stats;
  const paused = data?.paused ?? false;

  useEffect(() => {
    setSelectedIds((prev) => {
      if (prev.size === 0) return prev;
      const valid = new Set(items.map((it) => it.track.id));
      let changed = false;
      const next = new Set<string>();
      prev.forEach((id) => {
        if (valid.has(id)) {
          next.add(id);
        } else {
          changed = true;
        }
      });
      return changed ? next : prev;
    });
  }, [items]);

  const invalidateQueue = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ["queue"] });
    void queryClient.invalidateQueries({ queryKey: ["health"] });
  }, [queryClient]);

  const submitEnqueueText = useCallback(
    async (rawText: string) => {
      const cleaned = rawText.trim();
      if (!cleaned || submitting) return;
      setSubmitting(true);
      try {
        const res = await api.queue.enqueue({
          input: cleaned,
          auto_start: autoStart,
          preferred_engine: preferredEngine,
        });
        setUrlInput("");
        invalidateQueue();
        if (res.saved_playlists_updated) {
          void queryClient.invalidateQueries({ queryKey: ["playlists"] });
        }

        if (res.truncated_guest_limit) {
          toast.warning("Playlist Capped at 100 Tracks (Guest Limit)", {
            description:
              "Added 100 tracks. Add your free Spotify API keys in Settings to enqueue full 1,000+ track playlists.",
            action: {
              label: "Settings",
              onClick: () => navigate("/settings"),
            },
            duration: 9000,
          });
        } else if (res.enqueued_count > 0) {
          toast.success(`Enqueued ${res.enqueued_count} track(s)`, {
            description:
              res.errors.length > 0
                ? res.errors[0]
                : res.started
                  ? "Download pipeline active."
                  : "Click 'Start All' when ready.",
          });
        } else {
          toast.warning("No tracks found", {
            description: res.errors[0] || "Check the link or search terms.",
          });
        }
      } catch (err) {
        toast.error("Failed to enqueue", {
          description:
            err instanceof Error
              ? err.message
              : "Check URL and backend connection.",
        });
      } finally {
        setSubmitting(false);
      }
    },
    [autoStart, invalidateQueue, navigate, preferredEngine, queryClient, submitting]
  );

  const handlePasteFromClipboard = useCallback(async () => {
    try {
      const text = (await navigator.clipboard.readText()).trim();
      if (text) {
        setUrlInput(text);
      } else {
        toast.info("Clipboard is empty");
      }
    } catch {
      toast.error("Clipboard access denied", {
        description: "Paste directly into the URL field with Ctrl+V.",
      });
    }
  }, []);

  const handleOpenFolder = useCallback(async () => {
    try {
      await api.settings.openFolder();
    } catch (err) {
      toast.error("Could not open downloads folder", {
        description: err instanceof Error ? err.message : undefined,
      });
    }
  }, []);

  const handleRowClick = useCallback(
    (trackId: string, index: number, e: React.MouseEvent) => {
      if (e.shiftKey && lastAnchorIndexRef.current !== null) {
        const start = Math.min(lastAnchorIndexRef.current, index);
        const end = Math.max(lastAnchorIndexRef.current, index);
        setSelectedIds((prev) => {
          const next = new Set(e.ctrlKey || e.metaKey ? prev : []);
          for (let i = start; i <= end; i += 1) {
            if (items[i]) next.add(items[i].track.id);
          }
          return next;
        });
        return;
      }

      if (e.ctrlKey || e.metaKey) {
        lastAnchorIndexRef.current = index;
        setSelectedIds((prev) => {
          const next = new Set(prev);
          if (next.has(trackId)) next.delete(trackId);
          else next.add(trackId);
          return next;
        });
        return;
      }

      lastAnchorIndexRef.current = index;
      setSelectedIds(new Set([trackId]));
    },
    [items]
  );

  const handleCheckboxClick = useCallback(
    (trackId: string, index: number, e: React.MouseEvent) => {
      if (e.shiftKey && lastAnchorIndexRef.current !== null) {
        const start = Math.min(lastAnchorIndexRef.current, index);
        const end = Math.max(lastAnchorIndexRef.current, index);
        setSelectedIds((prev) => {
          const next = new Set(prev);
          for (let i = start; i <= end; i += 1) {
            if (items[i]) next.add(items[i].track.id);
          }
          return next;
        });
        return;
      }

      lastAnchorIndexRef.current = index;
      setSelectedIds((prev) => {
        const next = new Set(prev);
        if (next.has(trackId)) next.delete(trackId);
        else next.add(trackId);
        return next;
      });
    },
    [items]
  );

  const allVisibleSelected =
    items.length > 0 && items.every((it) => selectedIds.has(it.track.id));

  const handleToggleSelectAll = useCallback(() => {
    if (allVisibleSelected) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(items.map((it) => it.track.id)));
    }
  }, [allVisibleSelected, items]);

  const handlePlayItem = useCallback(
    (target: QueueItem) => {
      const completed = items.filter(
        (it) =>
          it.status.trim().toLowerCase() === "completed" &&
          Boolean(it.output_path)
      );
      const list = completed.length > 0 ? completed : [target];
      const idx = Math.max(
        0,
        list.findIndex((it) => it.track.id === target.track.id)
      );
      playTrackList(list.map(toPlayerTrack), idx);
    },
    [items, playTrackList]
  );

  const handleDoubleClick = useCallback(
    async (item: QueueItem) => {
      const s = item.status.trim().toLowerCase();
      if (s === "completed" && item.output_path) {
        handlePlayItem(item);
      } else if (RETRYABLE_SET.has(s)) {
        await api.queue.retryTrack(item.track.id);
        invalidateQueue();
      } else if (s === "queued") {
        await api.queue.start();
        invalidateQueue();
      }
    },
    [handlePlayItem, invalidateQueue]
  );

  const handleRevealInExplorer = useCallback(async (item: QueueItem) => {
    if (!item.output_path) return;
    try {
      await api.settings.openFolder(item.output_path, true);
    } catch (err) {
      toast.error("Could not reveal file", {
        description: err instanceof Error ? err.message : undefined,
      });
    }
  }, []);

  const handleCopyText = useCallback(async (text: string, label: string) => {
    try {
      await navigator.clipboard.writeText(text);
      toast.success(`Copied ${label}`);
    } catch {
      toast.error("Clipboard copy failed");
    }
  }, []);

  const selectedItems = useMemo(
    () => items.filter((it) => selectedIds.has(it.track.id)),
    [items, selectedIds]
  );

  const hasRetryable = selectedItems.some((it) =>
    RETRYABLE_SET.has(it.status.trim().toLowerCase())
  );
  const hasCancellable = selectedItems.some((it) =>
    CANCELLABLE_SET.has(it.status.trim().toLowerCase())
  );

  const handleRemoveSelected = useCallback(async () => {
    const ids = Array.from(selectedIds);
    if (!ids.length) return;
    await api.queue.removeBatch(ids);
    setSelectedIds(new Set());
    invalidateQueue();
    toast.info(`Removed ${ids.length} track(s) from queue`);
  }, [invalidateQueue, selectedIds]);

  // Global keyboard shortcuts inside QueueView
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "f") {
        if ((stats?.total ?? 0) > 0) {
          e.preventDefault();
          searchInputRef.current?.focus();
          searchInputRef.current?.select();
        }
        return;
      }

      if (isEditableElement(e.target)) return;

      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "a") {
        if (items.length > 0) {
          e.preventDefault();
          setSelectedIds(new Set(items.map((it) => it.track.id)));
        }
      } else if (e.key === "Delete" && selectedIds.size > 0) {
        e.preventDefault();
        void handleRemoveSelected();
      } else if (e.key === "Escape") {
        if (selectedIds.size > 0) {
          setSelectedIds(new Set());
        } else if (searchQuery) {
          setSearchQuery("");
        }
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [handleRemoveSelected, items, searchQuery, selectedIds.size, stats?.total]);

  // Drag & Drop URL handler
  const onDragEnter = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    dragDepthRef.current += 1;
    setDragActive(true);
  };

  const onDragOver = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
  };

  const onDragLeave = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    dragDepthRef.current = Math.max(0, dragDepthRef.current - 1);
    if (dragDepthRef.current === 0) {
      setDragActive(false);
    }
  };

  const onDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    dragDepthRef.current = 0;
    setDragActive(false);
    const droppedUri = e.dataTransfer.getData("text/uri-list");
    const droppedText = e.dataTransfer.getData("text/plain");
    const payload = (droppedUri || droppedText || "").trim();
    if (payload) {
      setUrlInput(payload);
      void submitEnqueueText(payload);
    }
  };

  return (
    <div
      onDragEnter={onDragEnter}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
      className="relative space-y-5"
    >
      <QueueIngestionBar
        value={urlInput}
        onChange={setUrlInput}
        preferredEngine={preferredEngine}
        onEngineChange={setPreferredEngine}
        autoStart={autoStart}
        onAutoStartChange={setAutoStart}
        submitting={submitting}
        onSubmit={() => void submitEnqueueText(urlInput)}
        onPasteClipboard={() => void handlePasteFromClipboard()}
        onOpenFolder={() => void handleOpenFolder()}
      />

      <QueueControlsStrip
        stats={stats}
        paused={paused}
        isLoading={isLoading}
        statusFilter={statusFilter}
        onStatusFilterChange={setStatusFilter}
        searchQuery={searchQuery}
        onSearchChange={setSearchQuery}
        searchInputRef={searchInputRef}
        filteredCount={items.length}
        allVisibleSelected={allVisibleSelected}
        onToggleSelectAll={handleToggleSelectAll}
        onStartAll={() =>
          void api.queue.start().then((r) => {
            invalidateQueue();
            toast.info(`Queue active (${r.started_count} track(s) pending)`);
          })
        }
        onTogglePause={() =>
          void (paused ? api.queue.resume() : api.queue.pause()).then(() => {
            invalidateQueue();
            toast.info(paused ? "Queue resumed" : "Queue paused");
          })
        }
        onStopAll={() =>
          void api.queue.stop().then(() => {
            invalidateQueue();
            toast.warning("Downloads stopped");
          })
        }
        onRetryFailed={() =>
          void api.queue.retryFailed().then((r) => {
            invalidateQueue();
            toast.success(`Re-queued ${r.retried_count} track(s)`);
          })
        }
        onClearCompleted={() =>
          void api.queue.clearCompleted().then(() => {
            invalidateQueue();
            toast.info("Cleared completed tracks");
          })
        }
      />

      <QueueBatchBar
        selectedCount={selectedIds.size}
        hasRetryable={hasRetryable}
        hasCancellable={hasCancellable}
        onRetrySelected={() =>
          void api.queue.retryBatch(Array.from(selectedIds)).then((r) => {
            invalidateQueue();
            toast.success(`Retried ${r.retried_count} selected track(s)`);
          })
        }
        onCancelSelected={() =>
          void api.queue.cancelBatch(Array.from(selectedIds)).then((r) => {
            invalidateQueue();
            toast.info(`Cancelled ${r.cancelled_count} track(s)`);
          })
        }
        onRemoveSelected={() => void handleRemoveSelected()}
        onCopyTitles={() =>
          void handleCopyText(
            selectedItems
              .map((it) => `${it.track.title} - ${it.track.artist_str}`)
              .join("\n"),
            "track titles"
          )
        }
        onCopyLinks={() =>
          void handleCopyText(
            selectedItems
              .map((it) => `https://open.spotify.com/track/${it.track.id}`)
              .join("\n"),
            "Spotify links"
          )
        }
        onClearSelection={() => setSelectedIds(new Set())}
      />

      {(stats?.total ?? 0) === 0 && !isLoading ? (
        <QueueEmptyState
          onPasteFromClipboard={() => void handlePasteFromClipboard()}
          onOpenFolder={() => void handleOpenFolder()}
          onOpenPalette={() => setCommandPaletteOpen(true)}
        />
      ) : (
        <QueueTrackList
          items={items}
          selectedIds={selectedIds}
          liveProgress={liveProgress}
          onRowClick={handleRowClick}
          onCheckboxClick={handleCheckboxClick}
          onDoubleClick={(it) => void handleDoubleClick(it)}
          onPlay={handlePlayItem}
          onRetry={(id) =>
            void api.queue.retryTrack(id).then(() => invalidateQueue())
          }
          onCancel={(id) =>
            void api.queue.cancelTrack(id).then(() => invalidateQueue())
          }
          onRemove={(id) =>
            void api.queue.removeTrack(id).then(() => invalidateQueue())
          }
          onRevealInExplorer={(it) => void handleRevealInExplorer(it)}
          onCopyTitle={(it) =>
            void handleCopyText(
              `${it.track.title} - ${it.track.artist_str}`,
              "track title"
            )
          }
          onCopyLink={(it) =>
            void handleCopyText(
              `https://open.spotify.com/track/${it.track.id}`,
              "Spotify link"
            )
          }
        />
      )}

      {/* Drag & Drop Glass Overlay */}
      <AnimatePresence>
        {dragActive && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-40 flex items-center justify-center bg-black/70 backdrop-blur-sm p-6 pointer-events-none"
          >
            <div className="rounded-3xl border-2 border-dashed border-emerald-400/70 bg-panel/90 px-12 py-10 text-center space-y-2 shadow-2xl">
              <Link2 className="h-9 w-9 mx-auto text-emerald-bright" />
              <div className="text-lg font-semibold text-white">
                Drop Links to Enqueue
              </div>
              <p className="text-xs text-zinc-400">
                Spotify tracks, playlists, albums, or YouTube Music URLs
              </p>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
