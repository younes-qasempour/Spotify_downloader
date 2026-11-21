import type { EqualizerConfig } from "@/api/types";
import { DEFAULT_EQ_FREQUENCIES } from "@/stores/playerStore";

class FlacifyAudioEngine {
  readonly audio: HTMLAudioElement;
  private ctx: AudioContext | null = null;
  private sourceNode: MediaElementAudioSourceNode | null = null;
  private preampGain: GainNode | null = null;
  private bassShelf: BiquadFilterNode | null = null;
  private bandFilters: BiquadFilterNode[] = [];
  private limiter: DynamicsCompressorNode | null = null;
  private graphInitFailed = false;
  private currentEq: EqualizerConfig | null = null;

  constructor() {
    this.audio = new Audio();
    this.audio.crossOrigin = "anonymous";
    this.audio.preload = "auto";
  }

  ensureGraph(): void {
    if (this.ctx || this.graphInitFailed) return;
    const AudioCtx =
      window.AudioContext ||
      (window as unknown as { webkitAudioContext?: typeof AudioContext })
        .webkitAudioContext;
    if (!AudioCtx) {
      this.graphInitFailed = true;
      return;
    }

    try {
      const ctx = new AudioCtx();
      const source = ctx.createMediaElementSource(this.audio);
      const preamp = ctx.createGain();
      preamp.gain.value = 1;

      const bassShelf = ctx.createBiquadFilter();
      bassShelf.type = "lowshelf";
      bassShelf.frequency.value = 85;
      bassShelf.gain.value = 0;

      const filters = DEFAULT_EQ_FREQUENCIES.map((freq) => {
        const f = ctx.createBiquadFilter();
        f.type = "peaking";
        f.frequency.value = freq;
        f.Q.value = 1.41;
        f.gain.value = 0;
        return f;
      });

      const limiter = ctx.createDynamicsCompressor();
      limiter.threshold.value = -1.0;
      limiter.knee.value = 6.0;
      limiter.ratio.value = 12.0;
      limiter.attack.value = 0.003;
      limiter.release.value = 0.15;

      let tail: AudioNode = source;
      tail.connect(preamp);
      tail = preamp;
      tail.connect(bassShelf);
      tail = bassShelf;
      for (const f of filters) {
        tail.connect(f);
        tail = f;
      }
      tail.connect(limiter);
      limiter.connect(ctx.destination);

      this.ctx = ctx;
      this.sourceNode = source;
      this.preampGain = preamp;
      this.bassShelf = bassShelf;
      this.bandFilters = filters;
      this.limiter = limiter;

      if (this.currentEq) {
        this.applyEqualizer(this.currentEq);
      }
    } catch {
      this.graphInitFailed = true;
    }
  }

  async resumeContext(): Promise<void> {
    this.ensureGraph();
    if (this.ctx && this.ctx.state === "suspended") {
      try {
        await this.ctx.resume();
      } catch {
        // Ignore resume failure if outside user gesture
      }
    }
  }

  applyEqualizer(eq: EqualizerConfig): void {
    this.currentEq = eq;
    if (
      !this.ctx ||
      !this.preampGain ||
      !this.bassShelf ||
      this.bandFilters.length !== 10
    ) {
      return;
    }

    const now = this.ctx.currentTime;
    const tau = 0.015;
    if (!eq.enabled) {
      this.preampGain.gain.setTargetAtTime(1.0, now, tau);
      this.bassShelf.gain.setTargetAtTime(0, now, tau);
      for (const f of this.bandFilters) {
        f.gain.setTargetAtTime(0, now, tau);
      }
      return;
    }

    const linearPreamp = Math.pow(10, (eq.preamp || 0) / 20);
    this.preampGain.gain.setTargetAtTime(linearPreamp, now, tau);
    this.bassShelf.gain.setTargetAtTime(eq.bass_boost || 0, now, tau);
    this.bandFilters.forEach((f, idx) => {
      const db = Number(eq.bands?.[idx] ?? 0);
      f.gain.setTargetAtTime(Math.max(-12, Math.min(12, db)), now, tau);
    });
  }

  setVolume(volume: number, muted: boolean): void {
    this.audio.volume = Math.max(0, Math.min(1, volume));
    this.audio.muted = muted;
  }

  loadAndPlay(url: string, autoPlay: boolean): void {
    this.audio.src = url;
    this.audio.load();
    if (autoPlay) {
      void this.play();
    }
  }

  async play(): Promise<void> {
    await this.resumeContext();
    await this.audio.play();
  }

  pause(): void {
    this.audio.pause();
  }

  seek(timeSec: number): void {
    if (!Number.isFinite(timeSec)) return;
    const dur = this.audio.duration;
    const target = Number.isFinite(dur) && dur > 0
      ? Math.max(0, Math.min(dur, timeSec))
      : Math.max(0, timeSec);
    this.audio.currentTime = target;
  }

  /**
   * Releases open HTTP stream & underlying file handles on Windows before
   * permanent FFmpeg EQ baking overwrites the audio file on disk.
   */
  releaseSource(): void {
    this.audio.pause();
    this.audio.removeAttribute("src");
    this.audio.load();
  }

  get hasWebAudio(): boolean {
    return Boolean(this.ctx && this.sourceNode && this.limiter);
  }
}

export const audioEngine = new FlacifyAudioEngine();
