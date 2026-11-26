import { useEffect, useRef } from "react";
import { apiUrl } from "@/api/client";
import { api } from "@/api/endpoints";
import { audioEngine } from "@/lib/audioEngine";
import { useAppStore } from "@/stores/appStore";
import { usePlayerStore } from "@/stores/playerStore";

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName.toLowerCase();
  return (
    tag === "input" ||
    tag === "textarea" ||
    tag === "select" ||
    tag === "button" ||
    target.isContentEditable
  );
}

export function AudioEngineController() {
  const wsStatus = useAppStore((s) => s.wsStatus);
  const currentTrack = usePlayerStore((s) => s.currentTrack);
  const reloadNonce = usePlayerStore((s) => s.reloadNonce);
  const isPlaying = usePlayerStore((s) => s.isPlaying);
  const seekRequest = usePlayerStore((s) => s.seekRequest);
  const volume = usePlayerStore((s) => s.volume);
  const muted = usePlayerStore((s) => s.muted);
  const volumeHydrated = usePlayerStore((s) => s.volumeHydrated);
  const eq = usePlayerStore((s) => s.eq);

  const loadedKeyRef = useRef<string>("");
  const lastSeekSeqRef = useRef<number>(0);
  const volumePersistInitializedRef = useRef(false);
  const eqHydratedRef = useRef(false);
  const volumeConfigHydratedRef = useRef(false);

  // Hydrate initial EQ settings & saved player volume from backend config (retries on WS connect)
  useEffect(() => {
    if (eqHydratedRef.current && volumeConfigHydratedRef.current) return;
    let active = true;

    if (!eqHydratedRef.current) {
      void api.tools
        .getEq()
        .then((res) => {
          if (!active) return;
          eqHydratedRef.current = true;
          usePlayerStore
            .getState()
            .hydrateEq(res.config, res.presets, res.frequencies);
          audioEngine.applyEqualizer(res.config);
        })
        .catch(() => {
          // Ignore if backend is still booting; retries when wsStatus === "connected"
        });
    }

    if (!volumeConfigHydratedRef.current) {
      void api.settings
        .get()
        .then((res) => {
          if (!active) return;
          volumeConfigHydratedRef.current = true;
          const pct = Number(res.config.ui?.player_volume ?? 100);
          if (Number.isFinite(pct)) {
            usePlayerStore.getState().hydrateVolume(pct / 100);
          }
        })
        .catch(() => {});
    }

    return () => {
      active = false;
    };
  }, [wsStatus]);

  // Wire HTML5 audio element listeners -> Zustand store
  useEffect(() => {
    const audio = audioEngine.audio;

    const onTimeUpdate = () => {
      usePlayerStore.getState().setCurrentTime(audio.currentTime || 0);
    };
    const onDurationChange = () => {
      if (Number.isFinite(audio.duration) && audio.duration > 0) {
        usePlayerStore.getState().setDuration(audio.duration);
      }
    };
    const onPlaying = () => {
      const st = usePlayerStore.getState();
      st.setBuffering(false);
      st.setAudioError(null);
      if (!st.isPlaying) st.setPlaying(true);
    };
    const onPause = () => {
      const st = usePlayerStore.getState();
      if (!audio.ended && st.isPlaying && audio.src) {
        st.setPlaying(false);
      }
    };
    const onWaiting = () => {
      usePlayerStore.getState().setBuffering(true);
    };
    const onCanPlay = () => {
      usePlayerStore.getState().setBuffering(false);
    };
    const onEnded = () => {
      const st = usePlayerStore.getState();
      if (st.repeatMode === "one") {
        audio.currentTime = 0;
        void audioEngine.play().catch(() => {});
        return;
      }
      st.nextTrack();
    };
    const onError = () => {
      if (!audio.getAttribute("src")) return;
      const st = usePlayerStore.getState();
      st.setBuffering(false);
      st.setPlaying(false);
      st.setAudioError("Could not decode or stream audio file.");
    };

    audio.addEventListener("timeupdate", onTimeUpdate);
    audio.addEventListener("loadedmetadata", onDurationChange);
    audio.addEventListener("durationchange", onDurationChange);
    audio.addEventListener("playing", onPlaying);
    audio.addEventListener("pause", onPause);
    audio.addEventListener("waiting", onWaiting);
    audio.addEventListener("canplay", onCanPlay);
    audio.addEventListener("ended", onEnded);
    audio.addEventListener("error", onError);

    return () => {
      audio.removeEventListener("timeupdate", onTimeUpdate);
      audio.removeEventListener("loadedmetadata", onDurationChange);
      audio.removeEventListener("durationchange", onDurationChange);
      audio.removeEventListener("playing", onPlaying);
      audio.removeEventListener("pause", onPause);
      audio.removeEventListener("waiting", onWaiting);
      audio.removeEventListener("canplay", onCanPlay);
      audio.removeEventListener("ended", onEnded);
      audio.removeEventListener("error", onError);
    };
  }, []);

  // Load new track audio source + update OS MediaSession metadata
  useEffect(() => {
    if (!currentTrack) {
      loadedKeyRef.current = "";
      audioEngine.releaseSource();
      if ("mediaSession" in navigator) {
        navigator.mediaSession.metadata = null;
        navigator.mediaSession.playbackState = "none";
      }
      return;
    }

    const nextKey = `${currentTrack.id}|${reloadNonce}`;
    if (loadedKeyRef.current !== nextKey) {
      loadedKeyRef.current = nextKey;
      const rawUrl = apiUrl(currentTrack.audioUrl);
      const srcUrl =
        reloadNonce > 0
          ? `${rawUrl}${rawUrl.includes("?") ? "&" : "?"}v=${reloadNonce}`
          : rawUrl;
      audioEngine.loadAndPlay(srcUrl, usePlayerStore.getState().isPlaying);
    }

    if ("mediaSession" in navigator) {
      const cover = currentTrack.coverUrl
        ? currentTrack.coverUrl.startsWith("http")
          ? currentTrack.coverUrl
          : apiUrl(currentTrack.coverUrl)
        : undefined;
      navigator.mediaSession.metadata = new MediaMetadata({
        title: currentTrack.title,
        artist: currentTrack.artist,
        album: currentTrack.album || "",
        artwork: cover
          ? [{ src: cover, sizes: "512x512", type: "image/jpeg" }]
          : [],
      });
    }
  }, [currentTrack, reloadNonce]);

  // Register MediaSession hardware / OS media key handlers
  useEffect(() => {
    if (!("mediaSession" in navigator)) return;
    const ms = navigator.mediaSession;
    ms.setActionHandler("play", () => usePlayerStore.getState().setPlaying(true));
    ms.setActionHandler("pause", () =>
      usePlayerStore.getState().setPlaying(false)
    );
    ms.setActionHandler("previoustrack", () =>
      usePlayerStore.getState().prevTrack()
    );
    ms.setActionHandler("nexttrack", () =>
      usePlayerStore.getState().nextTrack()
    );
    ms.setActionHandler("seekto", (details) => {
      if (typeof details.seekTime === "number") {
        usePlayerStore.getState().seek(details.seekTime);
      }
    });
    ms.setActionHandler("seekbackward", (details) => {
      const offset = details.seekOffset ?? 10;
      const cur = usePlayerStore.getState().currentTimeSec;
      usePlayerStore.getState().seek(Math.max(0, cur - offset));
    });
    ms.setActionHandler("seekforward", (details) => {
      const offset = details.seekOffset ?? 10;
      const cur = usePlayerStore.getState().currentTimeSec;
      usePlayerStore.getState().seek(cur + offset);
    });
  }, []);

  // Sync play/pause transitions to audioEngine
  useEffect(() => {
    if (!currentTrack) return;
    if ("mediaSession" in navigator) {
      navigator.mediaSession.playbackState = isPlaying ? "playing" : "paused";
    }
    if (isPlaying) {
      if (audioEngine.audio.paused && audioEngine.audio.getAttribute("src")) {
        void audioEngine.play().catch((err) => {
          usePlayerStore
            .getState()
            .setAudioError(
              err instanceof Error ? err.message : "Playback blocked by browser."
            );
          usePlayerStore.getState().setPlaying(false);
        });
      }
    } else if (!audioEngine.audio.paused) {
      audioEngine.pause();
    }
  }, [currentTrack, isPlaying]);

  // Apply explicit seek requests
  useEffect(() => {
    if (!seekRequest || seekRequest.seq === lastSeekSeqRef.current) return;
    lastSeekSeqRef.current = seekRequest.seq;
    audioEngine.seek(seekRequest.timeSec);
  }, [seekRequest]);

  // Sync volume + persist ui.player_volume with debounce
  useEffect(() => {
    audioEngine.setVolume(volume, muted);
    if (!volumeHydrated) return;
    if (!volumePersistInitializedRef.current) {
      volumePersistInitializedRef.current = true;
      return;
    }
    const timer = window.setTimeout(() => {
      void api.settings
        .patch({ "ui.player_volume": Math.round((muted ? 0 : volume) * 100) })
        .catch(() => {});
    }, 350);
    return () => window.clearTimeout(timer);
  }, [muted, volume, volumeHydrated]);

  // Apply zero-latency live 10-band Web Audio DSP on EQ updates
  useEffect(() => {
    if (eq.enabled) {
      audioEngine.ensureGraph();
    }
    audioEngine.applyEqualizer(eq);
  }, [eq]);

  // Global Spacebar Play/Pause shortcut
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.code === "Space" && !e.ctrlKey && !e.metaKey && !e.altKey) {
        if (isEditableTarget(e.target)) return;
        const st = usePlayerStore.getState();
        if (st.currentTrack) {
          e.preventDefault();
          st.togglePlay();
        }
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  return null;
}
