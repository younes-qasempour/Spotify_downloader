import { create } from "zustand";
import type {
  EqualizerConfig,
  EqualizerPreset,
  PlayerTrack,
} from "@/api/types";

export type RepeatMode = "off" | "all" | "one";

export const DEFAULT_EQ_FREQUENCIES = [
  31, 62, 125, 250, 500, 1000, 2000, 4000, 8000, 16000,
];

export const DEFAULT_EQ_CONFIG: EqualizerConfig = {
  enabled: false,
  preset: "Flat (Default)",
  preamp: 0,
  bass_boost: 0,
  bands: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
};

interface PlayerState {
  currentTrack: PlayerTrack | null;
  queue: PlayerTrack[];
  currentIndex: number;
  isPlaying: boolean;
  isBuffering: boolean;
  audioError: string | null;
  currentTimeSec: number;
  durationSec: number;
  seekRequest: { timeSec: number; seq: number } | null;
  reloadNonce: number;
  volume: number;
  volumeHydrated: boolean;
  muted: boolean;
  shuffle: boolean;
  repeatMode: RepeatMode;

  eq: EqualizerConfig;
  eqPresets: Record<string, EqualizerPreset>;
  eqFrequencies: number[];
  eqDirtyVersion: number;

  setTrack: (track: PlayerTrack) => void;
  playTrackList: (tracks: PlayerTrack[], startIndex?: number) => void;
  playQueueIndex: (index: number) => void;
  togglePlay: () => void;
  setPlaying: (playing: boolean) => void;
  setBuffering: (buffering: boolean) => void;
  setAudioError: (error: string | null) => void;
  setCurrentTime: (timeSec: number) => void;
  seek: (timeSec: number) => void;
  setDuration: (durationSec: number) => void;
  bumpReloadNonce: () => void;
  nextTrack: () => void;
  prevTrack: () => void;
  hydrateVolume: (vol0to1: number) => void;
  setVolume: (volume: number) => void;
  toggleMute: () => void;
  toggleShuffle: () => void;
  cycleRepeat: () => void;

  hydrateEq: (
    config: EqualizerConfig,
    presets: Record<string, EqualizerPreset>,
    frequencies: number[]
  ) => void;
  setEqEnabled: (enabled: boolean) => void;
  setEqPreset: (presetName: string) => void;
  setEqPreamp: (preamp: number) => void;
  setEqBassBoost: (bassBoost: number) => void;
  setEqBand: (index: number, db: number) => void;
  resetEqFlat: () => void;
}

