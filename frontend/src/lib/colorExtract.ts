export type RgbColor = [number, number, number];

export const DEFAULT_AMBIENT_RGB: RgbColor = [29, 185, 84];

export function applyAmbientColor(rgb: RgbColor): void {
  const root = document.documentElement;
  root.style.setProperty("--ambient-r", String(rgb[0]));
  root.style.setProperty("--ambient-g", String(rgb[1]));
  root.style.setProperty("--ambient-b", String(rgb[2]));
}

export function extractAmbientColor(imageUrl: string): Promise<RgbColor | null> {
  return new Promise((resolve) => {
    if (!imageUrl) {
      resolve(null);
      return;
    }

    const img = new Image();
    img.crossOrigin = "anonymous";

    img.onload = () => {
      try {
        const size = 24;
        const canvas = document.createElement("canvas");
        canvas.width = size;
        canvas.height = size;
        const ctx = canvas.getContext("2d", { willReadFrequently: true });
        if (!ctx) {
          resolve(null);
          return;
        }
        ctx.drawImage(img, 0, 0, size, size);
        const { data } = ctx.getImageData(0, 0, size, size);

        let rSum = 0;
        let gSum = 0;
        let bSum = 0;
        let weightSum = 0;

        for (let i = 0; i < data.length; i += 4) {
          const r = data[i];
          const g = data[i + 1];
          const b = data[i + 2];
          const a = data[i + 3];
          if (a < 128) continue;

          const maxC = Math.max(r, g, b);
          const minC = Math.min(r, g, b);
          const luma = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
          const sat = maxC === 0 ? 0 : (maxC - minC) / maxC;

          if (luma < 0.08 || luma > 0.92) continue;

          const weight = 0.25 + sat * 2.5 + (1 - Math.abs(luma - 0.5));
          rSum += r * weight;
          gSum += g * weight;
          bSum += b * weight;
          weightSum += weight;
        }

        if (weightSum <= 0) {
          resolve(null);
          return;
        }

        const r = Math.min(245, Math.max(32, Math.round(rSum / weightSum)));
        const g = Math.min(245, Math.max(32, Math.round(gSum / weightSum)));
        const b = Math.min(245, Math.max(32, Math.round(bSum / weightSum)));
        resolve([r, g, b]);
      } catch {
        resolve(null);
      }
    };

    img.onerror = () => resolve(null);
    img.src = imageUrl;
  });
}
