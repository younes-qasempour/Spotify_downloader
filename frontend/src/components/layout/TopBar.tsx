import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  Command,
  Copy,
  Menu,
  Minus,
  PanelBottomClose,
  PauseCircle,
  Search,
  Square,
  X,
} from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";
import { api } from "@/api/endpoints";
import {
  hideDesktopToTray,
  isDesktopApp,
  isDesktopWindowMaximized,
  minimizeDesktopWindow,
  toggleMaximizeDesktopWindow,
} from "@/lib/desktop";
import { useAppStore } from "@/stores/appStore";

function useRouteMeta() {
  const { pathname } = useLocation();
  if (pathname === "/") {
    return {
      title: "Download Queue",
      subtitle: "Lossless resolving & multi-engine transfer pipeline",
    };
  }
  if (pathname === "/playlists") {
    return {
      title: "Saved Playlists",
      subtitle: "Offline mirror collections & Auto-Sync monitors",
    };
  }
  if (pathname.startsWith("/playlists/")) {
    return {
      title: "Playlist Explorer",
      subtitle: "Inspect, batch-download, reconcile & export tracks",
    };
  }
  if (pathname.startsWith("/library")) {
    return {
      title: "Offline Library",
      subtitle: "Browse downloaded songs, playlists & albums",
    };
  }
  if (pathname.startsWith("/tools")) {
    return {
      title: "Audio Tools Studio",
      subtitle: "Spectrum audit, duplicate merger, loudness & portable export",
    };
  }
  if (pathname.startsWith("/settings")) {
    return {
      title: "Settings",
      subtitle: "Engines, credentials, storage, FFmpeg & maintenance",
    };
  }
  return {
    title: "Flacify",
    subtitle: "Lossless Audio Studio",
  };
}