export const usePlayerStore = create<PlayerState>((set, get) => ({
  currentTrack: null,
  queue: [],
  currentIndex: -1,
  isPlaying: false,
  isBuffering: false,
  audioError: null,
  currentTimeSec: 0,
  durationSec: 0,
  seekRequest: null,
  reloadNonce: 0,
  volume: 0.9,
  volumeHydrated: false,
  muted: false,
  shuffle: false,
  repeatMode: "off",

  eq: { ...DEFAULT_EQ_CONFIG, bands: [...DEFAULT_EQ_CONFIG.bands] },
  eqPresets: {},
  eqFrequencies: [...DEFAULT_EQ_FREQUENCIES],
  eqDirtyVersion: 0,

  setTrack: (track) =>
    set({
      currentTrack: track,
      queue: [track],
      currentIndex: 0,
      isPlaying: true,
      isBuffering: true,
      audioError: null,
      currentTimeSec: 0,
      durationSec: track.durationSec || 0,
    }),

  playTrackList: (tracks, startIndex = 0) => {
    if (!tracks.length) return;
    const clampedIdx = Math.max(0, Math.min(tracks.length - 1, startIndex));
    const track = tracks[clampedIdx];
    set({
      currentTrack: track,
      queue: tracks,
      currentIndex: clampedIdx,
      isPlaying: true,
      isBuffering: true,
      audioError: null,
      currentTimeSec: 0,
      durationSec: track.durationSec || 0,
    });
  },

  playQueueIndex: (index) => {
    const { queue } = get();
    if (!queue.length || index < 0 || index >= queue.length) return;
    const track = queue[index];
    set({
      currentTrack: track,
      currentIndex: index,
      isPlaying: true,
      isBuffering: true,
      audioError: null,
      currentTimeSec: 0,
      durationSec: track.durationSec || 0,
    });
  },

  togglePlay: () =>
    set((state) =>
      state.currentTrack ? { isPlaying: !state.isPlaying } : state
    ),

  setPlaying: (isPlaying) => set({ isPlaying }),

  setBuffering: (isBuffering) => set({ isBuffering }),

  setAudioError: (audioError) => set({ audioError }),

  setCurrentTime: (currentTimeSec) => set({ currentTimeSec }),

  seek: (timeSec) =>
    set((state) => {
      const clamped = Math.max(0, timeSec);
      const nextSeq = (state.seekRequest?.seq ?? 0) + 1;
      return {
        currentTimeSec: clamped,
        seekRequest: { timeSec: clamped, seq: nextSeq },
      };
    }),

  setDuration: (durationSec) => set({ durationSec }),

  bumpReloadNonce: () =>
    set((state) => ({ reloadNonce: state.reloadNonce + 1 })),

  nextTrack: () => {
    const { queue, currentIndex, shuffle, repeatMode, seekRequest } = get();
    if (!queue.length) return;

    if (repeatMode === "one") {
      set({
        currentTimeSec: 0,
        isPlaying: true,
        seekRequest: { timeSec: 0, seq: (seekRequest?.seq ?? 0) + 1 },
      });
      return;
    }

    let nextIndex = currentIndex + 1;
    if (shuffle && queue.length > 1) {
      let rand = Math.floor(Math.random() * queue.length);
      if (rand === currentIndex) {
        rand = (currentIndex + 1) % queue.length;
      }
      nextIndex = rand;
    } else if (nextIndex >= queue.length) {
      if (repeatMode === "all") {
        nextIndex = 0;
      } else {
        set({ isPlaying: false });
        return;
      }
    }

    const next = queue[nextIndex];
    set({
      currentTrack: next,
      currentIndex: nextIndex,
      currentTimeSec: 0,
      durationSec: next.durationSec || 0,
      isPlaying: true,
      isBuffering: true,
      audioError: null,
    });
  },

  prevTrack: () => {
    const { queue, currentIndex, currentTimeSec, seekRequest } = get();
    if (!queue.length) return;
    if (currentTimeSec > 3) {
      set({
        currentTimeSec: 0,
        seekRequest: { timeSec: 0, seq: (seekRequest?.seq ?? 0) + 1 },
      });
      return;
    }
    const prevIndex = currentIndex > 0 ? currentIndex - 1 : queue.length - 1;
    const prev = queue[prevIndex];
    set({
      currentTrack: prev,
      currentIndex: prevIndex,
      currentTimeSec: 0,
      durationSec: prev.durationSec || 0,
      isPlaying: true,
      isBuffering: true,
      audioError: null,
    });
  },

  hydrateVolume: (vol0to1) =>
    set({
      volume: Math.max(0, Math.min(1, vol0to1)),
      muted: vol0to1 <= 0,
      volumeHydrated: true,
    }),

  setVolume: (volume) =>
    set({
      volume: Math.max(0, Math.min(1, volume)),
      muted: volume <= 0,
      volumeHydrated: true,
    }),

  toggleMute: () => set((state) => ({ muted: !state.muted })),

  toggleShuffle: () => set((state) => ({ shuffle: !state.shuffle })),

  cycleRepeat: () =>
    set((state) => ({
      repeatMode:
        state.repeatMode === "off"
          ? "all"
          : state.repeatMode === "all"
            ? "one"
            : "off",
    })),

  hydrateEq: (config, presets, frequencies) =>
    set({
      eq: {
        enabled: Boolean(config.enabled),
        preset: config.preset || "Flat (Default)",
        preamp: Number(config.preamp ?? 0),
        bass_boost: Number(config.bass_boost ?? 0),
        bands:
          Array.isArray(config.bands) && config.bands.length === 10
            ? config.bands.map(Number)
            : [...DEFAULT_EQ_CONFIG.bands],
      },
      eqPresets: presets || {},
      eqFrequencies:
        Array.isArray(frequencies) && frequencies.length === 10
          ? frequencies
          : [...DEFAULT_EQ_FREQUENCIES],
    }),

  setEqEnabled: (enabled) =>
    set((state) => ({
      eq: { ...state.eq, enabled },
      eqDirtyVersion: state.eqDirtyVersion + 1,
    })),

  setEqPreset: (presetName) =>
    set((state) => {
      const p = state.eqPresets[presetName];
      if (!p) {
        return {
          eq: { ...state.eq, preset: presetName },
          eqDirtyVersion: state.eqDirtyVersion + 1,
        };
      }
      return {
        eq: {
          enabled: presetName !== "Flat (Default)" ? true : state.eq.enabled,
          preset: presetName,
          preamp: Number(p.preamp ?? 0),
          bass_boost: Number(p.bass_boost ?? 0),
          bands:
            Array.isArray(p.bands) && p.bands.length === 10
              ? p.bands.map(Number)
              : [...DEFAULT_EQ_CONFIG.bands],
        },
        eqDirtyVersion: state.eqDirtyVersion + 1,
      };
    }),

  setEqPreamp: (preamp) =>
    set((state) => ({
      eq: {
        ...state.eq,
        preset: "Custom",
        preamp: Math.max(-12, Math.min(12, preamp)),
      },
      eqDirtyVersion: state.eqDirtyVersion + 1,
    })),

  setEqBassBoost: (bassBoost) =>
    set((state) => ({
      eq: {
        ...state.eq,
        preset: "Custom",
        bass_boost: Math.max(0, Math.min(12, bassBoost)),
      },
      eqDirtyVersion: state.eqDirtyVersion + 1,
    })),

  setEqBand: (index, db) =>
    set((state) => {
      const clamped = Math.max(-12, Math.min(12, db));
      const nextBands = [...state.eq.bands];
      if (index >= 0 && index < 10) {
        nextBands[index] = clamped;
      }
      const autoEnable =
        !state.eq.enabled && Math.abs(clamped) >= 0.2 ? true : state.eq.enabled;
      return {
        eq: {
          ...state.eq,
          enabled: autoEnable,
          preset: "Custom",
          bands: nextBands,
        },
        eqDirtyVersion: state.eqDirtyVersion + 1,
      };
    }),

  resetEqFlat: () =>
    set((state) => ({
      eq: {
        enabled: false,
        preset: "Flat (Default)",
        preamp: 0,
        bass_boost: 0,
        bands: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
      },
      eqDirtyVersion: state.eqDirtyVersion + 1,
    })),
}));
