export interface HealthResponse {
  status: string;
  version: string;
  api_version: string;
  queue_paused: boolean;
  queue_count: number;
  ws_clients: number;
  pending_prompts: number;
  web_ui_enabled?: boolean;
}

export interface TrackMetadata {
  id: string;
  title: string;
  artists: string[];
  artist_str: string;
  primary_artist: string;
  album: string;
  release_date: string;
  duration_ms: number;
  duration_sec: number;
  track_number: number;
  disc_number: number;
  isrc: string;
  cover_url: string;
  collection_type: string;
  collection_name: string;
  collection_cover_url: string;
  genres: string[];
  genre_str: string;
  preferred_engine: string;
}

export interface QueueItem {
  track: TrackMetadata;
  status: string;
  source_type: string;
  quality_badge: string;
  progress_percent: number;
  speed_str: string;
  eta_str: string;
  error_message: string;
  output_path: string;
  cancelled: boolean;
  preferred_engine: string;
}

export interface QueueStats {
  total: number;
  active: number;
  queued: number;
  completed: number;
  failed: number;
  overall_progress_percent: number;
}

export interface MusilonPrompt {
  prompt_id: string;
  track: TrackMetadata;
  reason: string;
  category: "quota" | "vip" | "error";
  title: string;
  description: string;
  action_prompt: string;
}

export interface QueueResponse {
  items: QueueItem[];
  stats: QueueStats;
  paused: boolean;
  running: boolean;
  pending_prompts: MusilonPrompt[];
}

export interface SavedPlaylist {
  id: string;
  name: string;
  spotify_url: string;
  cover_url: string;
  local_cover: string;
  total_tracks: number;
  downloaded_count: number;
  pending_count: number;
  progress_percent: number;
  auto_sync: boolean;
  last_synced_at: string;
  created_at: string;
  updated_at: string;
}

export interface PlaylistTrackRow {
  spotify_id: string;
  playlist_id?: string;
  position?: number;
  title: string;
  artist: string;
  artists: string[];
  album: string;
  duration_ms: number;
  track_number: number;
  disc_number: number;
  isrc: string;
  cover_url: string;
  file_path: string;
  quality_badge: string;
  source_type: string;
  genre: string;
  genres: string[];
  status: "pending" | "queued" | "downloaded" | string;
  status_pill: "Completed" | "Queued" | "Pending" | string;
  file_exists: boolean;
}

export interface PlaylistDetailResponse {
  playlist: SavedPlaylist;
  tracks: PlaylistTrackRow[];
  available_genres: string[];
}

export interface SavePlaylistResponse {
  playlist: SavedPlaylist;
  was_truncated: boolean;
  is_guest: boolean;
  api_error: string;
  owner_name: string;
  auth_user: string;
}

export interface SyncPlaylistResponse {
  playlist: SavedPlaylist;
  added: number;
  removed: number;
  total: number;
  queued_count: number;
  liked_songs_tip: boolean;
}

export interface SyncAllPlaylistsResponse {
  checked_count: number;
  total_added: number;
  total_removed: number;
  errors: string[];
}

export interface AutoSyncSchedule {
  on_startup: boolean;
  interval_hours: number;
  auto_download_synced_tracks: boolean;
}

export interface PlaylistsListResponse {
  playlists: SavedPlaylist[];
  summary: {
    total_playlists: number;
    total_tracks: number;
    downloaded_count: number;
    pending_count: number;
  };
  auto_sync_schedule: AutoSyncSchedule;
  spotify_status: {
    mode: "connected" | "keys_only" | "guest";
    has_credentials: boolean;
    has_user_auth: boolean;
    user_name: string;
  };
}

export interface ExportSongsResponse {
  total: number;
  exported: number;
  skipped: number;
  failed: number;
  export_dir: string;
  m3u8_path: string | null;
  errors: string[];
  cancelled: boolean;
}

export interface ExportM3u8Response {
  success: boolean;
  m3u8_path: string;
  path_mode: string;
}

export interface LyricLine {
  timestamp_ms: number;
  text: string;
  translated?: string;
}

export interface TrackLyricsResponse {
  track_id: string;
  has_lyrics: boolean;
  is_synced: boolean;
  source: "lrc_file" | "embedded" | "lrclib" | "none" | string;
  raw_text: string;
  lines: LyricLine[];
  translation_lang: "none" | "en" | "fa" | string;
}

export interface FetchLyricsResponse {
  found: boolean;
  has_lyrics: boolean;
  is_synced: boolean;
  source: string;
  raw_text: string;
  lines: LyricLine[];
  lrc_saved?: boolean;
  message?: string;
}

export interface EqualizerPreset {
  preamp: number;
  bass_boost: number;
  bands: number[];
}

export interface EqualizerConfig {
  enabled: boolean;
  preset: string;
  preamp: number;
  bass_boost: number;
  bands: number[];
}

export interface EqualizerResponse {
  frequencies: number[];
  presets: Record<string, EqualizerPreset>;
  config: EqualizerConfig;
}

