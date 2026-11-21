import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Copy,
  Disc3,
  ExternalLink,
  KeyRound,
  Loader2,
  LogOut,
  ShieldCheck,
} from "lucide-react";
import { toast } from "sonner";
import { api } from "@/api/endpoints";
import type { SettingsResponse } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

interface SpotifySettingsSectionProps {
  settings: SettingsResponse;
}

export function SpotifySettingsSection({
  settings,
}: SpotifySettingsSectionProps) {
  const queryClient = useQueryClient();

  const [clientId, setClientId] = useState(settings.config.spotify.client_id || "");
  const [clientSecret, setClientSecret] = useState("");
  const [validating, setValidating] = useState(false);
  const [authorizing, setAuthorizing] = useState(false);
  const [disconnecting, setDisconnecting] = useState(false);
  const [validationBanner, setValidationBanner] = useState<{
    valid: boolean;
    message: string;
  } | null>(null);

  const [showManualOAuth, setShowManualOAuth] = useState(false);
  const [authUrl, setAuthUrl] = useState("");
  const [fetchingUrl, setFetchingUrl] = useState(false);
  const [callbackInput, setCallbackInput] = useState("");
  const [completingCallback, setCompletingCallback] = useState(false);

  const { data: spotifyStatus, refetch: refetchSpotifyStatus } = useQuery({
    queryKey: ["spotify-status"],
    queryFn: () => api.settings.spotifyStatus(true),
    staleTime: 30000,
  });

  useEffect(() => {
    setClientId(settings.config.spotify.client_id || "");
  }, [settings.config.spotify.client_id]);

  const handleValidate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (validating) return;
    setValidating(true);
    setValidationBanner(null);
    try {
      const payload: { client_id?: string; client_secret?: string } = {
        client_id: clientId.trim(),
      };
      if (clientSecret.trim()) {
        payload.client_secret = clientSecret.trim();
      }
      const res = await api.settings.spotifyValidate(payload);
      setValidationBanner({ valid: res.valid, message: res.message });
      setClientSecret("");
      void queryClient.invalidateQueries({ queryKey: ["settings"] });
      void refetchSpotifyStatus();
      void queryClient.invalidateQueries({ queryKey: ["playlists"] });
      if (res.valid) {
        toast.success("Spotify API keys verified");
      } else {
        toast.error("Spotify validation failed", { description: res.message });
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Validation failed";
      setValidationBanner({ valid: false, message: msg });
      toast.error("Validation error", { description: msg });
    } finally {
      setValidating(false);
    }
  };

  const handleDesktopAuthorize = async () => {
    if (authorizing) return;
    setAuthorizing(true);
    try {
      const res = await api.settings.authorizeSpotify();
      void refetchSpotifyStatus();
      void queryClient.invalidateQueries({ queryKey: ["playlists"] });
      if (res.success) {
        toast.success(res.message || "Spotify account authorized!");
      } else {
        toast.warning(res.message || "Spotify authorization did not complete");
      }
    } catch (err) {
      toast.error("Spotify authorization failed", {
        description: err instanceof Error ? err.message : undefined,
      });
    } finally {
      setAuthorizing(false);
    }
  };

  const handleGetAuthUrl = async () => {
    if (fetchingUrl) return;
    setFetchingUrl(true);
    try {
      const res = await api.settings.spotifyAuthUrl();
      setAuthUrl(res.auth_url);
    } catch (err) {
      toast.error("Could not generate auth URL", {
        description: err instanceof Error ? err.message : undefined,
      });
    } finally {
      setFetchingUrl(false);
    }
  };

  const handleCompleteManualAuth = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!callbackInput.trim() || completingCallback) return;
    setCompletingCallback(true);
    try {
      const res = await api.settings.spotifyAuthCallback(callbackInput.trim());
      if (res.success) {
        toast.success(
          res.user_name
            ? `Authorized as @${res.user_name}`
            : "Spotify authorized!"
        );
        setCallbackInput("");
        void refetchSpotifyStatus();
        void queryClient.invalidateQueries({ queryKey: ["playlists"] });
      } else {
        toast.error("Could not exchange authorization code");
      }
    } catch (err) {
      toast.error("Callback failed", {
        description: err instanceof Error ? err.message : undefined,
      });
    } finally {
      setCompletingCallback(false);
    }
  };

  const handleDisconnect = async () => {
    if (disconnecting) return;
    setDisconnecting(true);
    try {
      await api.settings.spotifyDisconnect();
      void refetchSpotifyStatus();
      void queryClient.invalidateQueries({ queryKey: ["playlists"] });
      toast.info("Spotify user authorization cleared");
    } catch (err) {
      toast.error("Disconnect failed", {
        description: err instanceof Error ? err.message : undefined,
      });
    } finally {
      setDisconnecting(false);
    }
  };

  const copyRedirectUri = () => {
    const uri = spotifyStatus?.redirect_uri || "http://127.0.0.1:9900/callback";
    void navigator.clipboard.writeText(uri);
    toast.success("Copied Redirect URI to clipboard");
  };

  const statusBadge =
    spotifyStatus?.mode === "authorized" ? (
      <Badge variant="emerald">
        Authorized {spotifyStatus.user_name ? `(@${spotifyStatus.user_name})` : ""}
      </Badge>
    ) : spotifyStatus?.mode === "keys_only" ? (
      <Badge variant="sky">API Keys Configured</Badge>
    ) : (
      <Badge variant="gold">Guest Mode (100-track playlist cap)</Badge>
    );

  return (
    <div className="space-y-5">
      <div className="glass-panel rounded-2xl p-6 space-y-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <Disc3 className="h-5 w-5 text-emerald-bright" />
            <div>
              <h2 className="text-base font-semibold text-white">
                Spotify Developer API & OAuth Access
              </h2>
              <p className="text-xs text-zinc-400">
                Unlocks unlimited 100+ track playlists, user-curated mixes, and
                fast metadata resolution.
              </p>
            </div>
          </div>
          {statusBadge}
        </div>

        <div className="rounded-xl border border-white/[0.07] bg-white/[0.02] p-3.5 flex flex-wrap items-center justify-between gap-2 text-xs">
          <div>
            <span className="text-zinc-400">Required Spotify App Redirect URI: </span>
            <code className="font-mono text-emerald-300">
              {spotifyStatus?.redirect_uri || "http://127.0.0.1:9900/callback"}
            </code>
          </div>
          <Button type="button" size="sm" variant="secondary" onClick={copyRedirectUri}>
            <Copy className="h-3.5 w-3.5" />
            Copy URI
          </Button>
        </div>

        <form onSubmit={handleValidate} className="space-y-3">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-zinc-300">
                Spotify Client ID
              </label>
              <Input
                value={clientId}
                onChange={(e) => setClientId(e.target.value)}
                placeholder="Paste Spotify App Client ID"
                className="font-mono text-xs"
              />
            </div>

            <div className="space-y-1.5">
              <label className="text-xs font-medium text-zinc-300">
                Spotify Client Secret{" "}
                {settings.secrets_set.spotify_client_secret && (
                  <span className="text-emerald-300/90 font-normal">
                    (Saved — leave blank to keep)
                  </span>
                )}
              </label>
              <Input
                type="password"
                value={clientSecret}
                onChange={(e) => setClientSecret(e.target.value)}
                placeholder={
                  settings.secrets_set.spotify_client_secret
                    ? "•••••••• (Saved)"
                    : "Paste Spotify App Client Secret"
                }
                className="font-mono text-xs"
              />
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2 pt-1">
            <Button type="submit" disabled={validating || !clientId.trim()}>
              {validating ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <KeyRound className="h-3.5 w-3.5" />
              )}
              Save & Validate Keys
            </Button>

            <Button
              type="button"
              variant="secondary"
              disabled={authorizing || !spotifyStatus?.has_keys}
              onClick={() => void handleDesktopAuthorize()}
            >
              {authorizing ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <ShieldCheck className="h-3.5 w-3.5" />
              )}
              Authorize Spotify Account
            </Button>

            {spotifyStatus?.has_user_auth && (
              <Button
                type="button"
                variant="destructive"
                disabled={disconnecting}
                onClick={() => void handleDisconnect()}
              >
                <LogOut className="h-3.5 w-3.5" />
                Disconnect Account
              </Button>
            )}
          </div>
        </form>

        {validationBanner && (
          <div
            className={`rounded-xl border p-3 text-xs flex items-center gap-2 ${
              validationBanner.valid
                ? "border-emerald-500/35 bg-emerald-500/10 text-emerald-200"
                : "border-red-500/35 bg-red-500/10 text-red-200"
            }`}
          >
            <CheckCircle2 className="h-4 w-4 shrink-0" />
            <span>{validationBanner.message}</span>
          </div>
        )}

        {/* Headless / Remote Web OAuth Fallback */}
        <div className="rounded-xl border border-white/[0.07] bg-white/[0.02]">
          <button
            type="button"
            onClick={() => setShowManualOAuth((v) => !v)}
            className="w-full flex items-center justify-between px-4 py-2.5 text-xs font-medium text-zinc-300 hover:text-white cursor-pointer"
          >
            <span>
              Manual Browser / Remote Web OAuth Fallback (if local loopback
              cannot open)
            </span>
            {showManualOAuth ? (
              <ChevronDown className="h-4 w-4" />
            ) : (
              <ChevronRight className="h-4 w-4" />
            )}
          </button>

          {showManualOAuth && (
            <div className="border-t border-white/[0.06] p-4 space-y-3 text-xs">
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  disabled={fetchingUrl || !spotifyStatus?.has_keys}
                  onClick={() => void handleGetAuthUrl()}
                >
                  {fetchingUrl && (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  )}
                  Generate Spotify Auth URL
                </Button>

                {authUrl && (
                  <a
                    href={authUrl}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1.5 text-emerald-300 hover:underline font-medium"
                  >
                    <ExternalLink className="h-3.5 w-3.5" />
                    Open Spotify Consent Page
                  </a>
                )}
              </div>

              <form onSubmit={handleCompleteManualAuth} className="space-y-2">
                <label className="text-[11px] text-zinc-400">
                  After approving, paste the full `http://127.0.0.1:9900/callback?code=...` URL (or just the `code`):
                </label>
                <div className="flex items-center gap-2">
                  <Input
                    value={callbackInput}
                    onChange={(e) => setCallbackInput(e.target.value)}
                    placeholder="http://127.0.0.1:9900/callback?code=..."
                    className="font-mono text-xs flex-1"
                  />
                  <Button
                    type="submit"
                    size="sm"
                    disabled={completingCallback || !callbackInput.trim()}
                  >
                    Complete Auth
                  </Button>
                </div>
              </form>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
