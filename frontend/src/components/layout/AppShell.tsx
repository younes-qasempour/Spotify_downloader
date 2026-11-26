import { Suspense, useEffect, useRef } from "react";
import { Outlet } from "react-router-dom";
import { Toaster } from "sonner";
import { CloseConfirmModal } from "@/components/layout/CloseConfirmModal";
import { CommandPalette } from "@/components/layout/CommandPalette";
import { PlayerDock } from "@/components/layout/PlayerDock";
import { Sidebar } from "@/components/layout/Sidebar";
import { TopBar } from "@/components/layout/TopBar";
import { AudioEngineController } from "@/components/player/AudioEngineController";
import { EqualizerPopover } from "@/components/player/EqualizerPopover";
import { KaraokeLyricsDrawer } from "@/components/player/KaraokeLyricsDrawer";
import { loadSavedMiniGeometry, MiniPlayer } from "@/components/player/MiniPlayer";
import { MusilonPromptModal } from "@/components/queue/MusilonPromptModal";
import { Skeleton } from "@/components/ui/skeleton";
import { useBackendEvents } from "@/hooks/useBackendEvents";
import {
  enterDesktopMiniPlayer,
  exitDesktopMiniPlayer,
  isDesktopApp,
  listenDesktopCloseRequest,
  listenDesktopMiniPlayerExit,
  listenDesktopMiniPlayerToggle,
} from "@/lib/desktop";
import { useAppStore } from "@/stores/appStore";

function RouteSuspenseFallback() {
  return (
    <div className="space-y-4">
      <div className="glass-panel rounded-2xl p-5 space-y-3">
        <Skeleton className="h-6 w-56" />
        <Skeleton className="h-4 w-80" />
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        <Skeleton className="h-36 rounded-2xl" />
        <Skeleton className="h-36 rounded-2xl" />
        <Skeleton className="h-36 rounded-2xl" />
      </div>
    </div>
  );
}

export function AppShell() {
  useBackendEvents();

  const miniPlayerOpen = useAppStore((s) => s.miniPlayerOpen);
  const toggleMiniPlayer = useAppStore((s) => s.toggleMiniPlayer);
  const desktop = isDesktopApp();
  const wasDesktopMiniRef = useRef(false);

  // Sync Tauri desktop window geometry between Full App and Studio Mini Player
  useEffect(() => {
    if (!desktop) return;
    if (miniPlayerOpen) {
      wasDesktopMiniRef.current = true;
      const geo = loadSavedMiniGeometry();
      const pinned = useAppStore.getState().miniPlayerPinned;
      void enterDesktopMiniPlayer(geo.width, geo.height, pinned);
    } else if (wasDesktopMiniRef.current) {
      wasDesktopMiniRef.current = false;
      void exitDesktopMiniPlayer();
    }
  }, [desktop, miniPlayerOpen]);

  // Global Alt+M shortcut & desktop System Tray toggle
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.altKey && !e.ctrlKey && !e.metaKey && e.key.toLowerCase() === "m") {
        if (
          e.target instanceof HTMLElement &&
          ["input", "textarea", "select"].includes(e.target.tagName.toLowerCase())
        ) {
          return;
        }
        e.preventDefault();
        toggleMiniPlayer();
      }
    };
    window.addEventListener("keydown", onKeyDown);

    let unlistenToggle = () => {};
    let unlistenExit = () => {};
    let unlistenClose = () => {};
    let active = true;
    if (desktop) {
      void listenDesktopMiniPlayerToggle(() => {
        useAppStore.getState().toggleMiniPlayer();
      }).then((fn) => {
        if (active) unlistenToggle = fn;
        else fn();
      });
      void listenDesktopMiniPlayerExit(() => {
        useAppStore.getState().setMiniPlayerOpen(false);
      }).then((fn) => {
        if (active) unlistenExit = fn;
        else fn();
      });
      void listenDesktopCloseRequest(() => {
        useAppStore.getState().setCloseConfirmOpen(true);
      }).then((fn) => {
        if (active) unlistenClose = fn;
        else fn();
      });
    }

    return () => {
      active = false;
      window.removeEventListener("keydown", onKeyDown);
      unlistenToggle();
      unlistenExit();
      unlistenClose();
    };
  }, [desktop, toggleMiniPlayer]);

  if (miniPlayerOpen && desktop) {
    return (
      <>
        <MiniPlayer mode="desktop" />
        <AudioEngineController />
        <Toaster theme="dark" position="bottom-right" richColors />
      </>
    );
  }

  return (
    <div className="flex h-screen supports-[height:100dvh]:h-dvh w-screen overflow-hidden bg-canvas text-zinc-100">
      <Sidebar />

      <div className="relative flex flex-1 flex-col min-w-0 overflow-hidden ambient-stage-bg">
        <TopBar />

        <main className="flex-1 overflow-y-auto px-4 md:px-7 pt-6 pb-40 sm:pb-32">
          <div className="mx-auto w-full max-w-[1440px]">
            <Suspense fallback={<RouteSuspenseFallback />}>
              <Outlet />
            </Suspense>
          </div>
        </main>

        <div className="pointer-events-none absolute inset-x-0 bottom-0 z-30 pb-[env(safe-area-inset-bottom)]">
          <div className="pointer-events-auto mx-auto max-w-[1440px]">
            <PlayerDock />
          </div>
        </div>
      </div>

      {miniPlayerOpen && !desktop && <MiniPlayer mode="web" />}
      <AudioEngineController />
      <EqualizerPopover />
      <KaraokeLyricsDrawer />
      <CommandPalette />
      <MusilonPromptModal />
      <CloseConfirmModal />
      <Toaster
        theme="dark"
        position="bottom-right"
        offset={{ bottom: 108, right: 20 }}
        richColors
      />
    </div>
  );
}
