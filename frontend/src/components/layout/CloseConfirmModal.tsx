import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import {
  AlertTriangle,
  Loader2,
  Music2,
  PanelBottomClose,
  Power,
  Wrench,
  X,
} from "lucide-react";
import { api } from "@/api/endpoints";
import { Button } from "@/components/ui/button";
import { hideDesktopToTray, quitDesktopApp } from "@/lib/desktop";
import { useAppStore } from "@/stores/appStore";
import { usePlayerStore } from "@/stores/playerStore";

export function CloseConfirmModal() {
  const open = useAppStore((s) => s.closeConfirmOpen);
  const setOpen = useAppStore((s) => s.setCloseConfirmOpen);
  const activeToolProgress = useAppStore((s) => s.activeToolProgress);
  const isPlaying = usePlayerStore((s) => s.isPlaying);
  const [closing, setClosing] = useState(false);

  const { data: queueData } = useQuery({
    queryKey: ["queue"],
    queryFn: () => api.queue.list(),
    enabled: open,
  });

  const activeDownloads =
    (queueData?.stats.active ?? 0) + (queueData?.stats.queued ?? 0);

  useEffect(() => {
    if (!open) {
      setClosing(false);
      return;
    }
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !closing) {
        e.preventDefault();
        setOpen(false);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, closing, setOpen]);

  const handleHideToTray = () => {
    if (closing) return;
    setOpen(false);
    void hideDesktopToTray();
  };

  const handleConfirmClose = async () => {
    if (closing) return;
    setClosing(true);
    try {
      usePlayerStore.getState().setPlaying(false);
      await quitDesktopApp();
    } catch {
      setClosing(false);
    }
  };

  const hasActiveTasks =
    activeDownloads > 0 || Boolean(activeToolProgress) || isPlaying;

  return (
    <AnimatePresence>
      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={() => {
              if (!closing) setOpen(false);
            }}
            className="fixed inset-0 bg-black/70 backdrop-blur-sm"
          />

          <motion.div
            role="dialog"
            aria-modal="true"
            aria-labelledby="close-confirm-title"
            initial={{ opacity: 0, scale: 0.96, y: 8 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.96, y: 8 }}
            transition={{ duration: 0.16 }}
            className="relative z-10 w-full max-w-md rounded-2xl glass-panel border border-white/12 p-5 shadow-2xl space-y-4"
          >
            <div className="flex items-start justify-between gap-3">
              <div className="flex items-center gap-3 min-w-0">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-amber-500/15 border border-amber-500/30 text-amber-300">
                  <AlertTriangle className="h-5 w-5" />
                </div>
                <div className="min-w-0">
                  <h2
                    id="close-confirm-title"
                    className="text-base font-semibold text-white"
                  >
                    Close Flacify?
                  </h2>
                  <p className="text-xs text-zinc-400">
                    Confirm exiting the app and stopping background services.
                  </p>
                </div>
              </div>

              <button
                type="button"
                disabled={closing}
                onClick={() => setOpen(false)}
                aria-label="Cancel"
                className="rounded-lg p-1.5 text-zinc-400 hover:bg-white/10 hover:text-white disabled:opacity-40 cursor-pointer"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <p className="text-xs leading-relaxed text-zinc-300">
              Closing Flacify will shut down the desktop window, terminate the
              local backend server, and stop Wi-Fi Mobile Sync until you launch
              it again. If you want it to stay running quietly in the
              background, choose <span className="text-white font-medium">Hide to Tray</span>.
            </p>

            {hasActiveTasks && (
              <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-3 space-y-1.5">
                <div className="text-[11px] font-semibold uppercase tracking-wide text-amber-300">
                  Active in Background
                </div>
                {activeDownloads > 0 && (
                  <div className="flex items-center gap-2 text-xs text-amber-100">
                    <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-amber-300" />
                    <span>
                      {activeDownloads} download{activeDownloads === 1 ? "" : "s"}{" "}
                      currently active or queued — will be stopped.
                    </span>
                  </div>
                )}
                {activeToolProgress && (
                  <div className="flex items-center gap-2 text-xs text-amber-100">
                    <Wrench className="h-3.5 w-3.5 shrink-0 text-amber-300" />
                    <span>
                      Audio tool running ({activeToolProgress.tool}) — will be
                      interrupted.
                    </span>
                  </div>
                )}
                {isPlaying && (
                  <div className="flex items-center gap-2 text-xs text-amber-100">
                    <Music2 className="h-3.5 w-3.5 shrink-0 text-amber-300" />
                    <span>Audio playback is active — will stop.</span>
                  </div>
                )}
              </div>
            )}

            <div className="flex flex-wrap items-center justify-end gap-2 pt-1">
              <Button
                type="button"
                size="sm"
                variant="ghost"
                disabled={closing}
                onClick={() => setOpen(false)}
              >
                Cancel
              </Button>
              <Button
                type="button"
                size="sm"
                variant="secondary"
                disabled={closing}
                onClick={handleHideToTray}
              >
                <PanelBottomClose className="h-3.5 w-3.5" />
                Hide to Tray
              </Button>
              <Button
                type="button"
                size="sm"
                variant="destructive"
                disabled={closing}
                onClick={() => void handleConfirmClose()}
              >
                {closing ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Power className="h-3.5 w-3.5" />
                )}
                {closing ? "Closing..." : "Close Everything"}
              </Button>
            </div>
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  );
}
