import { Suspense } from "react";
import { Outlet } from "react-router-dom";
import { Toaster } from "sonner";
import { CommandPalette } from "@/components/layout/CommandPalette";
import { PlayerDock } from "@/components/layout/PlayerDock";
import { Sidebar } from "@/components/layout/Sidebar";
import { TopBar } from "@/components/layout/TopBar";
import { AudioEngineController } from "@/components/player/AudioEngineController";
import { EqualizerPopover } from "@/components/player/EqualizerPopover";
import { KaraokeLyricsDrawer } from "@/components/player/KaraokeLyricsDrawer";
import { MusilonPromptModal } from "@/components/queue/MusilonPromptModal";
import { Skeleton } from "@/components/ui/skeleton";
import { useBackendEvents } from "@/hooks/useBackendEvents";

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

      <AudioEngineController />
      <EqualizerPopover />
      <KaraokeLyricsDrawer />
      <CommandPalette />
      <MusilonPromptModal />
      <Toaster
        theme="dark"
        position="bottom-right"
        offset={{ bottom: 108, right: 20 }}
        richColors
      />
    </div>
  );
}