export interface LibraryStats {
  total_tracks: number;
  total_playlists: number;
  total_albums: number;
  total_bytes: number;
  size_str: string;
  available_genres: string[];
}

export interface LibraryTrack {
  id: number;
  spotify_id: string;
  title: string;
  artist: string;
  artists: string[];
  album: string;
  genre: string;
  genres: string[];
  duration_ms: number;
  track_number: number;
  disc_number: number;
  isrc?: string;
  file_path: string;
  file_size: number;
  quality_badge: string;
  source_type: string;
  collection_name: string;
  collection_type: string;
  downloaded_at: string;
  file_exists: boolean;
  audio_url: string;
  cover_url_local: string;
}

export interface LibraryCollection {
  name: string;
  artist?: string;
  collection_type?: string;
  track_count: number;
  total_size_bytes: number;
  size_str: string;
  folder_path: string;
  cover_path?: string;
  latest_download: string;
  genre: string;
  genres: string[];
  cover_url_local: string;
}

export interface LibraryTracksResponse {
  tracks: LibraryTrack[];
  total: number;
  stats: LibraryStats;
  available_genres: string[];
}

export interface LibraryPlaylistsResponse {
  playlists: LibraryCollection[];
  total: number;
}

export interface LibraryAlbumsResponse {
  albums: LibraryCollection[];
  total: number;
}

export interface LibraryCollectionTracksResponse {
  name: string;
  collection_type: "playlist" | "album";
  tracks: LibraryTrack[];
  total: number;
}

export interface SpectrumInspectResponse {
  file_path: string;
  codec: string;
  sample_rate: number;
  channels: number;
  bits_per_sample: number;
  container_bitrate_kbps: number;
  estimated_true_kbps: number;
  duration_sec: number;
  cutoff_khz: number;
  verdict: "authentic" | "good" | "upscaled" | string;
  verdict_title: string;
  band_db: Record<string, number>;
  spectrogram_path: string | null;
  spectrogram_url: string | null;
  track_id?: string;
  title?: string;
  artist?: string;
}

export interface SettingsResponse {
  config: {
    version: number;
    source_engine: "musilon" | "melobot";
    musilon: {
      session_cookie: string;
      username: string;
      password: string;
      enabled: boolean;
      safe_mode: boolean;
      cooldown_min_sec: number;
      cooldown_max_sec: number;
      stream_concurrency: number;
    };
    telegram: {
      enabled: boolean;
      bot_username: string;
      phone: string;
      preferred_quality: string;
      safe_delay_sec: number;
    };
    spotify: {
      client_id: string;
      client_secret: string;
    };
    download: {
      output_dir: string;
      cache_dir: string;
      naming_template: string;
      album_naming_template: string;
      save_in_subfolders: boolean;
      save_lrc: boolean;
      lyrics_mode: "embedded_only" | "separate_folder" | "same_folder";
      embed_lyrics: boolean;
      embed_cover_art: boolean;
      allow_fallback: boolean;
      preferred_quality: string;
      quality_priority: string[];
      concurrency: number;
      cookies_file: string;
      proxy: string;
      generate_m3u8: boolean;
      replaygain_tagging: boolean;
      normalize_volume: boolean;
      target_lufs: number;
      target_format: string;
    };
    ui: {
      theme: string;
      clipboard_auto_detect: boolean;
      player_volume: number;
      eq_enabled: boolean;
      eq_preset: string;
      eq_preamp: number;
      eq_bass_boost: number;
      eq_bands: number[];
      lyrics_translation_lang: string;
    };
    playlists: {
      auto_sync_on_startup: boolean;
      auto_sync_interval_hours: number;
      auto_download_synced_tracks: boolean;
    };
    mobile: {
      lan_enabled: boolean;
      device_name: string;
    };
  };
  secrets_set: {
    musilon_session_cookie: boolean;
    musilon_password: boolean;
    spotify_client_secret: boolean;
    telegram_api_hash: boolean;
    mobile_pair_token: boolean;
  };
  derived: {
    effective_source_engine: "musilon" | "melobot";
    concurrency_locked: boolean;
    effective_concurrency: number;
    musilon_configured: boolean;
    musilon_badge_state: string;
  };
}

export interface ToolProgressEvent {
  tool: string;
  current: number;
  total: number;
  percent: number;
  message: string;
}

export interface WsEventEnvelope {
  type: string;
  payload: Record<string, unknown>;
  timestamp: number;
}

export interface PlayerTrack {
  id: string;
  title: string;
  artist: string;
  album?: string;
  durationSec: number;
  audioUrl: string;
  coverUrl?: string;
  qualityBadge?: string;
  sourceType?: string;
}

export interface SpectrumScanItem {
  file_path: string;
  codec: string;
  sample_rate: number;
  channels: number;
  bits_per_sample: number;
  container_bitrate_kbps: number;
  estimated_true_kbps: number;
  duration_sec: number;
  cutoff_khz: number;
  verdict: "authentic" | "good" | "upscaled" | string;
  verdict_title: string;
  band_db: Record<string, number>;
  title: string;
  artist: string;
  spotify_id: string;
}