export function TopBar() {
  const navigate = useNavigate();
  const meta = useRouteMeta();
  const desktop = isDesktopApp();
  const [maximized, setMaximized] = useState(false);

  const setMobileNavOpen = useAppStore((s) => s.setMobileNavOpen);
  const setCommandPaletteOpen = useAppStore((s) => s.setCommandPaletteOpen);
  const setCloseConfirmOpen = useAppStore((s) => s.setCloseConfirmOpen);
  const pendingPrompts = useAppStore((s) => s.pendingPrompts);
  const queuePaused = useAppStore((s) => s.queuePaused);

  useEffect(() => {
    if (!desktop) return;
    let active = true;
    const syncMax = () => {
      void isDesktopWindowMaximized()
        .then((val) => {
          if (active) setMaximized(val);
        })
        .catch(() => {});
    };
    syncMax();
    window.addEventListener("resize", syncMax);
    return () => {
      active = false;
      window.removeEventListener("resize", syncMax);
    };
  }, [desktop]);

  const { data: queueData } = useQuery({
    queryKey: ["queue"],
    queryFn: () => api.queue.list(),
    staleTime: 10000,
  });

  const activeCount = queueData?.stats.active ?? 0;

  return (
    <header
      data-tauri-drag-region={desktop ? true : undefined}
      onDoubleClick={(e) => {
        if (!desktop) return;
        const target = e.target as HTMLElement;
        if (target.closest("button, a, input")) return;
        void toggleMaximizeDesktopWindow().then(() =>
          isDesktopWindowMaximized().then(setMaximized)
        );
      }}
      className="sticky top-0 z-20 flex h-14 shrink-0 items-center justify-between gap-3 border-b border-white/[0.06] bg-canvas/70 px-4 md:px-7 backdrop-blur-xl select-none"
    >
      <div
        data-tauri-drag-region={desktop ? true : undefined}
        className="flex items-center gap-3 min-w-0"
      >
        <button
          type="button"
          onClick={() => setMobileNavOpen(true)}
          className="lg:hidden rounded-lg p-2 text-zinc-300 hover:bg-white/8 hover:text-white cursor-pointer"
          aria-label="Open navigation"
        >
          <Menu className="h-5 w-5" />
        </button>

        <div
          data-tauri-drag-region={desktop ? true : undefined}
          className="min-w-0"
        >
          <h1
            data-tauri-drag-region={desktop ? true : undefined}
            className="text-sm md:text-base font-semibold tracking-tight text-white truncate"
          >
            {meta.title}
          </h1>
          <p
            data-tauri-drag-region={desktop ? true : undefined}
            className="hidden sm:block text-[11px] text-zinc-400 truncate"
          >
            {meta.subtitle}
          </p>
        </div>
      </div>

      {/* Right controls */}
      <div className="flex items-center gap-2.5">
        {pendingPrompts.length > 0 && (
          <button
            type="button"
            onClick={() => navigate("/")}
            className="inline-flex items-center gap-1.5 rounded-full bg-amber-500/15 border border-amber-500/35 px-3 py-1 text-xs font-medium text-amber-300 hover:bg-amber-500/25 transition-colors cursor-pointer"
          >
            <AlertTriangle className="h-3.5 w-3.5" />
            <span>{pendingPrompts.length} Action Needed</span>
          </button>
        )}

        {activeCount > 0 && (
          <button
            type="button"
            onClick={() => navigate("/")}
            className="hidden sm:inline-flex items-center gap-1.5 rounded-full bg-emerald-500/12 border border-emerald-500/30 px-3 py-1 text-xs font-medium text-emerald-300 cursor-pointer"
          >
            {queuePaused ? (
              <PauseCircle className="h-3.5 w-3.5 text-amber-300" />
            ) : (
              <span className="h-2 w-2 rounded-full bg-emerald-bright animate-pulse" />
            )}
            <span className="font-mono tabular-nums">
              {queuePaused ? "Paused" : `${activeCount} Active`}
            </span>
          </button>
        )}

        <button
          type="button"
          onClick={() => setCommandPaletteOpen(true)}
          className="flex items-center gap-2.5 rounded-xl border border-white/[0.09] bg-white/[0.04] hover:bg-white/[0.08] px-3 py-1.5 text-xs text-zinc-400 hover:text-zinc-200 transition-colors cursor-pointer"
        >
          <Search className="h-3.5 w-3.5 text-zinc-400" />
          <span className="hidden md:inline">
            Jump, paste URL, or run tool...
          </span>
          <span className="md:hidden">Search...</span>
          <kbd className="hidden sm:inline-flex items-center gap-0.5 rounded-md bg-white/[0.07] px-1.5 py-0.5 text-[10px] font-mono text-zinc-300 border border-white/[0.08]">
            <Command className="h-2.5 w-2.5" />K
          </kbd>
        </button>

        {desktop && (
          <div className="flex items-center gap-0.5 pl-2 ml-1 border-l border-white/[0.08]">
            <button
              type="button"
              onClick={() => void hideDesktopToTray()}
              className="rounded-lg p-1.5 text-zinc-400 hover:bg-white/10 hover:text-zinc-100 transition-colors cursor-pointer"
              title="Minimize to System Tray"
              aria-label="Hide to Tray"
            >
              <PanelBottomClose className="h-3.5 w-3.5" />
            </button>
            <button
              type="button"
              onClick={() => void minimizeDesktopWindow()}
              className="rounded-lg p-1.5 text-zinc-400 hover:bg-white/10 hover:text-white transition-colors cursor-pointer"
              title="Minimize Window"
              aria-label="Minimize"
            >
              <Minus className="h-3.5 w-3.5" />
            </button>
            <button
              type="button"
              onClick={() =>
                void toggleMaximizeDesktopWindow().then(() =>
                  isDesktopWindowMaximized().then(setMaximized)
                )
              }
              className="rounded-lg p-1.5 text-zinc-400 hover:bg-white/10 hover:text-white transition-colors cursor-pointer"
              title={maximized ? "Restore Window" : "Maximize Window"}
              aria-label={maximized ? "Restore" : "Maximize"}
            >
              {maximized ? (
                <Copy className="h-3.5 w-3.5" />
              ) : (
                <Square className="h-3.5 w-3.5" />
              )}
            </button>
            <button
              type="button"
              onClick={() => setCloseConfirmOpen(true)}
              className="rounded-lg p-1.5 text-zinc-400 hover:bg-red-500/80 hover:text-white transition-colors cursor-pointer"
              title="Close Window"
              aria-label="Close"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        )}
      </div>
    </header>
  );
}
