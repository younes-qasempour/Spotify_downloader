import path from "node:path";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes("node_modules")) return undefined;
          if (id.includes("framer-motion")) return "vendor-motion";
          if (
            id.includes("react-router") ||
            id.includes("react-dom") ||
            id.includes("node_modules/react/") ||
            id.includes("node_modules\\react\\") ||
            id.includes("scheduler")
          ) {
            return "vendor-react";
          }
          if (id.includes("@tanstack") || id.includes("zustand")) {
            return "vendor-state";
          }
          if (id.includes("lucide-react") || id.includes("sonner")) {
            return "vendor-ui";
          }
          return undefined;
        },
      },
    },
  },
  server: {
    port: 5173,
    host: true,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8765",
        changeOrigin: true,
      },
      "/ws": {
        target: "ws://127.0.0.1:8765",
        ws: true,
      },
    },
  },
});