export interface SpectrumScanResponse {
  results: SpectrumScanItem[];
  summary: {
    total: number;
    upscaled: number;
    good: number;
    authentic: number;
  };
}

export interface DuplicateFileEntry {
  file_path: string;
  title: string;
  artist: string;
  album: string;
  isrc: string;
  duration_ms: number;
  quality_badge: string;
  spotify_ids: string[];
  size_bytes: number;
  is_hardlinked?: boolean;
}

export interface DuplicateGroup {
  key: string;
  title: string;
  artist: string;
  match_reason: string;
  master: DuplicateFileEntry;
  duplicates: DuplicateFileEntry[];
  reclaimable_bytes: number;
}

export interface DuplicateScanResponse {
  groups: DuplicateGroup[];
  summary: {
    total_groups: number;
    redundant_files: number;
    reclaimable_bytes: number;
  };
}

export interface DuplicateMergeResponse {
  mode: "hardlink" | "merge";
  groups_processed: number;
  files_merged: number;
  hardlinked: number;
  reclaimed_bytes: number;
  errors: number;
}

export interface NormalizeLibraryResponse {
  cancelled: boolean;
  scanned: number;
  boosted: number;
  attenuated: number;
  already_balanced: number;
  errors: number;
}

export interface ReplayGainLibraryResponse {
  scanned: number;
  calculated: number;
  errors: number;
}

export interface CleanLibraryResponse {
  purged_corrupt_files: number;
  purged_db_records: number;
  removed_marker_files: number;
  relocated_covers: number;
  reorganized_lyrics: number;
}

export interface OrganizeLibraryResponse {
  target_dir: string;
  files_moved: number;
  duplicate_files_removed: number;
  duplicate_db_rows_removed: number;
  missing_db_rows_removed: number;
  paths_normalized: number;
  metadata_enriched: number;
  saved_tracks_repaired: number;
  saved_tracks_reset: number;
  empty_dirs_removed: number;
  errors: number;
}

export interface RepairLibraryResponse {
  scanned: number;
  missing_covers_found: number;
  missing_lyrics_found: number;
  healed_covers: number;
  healed_lyrics: number;
  errors: number;
}

export interface RetagGenresResponse {
  scanned: number;
  missing_genres_found: number;
  retagged: number;
  already_tagged: number;
  errors: number;
}

export interface MusilonLoginResponse {
  success: boolean;
  message: string;
  badge_state: "vip" | "active" | "guest" | "offline" | string;
  connected: boolean;
  is_authenticated: boolean;
  is_vip: boolean;
  session_cookie_saved: boolean;
}

export interface MusilonTestResponse {
  connected: boolean;
  is_authenticated: boolean;
  is_vip: boolean;
  message: string;
  badge_state: "vip" | "active" | "guest" | "offline" | string;
}

export interface TelegramStatusResponse {
  authorized: boolean;
  user: {
    id?: number;
    first_name?: string;
    last_name?: string;
    username?: string;
    phone?: string;
  } | null;
  display: string;
}

export interface TelegramSendCodeResponse {
  success: boolean;
  phone_code_hash: string | null;
  error: string | null;
}

export interface TelegramVerifyResponse {
  success: boolean;
  needs_password: boolean;
  user: Record<string, unknown> | null;
  error: string | null;
}

export interface SpotifyStatusResponse {
  has_keys: boolean;
  has_user_auth: boolean;
  user_name: string;
  mode: "authorized" | "keys_only" | "guest" | string;
  redirect_uri: string;
}

export interface SpotifyValidateResponse {
  valid: boolean;
  sample_title: string;
  has_user_auth: boolean;
  message: string;
  error?: string;
}

export interface FfmpegStatusResponse {
  installed: boolean;
  path: string;
}

export interface FfmpegInstallResponse {
  success: boolean;
  path: string;
  message: string;
}

export interface MobileSyncInfo {
  lan_enabled: boolean;
  bind_host?: string;
  restart_required?: boolean;
  device_name: string;
  port: number;
  server_version: string;
  ips: string[];
  urls: string[];
  primary_url: string;
  library_stats: LibraryStats;
  saved_playlists_count: number;
  paired: boolean;
  pair_token?: string;
  pair_uri?: string;
  qr_svg_url?: string;
}

export interface UsbDeviceInfo {
  serial: string;
  state: string;
  model: string;
  product: string;
  device: string;
  transport_id: string;
  is_emulator: boolean;
  reverse_active: boolean;
}

export interface UsbSyncStatus {
  adb_available: boolean;
  adb_path: string;
  port: number;
  usb_url: string;
  devices: UsbDeviceInfo[];
  ready_count: number;
  unauthorized_count: number;
  active_count: number;
  reverse_active: boolean;
  error: string;
}

export interface UsbReverseActionResponse extends UsbSyncStatus {
  success: boolean;
  enabled_serials?: string[];
  disabled_serials?: string[];
  errors: string[];
}

export interface InstallAdbResponse {
  success: boolean;
  adb_path: string;
  message: string;
}
