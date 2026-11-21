import { useEffect, useRef } from "react";
import { audioEngine } from "@/lib/audioEngine";
import { cn } from "@/lib/utils";
import { useAppStore } from "@/stores/appStore";

interface SpectrumVisualizerCanvasProps {
  isPlaying: boolean;
  barCount?: number;
  className?: string;
}

export function SpectrumVisualizerCanvas({
  isPlaying,
  barCount = 28,
  className,
}: SpectrumVisualizerCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const ambientColor = useAppStore((s) => s.ambientColor);
  const smoothRef = useRef<Float32Array>(new Float32Array(barCount));

  useEffect(() => {
    if (smoothRef.current.length !== barCount) {
      smoothRef.current = new Float32Array(barCount);
    }
  }, [barCount]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let rafId = 0;
    const freqBuffer = new Uint8Array(64);
    const [r, g, b] = ambientColor;

    const resize = () => {
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      const w = Math.max(1, Math.floor(canvas.clientWidth * dpr));
      const h = Math.max(1, Math.floor(canvas.clientHeight * dpr));
      if (canvas.width !== w || canvas.height !== h) {
        canvas.width = w;
        canvas.height = h;
      }
    };

    const observer = new ResizeObserver(() => resize());
    observer.observe(canvas);
    resize();

    const drawFrame = () => {
      const w = canvas.width;
      const h = canvas.height;
      ctx.clearRect(0, 0, w, h);

      const hasFft = isPlaying && audioEngine.getFrequencyData(freqBuffer);
      const smooth = smoothRef.current;
      const nowSec = performance.now() / 1000;

      const step = w / barCount;
      const gap = Math.max(1.5, step * 0.28);
      const barW = Math.max(2, step - gap);

      const grad = ctx.createLinearGradient(0, h, 0, 0);
      grad.addColorStop(0, `rgba(${r}, ${g}, ${b}, 0.85)`);
      grad.addColorStop(0.6, "rgba(30, 215, 96, 0.92)");
      grad.addColorStop(1, "rgba(255, 255, 255, 0.95)");

      for (let i = 0; i < barCount; i++) {
        let target = 0.08;
        if (hasFft) {
          // Focus mostly on audible musical spectrum bins (bins 1..44)
          const binIdx = Math.min(
            freqBuffer.length - 1,
            Math.max(0, Math.floor(Math.pow(i / barCount, 1.2) * 44))
          );
          target = Math.max(0.08, freqBuffer[binIdx] / 255);
        } else if (isPlaying) {
          // Fallback gentle harmonic wave if CORS/context wasn't initialized yet
          const wave =
            0.35 +
            0.25 * Math.sin(nowSec * 6.2 + i * 0.55) +
            0.2 * Math.cos(nowSec * 3.7 - i * 0.35);
          target = Math.max(0.1, Math.min(0.95, wave));
        }

        const prev = smooth[i] ?? 0.08;
        smooth[i] =
          target > prev ? prev * 0.45 + target * 0.55 : prev * 0.82 + target * 0.18;

        const barH = Math.max(3, smooth[i] * (h - 2));
        const x = i * step + gap * 0.5;
        const y = h - barH;
        const radius = Math.min(barW / 2, barH / 2, 3);

        ctx.fillStyle = grad;
        ctx.beginPath();
        ctx.roundRect(x, y, barW, barH, radius);
        ctx.fill();
      }

      if (isPlaying) {
        rafId = window.requestAnimationFrame(drawFrame);
      }
    };

    drawFrame();

    return () => {
      observer.disconnect();
      if (rafId) window.cancelAnimationFrame(rafId);
    };
  }, [ambientColor, barCount, isPlaying]);

  return (
    <canvas
      ref={canvasRef}
      className={cn("block w-full h-full pointer-events-none", className)}
    />
  );
}
