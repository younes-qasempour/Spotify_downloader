import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import {
  AlertTriangle,
  Disc3,
  Settings,
  ShieldAlert,
  Square,
  Youtube,
} from "lucide-react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { api } from "@/api/endpoints";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useAppStore } from "@/stores/appStore";

export function MusilonPromptModal() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const pendingPrompts = useAppStore((s) => s.pendingPrompts);
  const removePendingPrompt = useAppStore((s) => s.removePendingPrompt);
  const [submitting, setSubmitting] = useState(false);

  const activePrompt = pendingPrompts[0];

  const handleResolve = async (
    action: "continue_youtube" | "stop",
    openSettingsAfter = false
  ) => {
    if (!activePrompt || submitting) return;
    setSubmitting(true);
    try {
      await api.queue.resolvePrompt(activePrompt.prompt_id, action);
      removePendingPrompt(activePrompt.prompt_id);
      void queryClient.invalidateQueries({ queryKey: ["queue"] });
      if (action === "continue_youtube") {
        toast.info("Continuing via YouTube Music fallback");
      } else {
        toast.warning("Downloads stopped cleanly");
      }
      if (openSettingsAfter) {
        navigate("/settings");
      }
    } catch (err) {
      toast.error("Failed to submit decision", {
        description: err instanceof Error ? err.message : undefined,
      });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <AnimatePresence>
      {activePrompt && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/75 backdrop-blur-sm"
          />

          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 12 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 12 }}
            transition={{ duration: 0.18, ease: "easeOut" }}
            className="relative z-10 w-full max-w-lg overflow-hidden rounded-2xl glass-panel p-6 shadow-2xl space-y-4 border border-amber-500/30"
          >
            {/* Header */}
            <div className="flex items-start justify-between gap-3">
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-amber-500/15 text-amber-300 border border-amber-500/30">
                  {activePrompt.category === "vip" ? (
                    <ShieldAlert className="h-5 w-5" />
                  ) : (
                    <AlertTriangle className="h-5 w-5" />
                  )}
                </div>
                <div>
                  <h2 className="text-base font-semibold text-white">
                    {activePrompt.title}
                  </h2>
                  <p className="text-xs text-zinc-400">
                    {activePrompt.description}
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-2">
                {pendingPrompts.length > 1 && (
                  <Badge variant="default" className="font-mono">
                    1 / {pendingPrompts.length}
                  </Badge>
                )}
                <Badge
                  variant={activePrompt.category === "vip" ? "gold" : "danger"}
                  className="uppercase"
                >
                  {activePrompt.category}
                </Badge>
              </div>
            </div>

            {/* Affected Track Card */}
            <div className="flex items-center gap-3 rounded-xl bg-white/[0.04] border border-white/[0.08] p-3">
              <div className="h-12 w-12 shrink-0 overflow-hidden rounded-lg bg-elevated border border-white/[0.06]">
                {activePrompt.track.cover_url ? (
                  <img
                    src={activePrompt.track.cover_url}
                    alt={activePrompt.track.title}
                    className="h-full w-full object-cover"
                  />
                ) : (
                  <div className="flex h-full w-full items-center justify-center text-zinc-500">
                    <Disc3 className="h-5 w-5" />
                  </div>
                )}
              </div>
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-semibold text-white">
                  {activePrompt.track.title}
                </div>
                <div className="truncate text-xs text-zinc-400">
                  {activePrompt.track.artist_str}
                  {activePrompt.track.album ? ` · ${activePrompt.track.album}` : ""}
                </div>
              </div>
            </div>

            {/* Reason Diagnostic */}
            <div className="rounded-xl bg-black/40 border border-white/[0.07] p-3 text-xs font-mono text-amber-200/90 break-words">
              {activePrompt.reason}
            </div>

            <p className="text-sm text-zinc-300 leading-relaxed">
              {activePrompt.action_prompt}
            </p>

            {/* Footer Actions */}
            <div className="flex flex-wrap items-center justify-end gap-2 pt-2 border-t border-white/[0.06]">
              {activePrompt.category === "vip" && (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={submitting}
                  onClick={() => void handleResolve("stop", true)}
                >
                  <Settings className="h-3.5 w-3.5" />
                  Stop & Fix in Settings
                </Button>
              )}

              <Button
                type="button"
                variant="destructive"
                disabled={submitting}
                onClick={() => void handleResolve("stop")}
              >
                <Square className="h-3.5 w-3.5" />
                Stop Downloading
              </Button>

              <Button
                type="button"
                variant="default"
                disabled={submitting}
                onClick={() => void handleResolve("continue_youtube")}
              >
                <Youtube className="h-4 w-4" />
                Continue on YouTube Music
              </Button>
            </div>
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  );
}
