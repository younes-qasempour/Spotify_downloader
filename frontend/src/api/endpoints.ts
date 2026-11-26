import { apiFetch } from "@/api/client";
import type {
  AutoSyncSchedule,
  CleanLibraryResponse,
  DuplicateMergeResponse,
  DuplicateScanResponse,
  EqualizerConfig,
  EqualizerResponse,
  ExportM3u8Response,
  ExportSongsResponse,
  FetchLyricsResponse,
  FfmpegInstallResponse,
  FfmpegStatusResponse,
  HealthResponse,
  InstallAdbResponse,
  LibraryAlbumsResponse,
  LibraryCollectionTracksResponse,
  LibraryPlaylistsResponse,
  LibraryStats,
  LibraryTracksResponse,
  MobileSyncInfo,
  MusilonLoginResponse,
  MusilonPrompt,
  MusilonTestResponse,
  NormalizeLibraryResponse,
  OrganizeLibraryResponse,
  PlaylistDetailResponse,
  PlaylistsListResponse,
  QueueItem,
  QueueResponse,
  RepairLibraryResponse,
  ReplayGainLibraryResponse,
  RetagGenresResponse,
  SavePlaylistResponse,
  SavedPlaylist,
  SettingsResponse,
  SpectrumInspectResponse,
  SpectrumScanResponse,
  SpotifyStatusResponse,
  SpotifyValidateResponse,
  SyncAllPlaylistsResponse,
  SyncPlaylistResponse,
  TelegramSendCodeResponse,
  TelegramStatusResponse,
  TelegramVerifyResponse,
  TrackLyricsResponse,
  UsbReverseActionResponse,
  UsbSyncStatus,
} from "@/api/types";

