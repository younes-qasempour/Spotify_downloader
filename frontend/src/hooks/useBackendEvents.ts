import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { wsUrl } from "@/api/client";
import type { MusilonPrompt, ToolProgressEvent, WsEventEnvelope } from "@/api/types";
import { useAppStore } from "@/stores/appStore";

export function useBackendEvents(): void {
  const queryClient = useQueryClient();

  useEffect(() => {
    let active = true;
    let socket: WebSocket | null = null;
    let reconnectTimer: number | null = null;
    let heartbeatTimer: number | null = null;
    let clearToolTimer: number | null = null;
    let backoffMs = 1000;

    const cleanupTimers = () => {
      if (reconnectTimer !== null) {
        window.clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
      if (heartbeatTimer !== null) {
        window.clearInterval(heartbeatTimer);
        heartbeatTimer = null;
      }
      if (clearToolTimer !== null) {
        window.clearTimeout(clearToolTimer);
        clearToolTimer = null;
      }
    };

    const connect = () => {
      if (!active) return;
      const store = useAppStore.getState();
      store.setWsStatus("connecting");

      try {
        socket = new WebSocket(wsUrl("/ws/events"));
      } catch {
        store.setWsStatus("disconnected");
        reconnectTimer = window.setTimeout(connect, backoffMs);
        backoffMs = Math.min(10000, Math.round(backoffMs * 1.6));
        return;
      }

      socket.onopen = () => {
        if (!active) return;
        backoffMs = 1000;
        useAppStore.getState().setWsStatus("connected");
        heartbeatTimer = window.setInterval(() => {
          if (socket && socket.readyState === WebSocket.OPEN) {
            socket.send(JSON.stringify({ type: "ping" }));
          }
        }, 25000);
      };

      socket.onmessage = (event) => {
        if (!active) return;
        let msg: WsEventEnvelope;
        try {
          msg = JSON.parse(event.data as string) as WsEventEnvelope;
        } catch {
          return;
        }

        const app = useAppStore.getState();
        const payload = msg.payload || {};

        switch (msg.type) {
          case "connected": {
            if (typeof payload.version === "string") {
              app.setBackendVersion(payload.version);
            }
            if (typeof payload.queue_paused === "boolean") {
              app.setQueuePaused(payload.queue_paused);
            }
            if (Array.isArray(payload.pending_prompts)) {
              app.setPendingPrompts(payload.pending_prompts as MusilonPrompt[]);
            }
            break;
          }

          case "track_progress": {
            const trackId = String(payload.track_id || "");
            if (trackId) {
              app.updateTrackProgress(trackId, {
                percent: Number(payload.percent || 0),
                speed: String(payload.speed || ""),
                eta: String(payload.eta || ""),
              });
            }
            break;
          }

          case "track_completed": {
            const trackId = String(payload.track_id || "");
            if (trackId) app.clearTrackProgress(trackId);
            void queryClient.invalidateQueries({ queryKey: ["queue"] });
            void queryClient.invalidateQueries({ queryKey: ["library"] });
            void queryClient.invalidateQueries({ queryKey: ["playlists"] });
            break;
          }

          case "track_failed": {
            const trackId = String(payload.track_id || "");
            if (trackId) app.clearTrackProgress(trackId);
            void queryClient.invalidateQueries({ queryKey: ["queue"] });
            break;
          }

          case "track_enqueued":
          case "tracks_enqueued":
          case "source_resolved":
          case "status_changed":
          case "queue_started":
          case "queue_stopped":
          case "queue_cleared": {
            void queryClient.invalidateQueries({ queryKey: ["queue"] });
            void queryClient.invalidateQueries({ queryKey: ["health"] });
            break;
          }

          case "queue_state_changed": {
            if (typeof payload.paused === "boolean") {
              app.setQueuePaused(payload.paused);
            }
            void queryClient.invalidateQueries({ queryKey: ["queue"] });
            void queryClient.invalidateQueries({ queryKey: ["health"] });
            break;
          }

          case "tracks_removed": {
            if (Array.isArray(payload.track_ids)) {
              for (const rawId of payload.track_ids) {
                if (typeof rawId === "string" && rawId) {
                  app.clearTrackProgress(rawId);
                }
              }
            }
            void queryClient.invalidateQueries({ queryKey: ["queue"] });
            void queryClient.invalidateQueries({ queryKey: ["health"] });
            break;
          }

          case "queue_paused":
            app.setQueuePaused(true);
            void queryClient.invalidateQueries({ queryKey: ["queue"] });
            break;

          case "queue_resumed":
            app.setQueuePaused(false);
            void queryClient.invalidateQueries({ queryKey: ["queue"] });
            break;

          case "musilon_limit_reached": {
            const prompt = payload as unknown as MusilonPrompt;
            app.addPendingPrompt(prompt);
            toast.warning(prompt.title || "Musilon Limit Reached", {
              description: prompt.track?.title
                ? `Action needed for "${prompt.track.title}"`
                : "Resolve prompt in Queue",
            });
            break;
          }

          case "musilon_limit_resolved": {
            const promptId = String(payload.prompt_id || "");
            if (promptId) app.removePendingPrompt(promptId);
            void queryClient.invalidateQueries({ queryKey: ["queue"] });
            break;
          }

          case "playlist_sync_progress": {
            const playlistId = String(payload.playlist_id || "");
            if (playlistId) {
              app.setPlaylistSyncProgress(playlistId, {
                current: Number(payload.current || 0),
                total: Number(payload.total || 0),
              });
            }
            break;
          }

          case "playlists_updated":
            void queryClient.invalidateQueries({ queryKey: ["playlists"] });
            break;

          case "playlist_synced": {
            const playlistId = String(payload.playlist_id || "");
            if (playlistId) {
              app.clearPlaylistSyncProgress(playlistId);
            }
            void queryClient.invalidateQueries({ queryKey: ["playlists"] });
            break;
          }

          case "watched_playlists_synced": {
            const added = Number(payload.total_added || 0);
            if (added > 0) {
              toast.success("Auto-Sync Complete", {
                description: `Discovered ${added} new track(s) across watched playlists.`,
              });
            }
            void queryClient.invalidateQueries({ queryKey: ["playlists"] });
            void queryClient.invalidateQueries({ queryKey: ["queue"] });
            break;
          }

          case "library_updated":
            void queryClient.invalidateQueries({ queryKey: ["library"] });
            break;

          case "config_changed":
            void queryClient.invalidateQueries({ queryKey: ["settings"] });
            break;

          case "tool_progress": {
            const tp: ToolProgressEvent = {
              tool: String(payload.tool || "tool"),
              current: Number(payload.current || 0),
              total: Number(payload.total || 0),
              percent: Number(payload.percent || 0),
              message: String(payload.message || ""),
            };
            app.setActiveToolProgress(tp);
            if (tp.total > 0 && tp.current >= tp.total) {
              if (clearToolTimer !== null) window.clearTimeout(clearToolTimer);
              clearToolTimer = window.setTimeout(() => {
                useAppStore.getState().setActiveToolProgress(null);
              }, 2500);
            }
            break;
          }

          case "tool_completed":
            app.setActiveToolProgress(null);
            if (payload.tool === "ffmpeg_install") {
              if (payload.success) {
                toast.success("FFmpeg Installed", {
                  description: String(payload.path || "Ready for lossless audio."),
                });
              } else {
                toast.error("FFmpeg Installation Failed");
              }
            }
            void queryClient.invalidateQueries({ queryKey: ["settings"] });
            break;

          default:
            break;
        }
      };

      socket.onclose = () => {
        if (!active) return;
        cleanupTimers();
        useAppStore.getState().setWsStatus("disconnected");
        reconnectTimer = window.setTimeout(connect, backoffMs);
        backoffMs = Math.min(10000, Math.round(backoffMs * 1.6));
      };

      socket.onerror = () => {
        socket?.close();
      };
    };

    connect();

    return () => {
      active = false;
      cleanupTimers();
      socket?.close();
    };
  }, [queryClient]);
}
