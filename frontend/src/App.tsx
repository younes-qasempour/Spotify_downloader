import { lazy } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "@/components/layout/AppShell";

const QueuePage = lazy(() =>
  import("@/pages/QueuePage").then((m) => ({ default: m.QueuePage }))
);
const PlaylistsPage = lazy(() =>
  import("@/pages/PlaylistsPage").then((m) => ({ default: m.PlaylistsPage }))
);
const PlaylistDetailPage = lazy(() =>
  import("@/pages/PlaylistDetailPage").then((m) => ({
    default: m.PlaylistDetailPage,
  }))
);
const LibraryPage = lazy(() =>
  import("@/pages/LibraryPage").then((m) => ({ default: m.LibraryPage }))
);
const ToolsPage = lazy(() =>
  import("@/pages/ToolsPage").then((m) => ({ default: m.ToolsPage }))
);
const SettingsPage = lazy(() =>
  import("@/pages/SettingsPage").then((m) => ({ default: m.SettingsPage }))
);

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 10_000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="/" element={<QueuePage />} />
            <Route path="/playlists" element={<PlaylistsPage />} />
            <Route
              path="/playlists/:playlistId"
              element={<PlaylistDetailPage />}
            />
            <Route path="/library" element={<LibraryPage />} />
            <Route path="/tools" element={<ToolsPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}

export default App;