export const api = {
  health: () => apiFetch<HealthResponse>("/api/health"),

  queue: {
    list: (query = "", status = "all") => {
      const params = new URLSearchParams();
      if (query) params.set("query", query);
      if (status && status !== "all") params.set("status", status);
      const qs = params.toString();
      return apiFetch<QueueResponse>(`/api/queue${qs ? `?${qs}` : ""}`);
    },
    enqueue: (payload: {
      input?: string;
      urls?: string[];
      auto_start?: boolean;
      preferred_engine?: string;
    }) =>
      apiFetch<{
        enqueued_count: number;
        items: QueueItem[];
        errors: string[];
        truncated_guest_limit: boolean;
        saved_playlists_updated: boolean;
        started: boolean;
      }>("/api/queue/enqueue", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    start: () =>
      apiFetch<{ started_count: number; paused: boolean; running: boolean }>(
        "/api/queue/start",
        {
          method: "POST",
        }
      ),
    pause: () =>
      apiFetch<{ paused: boolean; running: boolean }>("/api/queue/pause", {
        method: "POST",
      }),
    resume: () =>
      apiFetch<{ paused: boolean; running: boolean }>("/api/queue/resume", {
        method: "POST",
      }),
    stop: () =>
      apiFetch<{ stopped: boolean; paused: boolean; running: boolean }>(
        "/api/queue/stop",
        {
          method: "POST",
        }
      ),
    retryFailed: () =>
      apiFetch<{ retried_count: number }>("/api/queue/retry-failed", {
        method: "POST",
      }),
    clearCompleted: () =>
      apiFetch<{ cleared: boolean; remaining_count: number }>(
        "/api/queue/clear-completed",
        {
          method: "POST",
        }
      ),
    retryBatch: (trackIds: string[]) =>
      apiFetch<{ retried_ids: string[]; retried_count: number }>(
        "/api/queue/tracks/retry",
        {
          method: "POST",
          body: JSON.stringify({ track_ids: trackIds }),
        }
      ),
    cancelBatch: (trackIds: string[]) =>
      apiFetch<{ cancelled_ids: string[]; cancelled_count: number }>(
        "/api/queue/tracks/cancel",
        {
          method: "POST",
          body: JSON.stringify({ track_ids: trackIds }),
        }
      ),
    removeBatch: (trackIds: string[]) =>
      apiFetch<{ removed_ids: string[]; removed_count: number }>(
        "/api/queue/tracks/remove",
        {
          method: "POST",
          body: JSON.stringify({ track_ids: trackIds }),
        }
      ),
    retryTrack: (trackId: string) =>
      apiFetch<{ retried: boolean; track_id: string }>(
        `/api/queue/tracks/${encodeURIComponent(trackId)}/retry`,
        {
          method: "POST",
        }
      ),
    cancelTrack: (trackId: string) =>
      apiFetch<{ cancelled: boolean; track_id: string }>(
        `/api/queue/tracks/${encodeURIComponent(trackId)}/cancel`,
        {
          method: "POST",
        }
      ),
    removeTrack: (trackId: string) =>
      apiFetch<{ removed: boolean; track_id: string }>(
        `/api/queue/tracks/${encodeURIComponent(trackId)}`,
        {
          method: "DELETE",
        }
      ),
    prompts: () =>
      apiFetch<{ prompts: MusilonPrompt[] }>("/api/queue/prompts"),
    resolvePrompt: (promptId: string, action: "continue_youtube" | "stop") =>
      apiFetch<{ resolved: boolean; prompt_id: string; action: string }>(
        `/api/queue/prompts/${encodeURIComponent(promptId)}/resolve`,
        {
          method: "POST",
          body: JSON.stringify({ action }),
        }
      ),
  },

  playlists: {
    list: (search = "") => {
      const qs = search ? `?search=${encodeURIComponent(search)}` : "";
      return apiFetch<PlaylistsListResponse>(`/api/playlists${qs}`);
    },
    save: (url: string) =>
      apiFetch<SavePlaylistResponse>("/api/playlists", {
        method: "POST",
        body: JSON.stringify({ url }),
      }),
    syncAll: () =>
      apiFetch<SyncAllPlaylistsResponse>("/api/playlists/sync-all", {
        method: "POST",
      }),
    getAutoSyncSchedule: () =>
      apiFetch<AutoSyncSchedule>("/api/playlists/auto-sync/schedule"),
    updateAutoSyncSchedule: (payload: Partial<AutoSyncSchedule>) =>
      apiFetch<AutoSyncSchedule>("/api/playlists/auto-sync/schedule", {
        method: "PUT",
        body: JSON.stringify(payload),
      }),
    runAutoSync: () =>
      apiFetch<{
        already_running: boolean;
        checked_count: number;
        total_added: number;
        queued_count: number;
        errors: string[];
      }>("/api/playlists/auto-sync/run", {
        method: "POST",
      }),
    detail: (
      playlistId: string,
      params: {
        search?: string;
        status?: string;
        genre?: string;
        sort?: string;
        reconcile?: boolean;
      } = {}
    ) => {
      const qs = new URLSearchParams();
      if (params.search) qs.set("search", params.search);
      if (params.status && params.status !== "all") qs.set("status", params.status);
      if (params.genre && params.genre !== "all") qs.set("genre", params.genre);
      if (params.sort && params.sort !== "default") qs.set("sort", params.sort);
      if (params.reconcile !== undefined) {
        qs.set("reconcile", String(params.reconcile));
      }
      const query = qs.toString();
      return apiFetch<PlaylistDetailResponse>(
        `/api/playlists/${encodeURIComponent(playlistId)}${query ? `?${query}` : ""}`
      );
    },
    update: (
      playlistId: string,
      payload: {
        name?: string;
        spotify_url?: string;
        cover_url?: string;
        local_cover_path?: string;
      }
    ) =>
      apiFetch<{ updated: boolean; playlist: SavedPlaylist }>(
        `/api/playlists/${encodeURIComponent(playlistId)}`,
        {
          method: "PATCH",
          body: JSON.stringify(payload),
        }
      ),
    delete: (playlistId: string) =>
      apiFetch<{ deleted: boolean; playlist_id: string }>(
        `/api/playlists/${encodeURIComponent(playlistId)}`,
        {
          method: "DELETE",
        }
      ),
    toggleAutoSync: (playlistId: string, enabled: boolean) =>
      apiFetch<{ playlist: SavedPlaylist; auto_sync: boolean }>(
        `/api/playlists/${encodeURIComponent(playlistId)}/auto-sync`,
        {
          method: "PUT",
          body: JSON.stringify({ enabled }),
        }
      ),
    sync: (playlistId: string, autoDownload = true) =>
      apiFetch<SyncPlaylistResponse>(
        `/api/playlists/${encodeURIComponent(playlistId)}/sync`,
        {
          method: "POST",
          body: JSON.stringify({ auto_download: autoDownload }),
        }
      ),
    downloadBatch: (playlistId: string, batchSize: number) =>
      apiFetch<{
        queued_count: number;
        requested_batch_size: number;
        track_ids: string[];
        playlist: SavedPlaylist;
      }>(`/api/playlists/${encodeURIComponent(playlistId)}/download-batch`, {
        method: "POST",
        body: JSON.stringify({ batch_size: batchSize }),
      }),
    downloadSelected: (
      playlistId: string,
      payload: {
        track_ids: string[];
        preferred_engine?: "auto" | "melobot" | "musilon" | "youtube";
        redownload?: boolean;
      }
    ) =>
      apiFetch<{
        queued_count: number;
        track_ids: string[];
        playlist: SavedPlaylist;
      }>(`/api/playlists/${encodeURIComponent(playlistId)}/download-selected`, {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    resetQueued: (playlistId: string) =>
      apiFetch<{ reverted_count: number; playlist: SavedPlaylist }>(
        `/api/playlists/${encodeURIComponent(playlistId)}/reset-queued`,
        {
          method: "POST",
        }
      ),
    updateTrack: (
      playlistId: string,
      trackId: string,
      payload: { title?: string; artist?: string; album?: string }
    ) =>
      apiFetch<{ updated: boolean }>(
        `/api/playlists/${encodeURIComponent(playlistId)}/tracks/${encodeURIComponent(trackId)}`,
        {
          method: "PATCH",
          body: JSON.stringify(payload),
        }
      ),
    resetTrack: (playlistId: string, trackId: string) =>
      apiFetch<{ reset: boolean }>(
        `/api/playlists/${encodeURIComponent(playlistId)}/tracks/${encodeURIComponent(trackId)}/reset`,
        {
          method: "POST",
        }
      ),
    cancelTrack: (playlistId: string, trackId: string) =>
      apiFetch<{ cancelled: boolean }>(
        `/api/playlists/${encodeURIComponent(playlistId)}/tracks/${encodeURIComponent(trackId)}/cancel`,
        {
          method: "POST",
        }
      ),
    deleteTrackFile: (playlistId: string, trackId: string) =>
      apiFetch<{ deleted: boolean; file_removed: boolean; playlist: SavedPlaylist }>(
        `/api/playlists/${encodeURIComponent(playlistId)}/tracks/${encodeURIComponent(trackId)}/file`,
        {
          method: "DELETE",
        }
      ),
  },

  library: {
    stats: () => apiFetch<LibraryStats>("/api/library/stats"),
    tracks: (
      params: { search?: string; genre?: string; sort?: string } = {}
    ) => {
      const qs = new URLSearchParams();
      if (params.search) qs.set("search", params.search);
      if (params.genre && params.genre !== "all") qs.set("genre", params.genre);
      if (params.sort) qs.set("sort", params.sort);
      const q = qs.toString();
      return apiFetch<LibraryTracksResponse>(
        `/api/library/tracks${q ? `?${q}` : ""}`
      );
    },
    playlists: (
      params: { search?: string; genre?: string; sort?: string } = {}
    ) => {
      const qs = new URLSearchParams();
      if (params.search) qs.set("search", params.search);
      if (params.genre && params.genre !== "all") qs.set("genre", params.genre);
      if (params.sort) qs.set("sort", params.sort);
      const q = qs.toString();
      return apiFetch<LibraryPlaylistsResponse>(
        `/api/library/playlists${q ? `?${q}` : ""}`
      );
    },
    albums: (
      params: { search?: string; genre?: string; sort?: string } = {}
    ) => {
      const qs = new URLSearchParams();
      if (params.search) qs.set("search", params.search);
      if (params.genre && params.genre !== "all") qs.set("genre", params.genre);
      if (params.sort) qs.set("sort", params.sort);
      const q = qs.toString();
      return apiFetch<LibraryAlbumsResponse>(
        `/api/library/albums${q ? `?${q}` : ""}`
      );
    },
    collectionTracks: (params: {
      name: string;
      type: "playlist" | "album";
      search?: string;
      genre?: string;
      sort?: string;
    }) => {
      const qs = new URLSearchParams();
      qs.set("name", params.name);
      qs.set("type", params.type);
      if (params.search) qs.set("search", params.search);
      if (params.genre && params.genre !== "all") qs.set("genre", params.genre);
      if (params.sort) qs.set("sort", params.sort);
      return apiFetch<LibraryCollectionTracksResponse>(
        `/api/library/collections/tracks?${qs.toString()}`
      );
    },
    renameCollection: (payload: {
      old_name: string;
      new_name: string;
      collection_type?: "playlist" | "album";
    }) =>
      apiFetch<{
        renamed: boolean;
        old_name: string;
        new_name: string;
        collection_type: string;
      }>("/api/library/collections/rename", {
        method: "PATCH",
        body: JSON.stringify(payload),
      }),
    deleteTrack: (trackId: string, deleteFile = false) =>
      apiFetch<{
        deleted: boolean;
        track_id: string;
        file_removed: boolean;
      }>(
        `/api/library/tracks/${encodeURIComponent(trackId)}?delete_file=${deleteFile ? "true" : "false"}`,
        {
          method: "DELETE",
        }
      ),
    redownloadTrack: (
      trackId: string,
      preferredEngine: "auto" | "melobot" | "musilon" | "youtube" = "auto"
    ) =>
      apiFetch<{ queued: boolean; track_id: string; preferred_engine: string }>(
        `/api/library/tracks/${encodeURIComponent(trackId)}/redownload`,
        {
          method: "POST",
          body: JSON.stringify({ preferred_engine: preferredEngine }),
        }
      ),
    rescan: () =>
      apiFetch<{ indexed: number; directory: string; stats: LibraryStats }>(
        "/api/library/rescan",
        { method: "POST" }
      ),
  },

  settings: {
    get: () => apiFetch<SettingsResponse>("/api/settings"),
    patch: (values: Record<string, unknown>) =>
      apiFetch<SettingsResponse & { updated: string[] }>("/api/settings", {
        method: "PATCH",
        body: JSON.stringify({ values }),
      }),
    musilonLogin: (
      payload: { username?: string; password?: string; run_test?: boolean } = {}
    ) =>
      apiFetch<MusilonLoginResponse>("/api/settings/musilon/login", {
        method: "POST",
        body: JSON.stringify({ run_test: true, ...payload }),
      }),
    musilonTest: () =>
      apiFetch<MusilonTestResponse>("/api/settings/musilon/test", {
        method: "POST",
      }),
    telegramStatus: () =>
      apiFetch<TelegramStatusResponse>("/api/settings/telegram/status"),
    telegramSendCode: (phone: string) =>
      apiFetch<TelegramSendCodeResponse>("/api/settings/telegram/send-code", {
        method: "POST",
        body: JSON.stringify({ phone }),
      }),
    telegramVerify: (payload: {
      code: string;
      phone?: string;
      password?: string;
      phone_code_hash?: string;
    }) =>
      apiFetch<TelegramVerifyResponse>("/api/settings/telegram/verify", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    telegramLogout: () =>
      apiFetch<{ success: boolean; authorized: boolean }>(
        "/api/settings/telegram/logout",
        { method: "POST" }
      ),
    spotifyStatus: (fetchUser = true) =>
      apiFetch<SpotifyStatusResponse>(
        `/api/settings/spotify/status?fetch_user=${fetchUser ? "true" : "false"}`
      ),
    spotifyValidate: (
      payload: { client_id?: string; client_secret?: string } = {}
    ) =>
      apiFetch<SpotifyValidateResponse>("/api/settings/spotify/validate", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    authorizeSpotify: () =>
      apiFetch<{ success: boolean; user_name: string; message: string }>(
        "/api/settings/spotify/authorize",
        { method: "POST" }
      ),
    spotifyAuthUrl: () =>
      apiFetch<{ auth_url: string; redirect_uri: string }>(
        "/api/settings/spotify/auth-url"
      ),
    spotifyAuthCallback: (codeOrUrl: string) =>
      apiFetch<{ success: boolean; user_name: string }>(
        "/api/settings/spotify/auth-callback",
        {
          method: "POST",
          body: JSON.stringify({ code_or_url: codeOrUrl }),
        }
      ),
    spotifyDisconnect: () =>
      apiFetch<{ success: boolean; has_user_auth: boolean }>(
        "/api/settings/spotify/disconnect",
        { method: "POST" }
      ),
    ffmpegStatus: () =>
      apiFetch<FfmpegStatusResponse>("/api/settings/ffmpeg/status"),
    ffmpegInstall: () =>
      apiFetch<FfmpegInstallResponse>("/api/settings/ffmpeg/install", {
        method: "POST",
      }),
    openFolder: (path?: string, reveal = false) =>
      apiFetch<{ opened: boolean; path: string }>("/api/settings/open-folder", {
        method: "POST",
        body: JSON.stringify({ path: path ?? null, reveal }),
      }),
  },

  lyrics: {
    get: (trackId: string, lang?: string) => {
      const qs = lang && lang !== "none" ? `?lang=${encodeURIComponent(lang)}` : "";
      return apiFetch<TrackLyricsResponse>(
        `/api/lyrics/${encodeURIComponent(trackId)}${qs}`
      );
    },
    fetch: (trackId: string) =>
      apiFetch<FetchLyricsResponse>(
        `/api/lyrics/${encodeURIComponent(trackId)}/fetch`,
        { method: "POST" }
      ),
    translate: (
      lines: string[],
      targetLang: "none" | "en" | "fa",
      persistPreference = true
    ) =>
      apiFetch<{ target_lang: string; translated_lines: string[] }>(
        "/api/lyrics/translate",
        {
          method: "POST",
          body: JSON.stringify({
            lines,
            target_lang: targetLang,
            persist_preference: persistPreference,
          }),
        }
      ),
    exportLrc: (
      trackId: string,
      payload: {
        include_translation?: boolean;
        target_lang?: "en" | "fa";
        output_path?: string;
        write_to_disk?: boolean;
      } = {}
    ) =>
      apiFetch<{ saved_path: string | null; content: string }>(
        `/api/lyrics/${encodeURIComponent(trackId)}/export-lrc`,
        {
          method: "POST",
          body: JSON.stringify(payload),
        }
      ),
  },

  tools: {
    getEq: () => apiFetch<EqualizerResponse>("/api/tools/eq"),
    updateEq: (payload: Partial<EqualizerConfig>) =>
      apiFetch<EqualizerResponse>("/api/tools/eq", {
        method: "PUT",
        body: JSON.stringify(payload),
      }),
    bakeEq: (
      trackId: string,
      payload: {
        bands?: number[];
        preamp_db?: number;
        bass_boost_db?: number;
      } = {}
    ) =>
      apiFetch<{ success: boolean; track_id: string; file_path: string }>(
        `/api/tools/eq/bake/${encodeURIComponent(trackId)}`,
        {
          method: "POST",
          body: JSON.stringify(payload),
        }
      ),
    inspectSpectrum: (trackId: string, generateSpectrogram = true) =>
      apiFetch<SpectrumInspectResponse>(
        `/api/tools/spectrum/inspect/${encodeURIComponent(trackId)}?generate_spectrogram=${generateSpectrogram ? "true" : "false"}`,
        { method: "POST" }
      ),
    inspectSpectrumByPath: (payload: {
      track_id?: string;
      file_path?: string;
      generate_spectrogram?: boolean;
    }) =>
      apiFetch<SpectrumInspectResponse>("/api/tools/spectrum/inspect", {
        method: "POST",
        body: JSON.stringify({ generate_spectrogram: true, ...payload }),
      }),
    scanSpectrum: (payload: { root_dir?: string; max_workers?: number } = {}) =>
      apiFetch<SpectrumScanResponse>("/api/tools/spectrum/scan", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    upgradeSpectrum: (
      trackIds: string[],
      preferredEngine: "auto" | "melobot" | "musilon" | "youtube" = "auto"
    ) =>
      apiFetch<{
        queued_count: number;
        track_ids: string[];
        not_found: string[];
      }>("/api/tools/spectrum/upgrade", {
        method: "POST",
        body: JSON.stringify({
          track_ids: trackIds,
          preferred_engine: preferredEngine,
        }),
      }),
    upgradeSpectrumBySelection: (payload: {
      track_ids?: string[];
      file_paths?: string[];
      preferred_engine?: "auto" | "melobot" | "musilon" | "youtube";
    }) =>
      apiFetch<{
        queued_count: number;
        track_ids: string[];
        not_found: string[];
      }>("/api/tools/spectrum/upgrade", {
        method: "POST",
        body: JSON.stringify({
          track_ids: payload.track_ids ?? [],
          file_paths: payload.file_paths ?? [],
          preferred_engine: payload.preferred_engine ?? "auto",
        }),
      }),
    scanDuplicates: (
      payload: { use_acoustic_fingerprint?: boolean; root_dir?: string } = {}
    ) =>
      apiFetch<DuplicateScanResponse>("/api/tools/duplicates/scan", {
        method: "POST",
        body: JSON.stringify({ use_acoustic_fingerprint: true, ...payload }),
      }),
    mergeDuplicates: (payload: {
      mode: "hardlink" | "merge";
      group_keys?: string[];
    }) =>
      apiFetch<DuplicateMergeResponse>("/api/tools/duplicates/merge", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    normalizeTrack: (trackId: string, targetLufs?: number, force = true) =>
      apiFetch<{
        success: boolean;
        track_id: string;
        target_lufs: number;
        measured_lufs: number | null;
        gain_db: number | null;
      }>(`/api/tools/volume/normalize-track/${encodeURIComponent(trackId)}`, {
        method: "POST",
        body: JSON.stringify({ target_lufs: targetLufs ?? null, force }),
      }),
    normalizeLibrary: (
      payload: { target_lufs?: number; max_workers?: number; root_dir?: string } = {}
    ) =>
      apiFetch<NormalizeLibraryResponse>("/api/tools/volume/normalize-library", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    replaygainTrack: (trackId: string) =>
      apiFetch<{
        success: boolean;
        track_id: string;
        track_gain: string | null;
        track_peak: string | null;
      }>(`/api/tools/replaygain/track/${encodeURIComponent(trackId)}`, {
        method: "POST",
      }),
    replaygainLibrary: (payload: { root_dir?: string } = {}) =>
      apiFetch<ReplayGainLibraryResponse>("/api/tools/replaygain/library", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    cleanLibrary: (payload: { root_dir?: string } = {}) =>
      apiFetch<CleanLibraryResponse>("/api/tools/maintenance/clean", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    repairLibrary: (payload: { root_dir?: string } = {}) =>
      apiFetch<RepairLibraryResponse>("/api/tools/maintenance/repair", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    retagGenres: (payload: { root_dir?: string } = {}) =>
      apiFetch<RetagGenresResponse>("/api/tools/maintenance/retag-genres", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    organizeLibrary: (
      payload: { root_dir?: string; enforce_single_folder?: boolean } = {}
    ) =>
      apiFetch<OrganizeLibraryResponse>("/api/tools/maintenance/organize", {
        method: "POST",
        body: JSON.stringify({
          enforce_single_folder: true,
          ...payload,
        }),
      }),
    exportSongs: (payload: {
      destination_dir: string;
      playlist_name?: string;
      playlist_id?: string;
      collection_name?: string;
      collection_type?: "playlist" | "album";
      track_ids?: string[];
      create_playlist_subfolder?: boolean;
      target_format?: "original" | "mp3" | "flac" | "opus" | "alac";
      generate_m3u8?: boolean;
      skip_existing?: boolean;
    }) =>
      apiFetch<ExportSongsResponse>("/api/tools/export/songs", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    exportM3u8: (payload: {
      dest_path?: string;
      playlist_id?: string;
      collection_name?: string;
      collection_type?: "playlist" | "album";
      playlist_name?: string;
      track_ids?: string[];
      path_mode?: "filename" | "absolute" | "relative" | "android_prefix";
      android_prefix?: string;
    }) =>
      apiFetch<ExportM3u8Response>("/api/tools/export/m3u8", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    cancel: (toolName: string) =>
      apiFetch<{ tool: string; cancelled: boolean }>(
        `/api/tools/cancel/${encodeURIComponent(toolName)}`,
        {
          method: "POST",
        }
      ),
  },
  sync: {
    info: () => apiFetch<MobileSyncInfo>("/api/sync/info"),
    regenerateToken: () =>
      apiFetch<MobileSyncInfo>("/api/sync/token/regenerate", {
        method: "POST",
      }),
    usbStatus: () => apiFetch<UsbSyncStatus>("/api/sync/usb/status"),
    usbEnable: (serial?: string) =>
      apiFetch<UsbReverseActionResponse>("/api/sync/usb/enable", {
        method: "POST",
        body: JSON.stringify(serial ? { serial } : {}),
      }),
    usbDisable: (serial?: string) =>
      apiFetch<UsbReverseActionResponse>("/api/sync/usb/disable", {
        method: "POST",
        body: JSON.stringify(serial ? { serial } : {}),
      }),
    installAdb: () =>
      apiFetch<InstallAdbResponse>("/api/sync/usb/install-adb", {
        method: "POST",
      }),
  },
};
