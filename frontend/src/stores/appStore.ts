import { create } from "zustand";
import type { MusilonPrompt, ToolProgressEvent } from "@/api/types";
import {
  applyAmbientColor,
  DEFAULT_AMBIENT_RGB,
  type RgbColor,
} from "@/lib/colorExtract";

export type WsConnectionStatus = "connecting" | "connected" | "disconnected";

export interface LiveTrackProgress {
  percent: number;
  speed: string;
  eta: string;
}

export interface PlaylistSyncProgress {
  current: number;
  total: number;
}

interface AppState {
  sidebarCollapsed: boolean;
  mobileNavOpen: boolean;
  commandPaletteOpen: boolean;
  lyricsDrawerOpen: boolean;
  eqPopoverOpen: boolean;
  miniPlayerOpen: boolean;
  miniPlayerPinned: boolean;
  ambientColor: RgbColor;

  wsStatus: WsConnectionStatus;
  backendVersion: string;
  queuePaused: boolean;
  pendingPrompts: MusilonPrompt[];
  liveProgress: Record<string, LiveTrackProgress>;
  playlistSyncProgress: Record<string, PlaylistSyncProgress>;
  activeToolProgress: ToolProgressEvent | null;

  toggleSidebar: () => void;
  setMobileNavOpen: (open: boolean) => void;
  setCommandPaletteOpen: (open: boolean) => void;
  toggleCommandPalette: () => void;
  setLyricsDrawerOpen: (open: boolean) => void;
  toggleLyricsDrawer: () => void;
  setEqPopoverOpen: (open: boolean) => void;
  toggleEqPopover: () => void;
  setMiniPlayerOpen: (open: boolean) => void;
  toggleMiniPlayer: () => void;
  setMiniPlayerPinned: (pinned: boolean) => void;
  toggleMiniPlayerPinned: () => void;
  setAmbientColor: (rgb: RgbColor) => void;
  resetAmbientColor: () => void;

  setWsStatus: (status: WsConnectionStatus) => void;
  setBackendVersion: (version: string) => void;
  setQueuePaused: (paused: boolean) => void;
  setPendingPrompts: (prompts: MusilonPrompt[]) => void;
  addPendingPrompt: (prompt: MusilonPrompt) => void;
  removePendingPrompt: (promptId: string) => void;
  updateTrackProgress: (trackId: string, progress: LiveTrackProgress) => void;
  clearTrackProgress: (trackId: string) => void;
  setPlaylistSyncProgress: (
    playlistId: string,
    progress: PlaylistSyncProgress
  ) => void;
  clearPlaylistSyncProgress: (playlistId: string) => void;
  setActiveToolProgress: (progress: ToolProgressEvent | null) => void;
}

export const useAppStore = create<AppState>((set) => ({
  sidebarCollapsed: false,
  mobileNavOpen: false,
  commandPaletteOpen: false,
  lyricsDrawerOpen: false,
  eqPopoverOpen: false,
  miniPlayerOpen: false,
  miniPlayerPinned: true,
  ambientColor: DEFAULT_AMBIENT_RGB,

  wsStatus: "connecting",
  backendVersion: "2.1.0",
  queuePaused: false,
  pendingPrompts: [],
  liveProgress: {},
  playlistSyncProgress: {},
  activeToolProgress: null,

  toggleSidebar: () =>
    set((state) => ({ sidebarCollapsed: !state.sidebarCollapsed })),
  setMobileNavOpen: (open) => set({ mobileNavOpen: open }),
  setCommandPaletteOpen: (open) => set({ commandPaletteOpen: open }),
  toggleCommandPalette: () =>
    set((state) => ({ commandPaletteOpen: !state.commandPaletteOpen })),
  setLyricsDrawerOpen: (open) => set({ lyricsDrawerOpen: open }),
  toggleLyricsDrawer: () =>
    set((state) => ({ lyricsDrawerOpen: !state.lyricsDrawerOpen })),
  setEqPopoverOpen: (open) => set({ eqPopoverOpen: open }),
  toggleEqPopover: () =>
    set((state) => ({ eqPopoverOpen: !state.eqPopoverOpen })),
  setMiniPlayerOpen: (miniPlayerOpen) => set({ miniPlayerOpen }),
  toggleMiniPlayer: () =>
    set((state) => ({ miniPlayerOpen: !state.miniPlayerOpen })),
  setMiniPlayerPinned: (miniPlayerPinned) => set({ miniPlayerPinned }),
  toggleMiniPlayerPinned: () =>
    set((state) => ({ miniPlayerPinned: !state.miniPlayerPinned })),

  setAmbientColor: (rgb) => {
    applyAmbientColor(rgb);
    set({ ambientColor: rgb });
  },
  resetAmbientColor: () => {
    applyAmbientColor(DEFAULT_AMBIENT_RGB);
    set({ ambientColor: DEFAULT_AMBIENT_RGB });
  },

  setWsStatus: (wsStatus) => set({ wsStatus }),
  setBackendVersion: (backendVersion) => set({ backendVersion }),
  setQueuePaused: (queuePaused) => set({ queuePaused }),
  setPendingPrompts: (pendingPrompts) => set({ pendingPrompts }),
  addPendingPrompt: (prompt) =>
    set((state) => {
      if (state.pendingPrompts.some((p) => p.prompt_id === prompt.prompt_id)) {
        return state;
      }
      return { pendingPrompts: [...state.pendingPrompts, prompt] };
    }),
  removePendingPrompt: (promptId) =>
    set((state) => ({
      pendingPrompts: state.pendingPrompts.filter(
        (p) => p.prompt_id !== promptId
      ),
    })),

  updateTrackProgress: (trackId, progress) =>
    set((state) => ({
      liveProgress: {
        ...state.liveProgress,
        [trackId]: progress,
      },
    })),
  clearTrackProgress: (trackId) =>
    set((state) => {
      if (!(trackId in state.liveProgress)) return state;
      const next = { ...state.liveProgress };
      delete next[trackId];
      return { liveProgress: next };
    }),
  setPlaylistSyncProgress: (playlistId, progress) =>
    set((state) => ({
      playlistSyncProgress: {
        ...state.playlistSyncProgress,
        [playlistId]: progress,
      },
    })),
  clearPlaylistSyncProgress: (playlistId) =>
    set((state) => {
      if (!(playlistId in state.playlistSyncProgress)) return state;
      const next = { ...state.playlistSyncProgress };
      delete next[playlistId];
      return { playlistSyncProgress: next };
    }),
  setActiveToolProgress: (activeToolProgress) => set({ activeToolProgress }),
}));
