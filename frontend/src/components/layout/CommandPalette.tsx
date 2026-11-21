import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import {
  CornerDownLeft,
  Download,
  FolderOpen,
  Library,
  ListMusic,
  PanelLeft,
  Pause,
  PictureInPicture2,
  Play,
  RefreshCw,
  Search,
  Settings,
  SlidersHorizontal,
  Sparkles,
  Wrench,
} from "lucide-react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { api } from "@/api/endpoints";
import { cn, isMediaUrl } from "@/lib/utils";
import { useAppStore } from "@/stores/appStore";

interface PaletteCommand {
  id: string;
  section: "URL Action" | "Navigation" | "Saved Playlists" | "Quick Actions";
  title: string;
  subtitle?: string;
  icon: React.ComponentType<{ className?: string }>;
  keywords?: string;
  run: () => void | Promise<void>;
}

export function CommandPalette() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const open = useAppStore((s) => s.commandPaletteOpen);
  const setOpen = useAppStore((s) => s.setCommandPaletteOpen);
  const toggleCommandPalette = useAppStore((s) => s.toggleCommandPalette);
  const queuePaused = useAppStore((s) => s.queuePaused);
  const toggleSidebar = useAppStore((s) => s.toggleSidebar);
  const toggleLyricsDrawer = useAppStore((s) => s.toggleLyricsDrawer);
  const toggleEqPopover = useAppStore((s) => s.toggleEqPopover);
  const toggleMiniPlayer = useAppStore((s) => s.toggleMiniPlayer);

  const [query, setQuery] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const { data: playlistsData } = useQuery({
    queryKey: ["playlists"],
    queryFn: () => api.playlists.list(),
    staleTime: 30000,
  });

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        toggleCommandPalette();
      } else if (e.key === "Escape" && open) {
        e.preventDefault();
        setOpen(false);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, setOpen, toggleCommandPalette]);

  useEffect(() => {
    if (open) {
      setQuery("");
      setSelectedIndex(0);
      const timer = window.setTimeout(() => inputRef.current?.focus(), 20);
      return () => window.clearTimeout(timer);
    }
  }, [open]);

  const trimmedQuery = query.trim();
  const hasMediaUrl = isMediaUrl(trimmedQuery);

  const commands = useMemo<PaletteCommand[]>(() => {
    const list: PaletteCommand[] = [];

    if (hasMediaUrl) {
      list.push({
        id: "enqueue-url",
        section: "URL Action",
        title: "Enqueue & Start Download",
        subtitle: trimmedQuery,
        icon: Sparkles,
        run: async () => {
          try {
            const res = await api.queue.enqueue({
              input: trimmedQuery,
              auto_start: true,
            });
            void queryClient.invalidateQueries({ queryKey: ["queue"] });
            toast.success(`Queued ${res.enqueued_count} track(s)`, {
              description: res.started ? "Download started automatically." : undefined,
            });
            navigate("/");
          } catch (err) {
            toast.error("Could not enqueue URL", {
              description: err instanceof Error ? err.message : "Unknown error",
            });
          }
        },
      });
    }

    list.push(
      {
        id: "nav-queue",
        section: "Navigation",
        title: "Go to Download Queue",
        subtitle: "Live transfers, URL bar & Musilon prompts",
        icon: Download,
        keywords: "home downloads active queue",
        run: () => navigate("/"),
      },
      {
        id: "nav-playlists",
        section: "Navigation",
        title: "Go to Saved Playlists",
        subtitle: "Offline mirrors & Auto-Sync",
        icon: ListMusic,
        keywords: "spotify mirror sync",
        run: () => navigate("/playlists"),
      },
      {
        id: "nav-library",
        section: "Navigation",
        title: "Go to Offline Library",
        subtitle: "All downloaded tracks, playlists & albums",
        icon: Library,
        keywords: "songs music albums flac mp3",
        run: () => navigate("/library"),
      },
      {
        id: "nav-tools",
        section: "Navigation",
        title: "Go to Audio Tools Studio",
        subtitle: "Spectrum audit, duplicate merger, exporters",
        icon: Wrench,
        keywords: "spectrum duplicates m3u8 export normalize replaygain",
        run: () => navigate("/tools"),
      },
      {
        id: "nav-settings",
        section: "Navigation",
        title: "Go to Settings",
        subtitle: "Musilon, MeloBot Telegram, Spotify API, FFmpeg",
        icon: Settings,
        keywords: "preferences auth cookies telegram",
        run: () => navigate("/settings"),
      }
    );

    const playlists = playlistsData?.playlists ?? [];
    for (const pl of playlists) {
      list.push({
        id: `playlist-${pl.id}`,
        section: "Saved Playlists",
        title: pl.name,
        subtitle: `${pl.downloaded_count}/${pl.total_tracks} downloaded${pl.auto_sync ? " · Auto-Sync On" : ""}`,
        icon: ListMusic,
        keywords: `playlist ${pl.name}`,
        run: () => navigate(`/playlists/${pl.id}`),
      });
    }

    list.push(
      {
        id: "act-toggle-queue",
        section: "Quick Actions",
        title: queuePaused ? "Resume Queue" : "Pause Queue",
        subtitle: queuePaused
          ? "Resume waiting downloads"
          : "Pause active queue transfers",
        icon: queuePaused ? Play : Pause,
        keywords: "queue pause resume start",
        run: async () => {
          try {
            if (queuePaused) {
              await api.queue.resume();
              toast.info("Queue resumed");
            } else {
              await api.queue.pause();
              toast.info("Queue paused");
            }
            void queryClient.invalidateQueries({ queryKey: ["queue"] });
          } catch (err) {
            toast.error("Queue command failed", {
              description: err instanceof Error ? err.message : undefined,
            });
          }
        },
      },
      {
        id: "act-autosync",
        section: "Quick Actions",
        title: "Run Auto-Sync Across Watched Playlists",
        subtitle: "Check pinned playlists for newly added songs",
        icon: RefreshCw,
        keywords: "sync pinned watched update",
        run: async () => {
          try {
            const res = await api.playlists.runAutoSync();
            void queryClient.invalidateQueries({ queryKey: ["playlists"] });
            toast.success("Auto-Sync Finished", {
              description: `Checked ${res.checked_count} playlist(s), added ${res.total_added} track(s).`,
            });
          } catch (err) {
            toast.error("Auto-Sync failed", {
              description: err instanceof Error ? err.message : undefined,
            });
          }
        },
      },
      {
        id: "act-rescan",
        section: "Quick Actions",
        title: "Rescan Library Download Folder",
        subtitle: "Re-index downloaded files into SQLite archive",
        icon: RefreshCw,
        keywords: "rescan index disk library",
        run: async () => {
          try {
            const res = await api.library.rescan();
            void queryClient.invalidateQueries({ queryKey: ["library"] });
            toast.success("Library Rescanned", {
              description: `Indexed ${res.indexed} file(s).`,
            });
          } catch (err) {
            toast.error("Library rescan failed", {
              description: err instanceof Error ? err.message : undefined,
            });
          }
        },
      },
      {
        id: "act-open-folder",
        section: "Quick Actions",
        title: "Open Download Folder",
        subtitle: "Reveal downloads directory on disk",
        icon: FolderOpen,
        keywords: "explorer finder directory folder",
        run: async () => {
          try {
            await api.settings.openFolder();
          } catch (err) {
            toast.error("Could not open download folder", {
              description: err instanceof Error ? err.message : undefined,
            });
          }
        },
      },
      {
        id: "act-lyrics",
        section: "Quick Actions",
        title: "Toggle Lyrics Drawer",
        icon: ListMusic,
        keywords: "karaoke lrc lyrics",
        run: () => toggleLyricsDrawer(),
      },
      {
        id: "act-eq",
        section: "Quick Actions",
        title: "Toggle 10-Band Equalizer",
        icon: SlidersHorizontal,
        keywords: "eq audio dsp equalizer",
        run: () => toggleEqPopover(),
      },
      {
        id: "act-mini-player",
        section: "Quick Actions",
        title: "Toggle Studio Mini Player",
        subtitle: "Resizable PiP / Always-on-top mini player (Alt+M)",
        icon: PictureInPicture2,
        keywords: "mini player pip float compact visualizer",
        run: () => toggleMiniPlayer(),
      },
      {
        id: "act-sidebar",
        section: "Quick Actions",
        title: "Toggle Sidebar Width",
        icon: PanelLeft,
        keywords: "collapse expand navigation",
        run: () => toggleSidebar(),
      }
    );

    if (!trimmedQuery || hasMediaUrl) {
      return list;
    }

    const q = trimmedQuery.toLowerCase();
    return list.filter(
      (cmd) =>
        cmd.title.toLowerCase().includes(q) ||
        (cmd.subtitle && cmd.subtitle.toLowerCase().includes(q)) ||
        (cmd.keywords && cmd.keywords.toLowerCase().includes(q))
    );
  }, [
    hasMediaUrl,
    navigate,
    playlistsData?.playlists,
    queryClient,
    queuePaused,
    toggleEqPopover,
    toggleLyricsDrawer,
    toggleMiniPlayer,
    toggleSidebar,
    trimmedQuery,
  ]);

  const execute = (cmd: PaletteCommand | undefined) => {
    if (!cmd) return;
    setOpen(false);
    void cmd.run();
  };

  useEffect(() => {
    setSelectedIndex(0);
  }, [trimmedQuery]);

  const handleInputKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSelectedIndex((prev) =>
        commands.length ? (prev + 1) % commands.length : 0
      );
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSelectedIndex((prev) =>
        commands.length ? (prev - 1 + commands.length) % commands.length : 0
      );
    } else if (e.key === "Enter") {
      e.preventDefault();
      execute(commands[selectedIndex] ?? commands[0]);
    }
  };

  return (
    <AnimatePresence>
      {open && (
        <div className="fixed inset-0 z-50 flex items-start justify-center pt-[12vh] px-4">
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={() => setOpen(false)}
            className="fixed inset-0 bg-black/75 backdrop-blur-sm"
          />

          <motion.div
            initial={{ opacity: 0, scale: 0.96, y: -10 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.96, y: -10 }}
            transition={{ duration: 0.16, ease: "easeOut" }}
            className="relative z-10 w-full max-w-xl overflow-hidden rounded-2xl glass-panel shadow-2xl"
          >
            {/* Search input */}
            <div className="flex items-center gap-3 border-b border-white/[0.08] px-4 py-3.5">
              <Search className="h-4 w-4 text-zinc-400 shrink-0" />
              <input
                ref={inputRef}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={handleInputKeyDown}
                placeholder="Paste Spotify/YouTube link, jump to playlist, or run a command..."
                className="flex-1 bg-transparent text-sm text-white placeholder:text-zinc-500 focus:outline-none"
              />
              <kbd className="rounded-md bg-white/[0.06] px-1.5 py-0.5 text-[10px] font-mono text-zinc-400 border border-white/[0.08]">
                ESC
              </kbd>
            </div>

            {/* Results */}
            <div className="max-h-[380px] overflow-y-auto p-2 space-y-1">
              {commands.length === 0 ? (
                <div className="py-10 text-center text-sm text-zinc-500">
                  No matching playlists, views, or actions.
                </div>
              ) : (
                commands.map((cmd, idx) => {
                  const Icon = cmd.icon;
                  const active = idx === selectedIndex;
                  const showSectionHeader =
                    idx === 0 || commands[idx - 1].section !== cmd.section;
                  return (
                    <div key={cmd.id}>
                      {showSectionHeader && (
                        <div className="px-3 pt-2 pb-1 text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
                          {cmd.section}
                        </div>
                      )}
                      <button
                        type="button"
                        onMouseEnter={() => setSelectedIndex(idx)}
                        onClick={() => execute(cmd)}
                        className={cn(
                          "flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left transition-colors cursor-pointer",
                          active
                            ? "bg-emerald-500/15 text-white border border-emerald-500/25"
                            : "text-zinc-300 border border-transparent hover:bg-white/[0.04]"
                        )}
                      >
                        <Icon
                          className={cn(
                            "h-4 w-4 shrink-0",
                            active ? "text-emerald-bright" : "text-zinc-400"
                          )}
                        />
                        <div className="min-w-0 flex-1">
                          <div className="text-sm font-medium truncate">
                            {cmd.title}
                          </div>
                          {cmd.subtitle && (
                            <div className="text-[11px] text-zinc-400 truncate">
                              {cmd.subtitle}
                            </div>
                          )}
                        </div>
                        {active && (
                          <CornerDownLeft className="h-3.5 w-3.5 text-emerald-400 shrink-0" />
                        )}
                      </button>
                    </div>
                  );
                })
              )}
            </div>
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  );
}
