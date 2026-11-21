import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Cookie,
  Loader2,
  LogOut,
  Radio,
  RefreshCw,
  Send,
  Shield,
  Sparkles,
} from "lucide-react";
import { toast } from "sonner";
import { api } from "@/api/endpoints";
import type { SettingsResponse } from "@/api/types";
import { TelegramLoginModal } from "@/components/settings/TelegramLoginModal";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

interface SourcesSettingsSectionProps {
  settings: SettingsResponse;
  onPatch: (values: Record<string, unknown>, toastMsg?: string) => Promise<void>;
  patching: boolean;
}

export function SourcesSettingsSection({
  settings,
  onPatch,
  patching,
}: SourcesSettingsSectionProps) {
  const queryClient = useQueryClient();
  const cfg = settings.config;
  const effEngine = settings.derived.effective_source_engine;

  const [musilonEmail, setMusilonEmail] = useState(cfg.musilon.username || "");
  const [musilonPassword, setMusilonPassword] = useState("");
  const [musilonCookie, setMusilonCookie] = useState("");
  const [showCookieBox, setShowCookieBox] = useState(false);

  const [minCooldown, setMinCooldown] = useState(
    String(cfg.musilon.cooldown_min_sec ?? 15)
  );
  const [maxCooldown, setMaxCooldown] = useState(
    String(cfg.musilon.cooldown_max_sec ?? 35)
  );
  const [tgDelay, setTgDelay] = useState(
    String(cfg.telegram.safe_delay_sec ?? 2.0)
  );

  const [badgeState, setBadgeState] = useState(
    settings.derived.musilon_badge_state || "guest"
  );
  const [musilonMsg, setMusilonMsg] = useState<string>("");
  const [loggingIn, setLoggingIn] = useState(false);
  const [testingMusilon, setTestingMusilon] = useState(false);
  const [tgModalOpen, setTgModalOpen] = useState(false);
  const [loggingOutTg, setLoggingOutTg] = useState(false);

  const {
    data: tgStatus,
    isFetching: fetchingTg,
    refetch: refetchTg,
  } = useQuery({
    queryKey: ["telegram-status"],
    queryFn: () => api.settings.telegramStatus(),
    staleTime: 30000,
  });

  useEffect(() => {
    setMusilonEmail(cfg.musilon.username || "");
    setMinCooldown(String(cfg.musilon.cooldown_min_sec ?? 15));
    setMaxCooldown(String(cfg.musilon.cooldown_max_sec ?? 35));
    setTgDelay(String(cfg.telegram.safe_delay_sec ?? 2.0));
  }, [
    cfg.musilon.cooldown_max_sec,
    cfg.musilon.cooldown_min_sec,
    cfg.musilon.username,
    cfg.telegram.safe_delay_sec,
  ]);

  useEffect(() => {
    setBadgeState(settings.derived.musilon_badge_state || "guest");
  }, [settings.derived.musilon_badge_state]);

  const handleMusilonLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    if (loggingIn) return;
    setLoggingIn(true);
    try {
      const payload: { username?: string; password?: string; run_test?: boolean } =
        {
          username: musilonEmail.trim(),
          run_test: true,
        };
      if (musilonPassword.trim()) {
        payload.password = musilonPassword.trim();
      }
      const res = await api.settings.musilonLogin(payload);
      setBadgeState(res.badge_state);
      setMusilonMsg(res.message);
      setMusilonPassword("");
      void queryClient.invalidateQueries({ queryKey: ["settings"] });
      if (res.success) {
        toast.success("Musilon account signed in", {
          description: res.is_vip
            ? "VIP Lossless FLAC unlocked"
            : res.message,
        });
      } else {
        toast.error("Musilon login failed", { description: res.message });
      }
    } catch (err) {
      const m = err instanceof Error ? err.message : "Login failed";
      setMusilonMsg(m);
      toast.error("Musilon login error", { description: m });
    } finally {
      setLoggingIn(false);
    }
  };

  const handleMusilonTest = async () => {
    if (testingMusilon) return;
    setTestingMusilon(true);
    try {
      const res = await api.settings.musilonTest();
      setBadgeState(res.badge_state);
      setMusilonMsg(res.message);
      if (res.is_vip) {
        toast.success("Musilon VIP Active", { description: res.message });
      } else if (res.connected) {
        toast.info("Musilon Connection Test", { description: res.message });
      } else {
        toast.error("Musilon Offline", { description: res.message });
      }
    } catch (err) {
      toast.error("Could not test Musilon connection", {
        description: err instanceof Error ? err.message : undefined,
      });
    } finally {
      setTestingMusilon(false);
    }
  };

  const handleTgLogout = async () => {
    if (loggingOutTg) return;
    setLoggingOutTg(true);
    try {
      await api.settings.telegramLogout();
      void refetchTg();
      toast.info("Telegram account disconnected");
    } catch (err) {
      toast.error("Could not disconnect Telegram", {
        description: err instanceof Error ? err.message : undefined,
      });
    } finally {
      setLoggingOutTg(false);
    }
  };

  const musilonBadgeVariant =
    badgeState === "vip"
      ? "gold"
      : badgeState === "active"
        ? "emerald"
        : badgeState === "offline"
          ? "danger"
          : "sky";

  return (
    <div className="space-y-5">
      {/* Primary Source Engine Selector */}
      <div className="glass-panel rounded-2xl p-5 space-y-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h2 className="text-base font-semibold text-white">
              Primary High-Quality Audio Source Engine
            </h2>
            <p className="text-xs text-zinc-400 mt-0.5">
              Choose which lossless/320k provider runs first before falling back
              to YouTube Music (if enabled).
            </p>
          </div>
          <Badge variant={effEngine === "melobot" ? "sky" : "emerald"}>
            Active: {effEngine === "melobot" ? "MeloBot Telegram" : "Musilon VIP"}
          </Badge>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <button
            type="button"
            disabled={patching}
            onClick={() =>
              void onPatch(
                { source_engine: "musilon" },
                "Primary source set to Musilon VIP CDN"
              )
            }
            className={cn(
              "rounded-2xl border p-4 text-left transition-all cursor-pointer",
              effEngine === "musilon"
                ? "border-emerald-500/50 bg-emerald-500/[0.09]"
                : "border-white/10 bg-white/[0.02] hover:bg-white/[0.05]"
            )}
          >
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2 font-semibold text-sm text-white">
                <Sparkles className="h-4 w-4 text-emerald-bright" />
                Musilon VIP CDN
              </div>
              {effEngine === "musilon" && (
                <CheckCircle2 className="h-4 w-4 text-emerald-bright" />
              )}
            </div>
            <p className="text-xs text-zinc-400 mt-1.5 leading-relaxed">
              Multi-worker high-speed MP3 320 kbps & 16/24-bit FLAC downloads
              with Anti-Ban Stealth Shield.
            </p>
          </button>

          <button
            type="button"
            disabled={patching}
            onClick={() =>
              void onPatch(
                { source_engine: "melobot" },
                "Primary source set to MeloBot Telegram (concurrency locked to 1)"
              )
            }
            className={cn(
              "rounded-2xl border p-4 text-left transition-all cursor-pointer",
              effEngine === "melobot"
                ? "border-sky-500/50 bg-sky-500/[0.09]"
                : "border-white/10 bg-white/[0.02] hover:bg-white/[0.05]"
            )}
          >
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2 font-semibold text-sm text-white">
                <Send className="h-4 w-4 text-sky-400" />
                MeloBot Telegram
              </div>
              {effEngine === "melobot" && (
                <CheckCircle2 className="h-4 w-4 text-sky-400" />
              )}
            </div>
            <p className="text-xs text-zinc-400 mt-1.5 leading-relaxed">
              Personal Telegram session fetcher. Automatically locks download
              concurrency to 1 worker to prevent FloodWait limits.
            </p>
          </button>
        </div>
      </div>

      {/* Musilon VIP Card */}
      <div className="glass-panel rounded-2xl p-6 space-y-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="text-base font-semibold text-white">
              Musilon Account & VIP Shield
            </h3>
            <p className="text-xs text-zinc-400 mt-0.5">
              Sign in with your Musilon email or supply a browser session cookie
              to unlock lossless FLAC streams.
            </p>
          </div>
          <Badge variant={musilonBadgeVariant} className="uppercase font-mono">
            Status: {badgeState}
          </Badge>
        </div>

        <form onSubmit={handleMusilonLogin} className="space-y-3">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-zinc-300">
                Musilon Registered Email
              </label>
              <Input
                type="email"
                value={musilonEmail}
                onChange={(e) => setMusilonEmail(e.target.value)}
                placeholder="name@gmail.com"
              />
            </div>

            <div className="space-y-1.5">
              <label className="text-xs font-medium text-zinc-300">
                Password{" "}
                {settings.secrets_set.musilon_password && (
                  <span className="text-emerald-300/90 font-normal">
                    (Saved — leave blank to keep)
                  </span>
                )}
              </label>
              <Input
                type="password"
                value={musilonPassword}
                onChange={(e) => setMusilonPassword(e.target.value)}
                placeholder={
                  settings.secrets_set.musilon_password
                    ? "•••••••• (Saved)"
                    : "Enter Musilon password"
                }
              />
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="submit"
              disabled={loggingIn || !musilonEmail.trim()}
            >
              {loggingIn && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              Log In & Verify Account
            </Button>
            <Button
              type="button"
              variant="secondary"
              disabled={testingMusilon}
              onClick={() => void handleMusilonTest()}
            >
              {testingMusilon ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Radio className="h-3.5 w-3.5" />
              )}
              Test Connection & VIP Status
            </Button>
          </div>
        </form>

        {musilonMsg && (
          <div className="rounded-xl border border-white/10 bg-white/[0.03] px-3.5 py-2.5 text-xs text-zinc-200">
            {musilonMsg}
          </div>
        )}

        {/* Collapsible Session Cookie */}
        <div className="rounded-xl border border-white/[0.07] bg-white/[0.02]">
          <button
            type="button"
            onClick={() => setShowCookieBox((v) => !v)}
            className="w-full flex items-center justify-between px-4 py-2.5 text-xs font-medium text-zinc-300 hover:text-white cursor-pointer"
          >
            <span className="flex items-center gap-2">
              <Cookie className="h-3.5 w-3.5 text-amber-300" />
              Advanced Session Cookie
              {settings.secrets_set.musilon_session_cookie && (
                <Badge variant="emerald" className="text-[10px]">
                  Cookie Saved
                </Badge>
              )}
            </span>
            {showCookieBox ? (
              <ChevronDown className="h-4 w-4" />
            ) : (
              <ChevronRight className="h-4 w-4" />
            )}
          </button>

          {showCookieBox && (
            <div className="border-t border-white/[0.06] p-4 space-y-3">
              <p className="text-[11px] text-zinc-400">
                Optional fallback if automated email login hits Turnstile/CAPTCHA:
                paste your `Cookie` header containing `next-auth` or `eyJ...`
                from DevTools Network tab.
              </p>
              <Input
                value={musilonCookie}
                onChange={(e) => setMusilonCookie(e.target.value)}
                placeholder={
                  settings.secrets_set.musilon_session_cookie
                    ? "Saved cookie hidden — paste new cookie string to replace"
                    : "Paste session cookie string..."
                }
                className="font-mono text-xs"
              />
              <div className="flex items-center gap-2">
                <Button
                  type="button"
                  size="sm"
                  disabled={patching || !musilonCookie.trim()}
                  onClick={async () => {
                    await onPatch(
                      { "musilon.session_cookie": musilonCookie.trim() },
                      "Musilon session cookie saved"
                    );
                    setMusilonCookie("");
                  }}
                >
                  Save Cookie
                </Button>
                {settings.secrets_set.musilon_session_cookie && (
                  <Button
                    type="button"
                    size="sm"
                    variant="destructive"
                    disabled={patching}
                    onClick={() =>
                      void onPatch(
                        { "musilon.session_cookie": "" },
                        "Saved session cookie cleared"
                      )
                    }
                  >
                    Clear Saved Cookie
                  </Button>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Toggles & Cooldown */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 pt-2 border-t border-white/[0.06]">
          <label className="flex items-center justify-between rounded-xl border border-white/[0.07] bg-white/[0.02] px-3.5 py-2.5 text-xs text-zinc-200 cursor-pointer">
            <span>Enable Musilon Engine</span>
            <input
              type="checkbox"
              checked={cfg.musilon.enabled}
              onChange={(e) =>
                void onPatch({ "musilon.enabled": e.target.checked })
              }
              className="h-4 w-4 accent-emerald-500"
            />
          </label>

          <label className="flex items-center justify-between rounded-xl border border-white/[0.07] bg-white/[0.02] px-3.5 py-2.5 text-xs text-zinc-200 cursor-pointer">
            <span className="flex items-center gap-1.5">
              <Shield className="h-3.5 w-3.5 text-emerald-bright" />
              VIP Anti-Ban Stealth Shield (Safe Mode)
            </span>
            <input
              type="checkbox"
              checked={cfg.musilon.safe_mode}
              onChange={(e) =>
                void onPatch({ "musilon.safe_mode": e.target.checked })
              }
              className="h-4 w-4 accent-emerald-500"
            />
          </label>
        </div>

        <div className="flex flex-wrap items-end gap-3">
          <div className="space-y-1">
            <label className="text-[11px] text-zinc-400">
              Min Cooldown (sec)
            </label>
            <Input
              type="number"
              min={0}
              max={300}
              value={minCooldown}
              onChange={(e) => setMinCooldown(e.target.value)}
              className="w-28 h-9 text-xs font-mono"
            />
          </div>
          <div className="space-y-1">
            <label className="text-[11px] text-zinc-400">
              Max Cooldown (sec)
            </label>
            <Input
              type="number"
              min={0}
              max={300}
              value={maxCooldown}
              onChange={(e) => setMaxCooldown(e.target.value)}
              className="w-28 h-9 text-xs font-mono"
            />
          </div>
          <Button
            type="button"
            size="sm"
            variant="secondary"
            disabled={patching}
            onClick={() =>
              void onPatch(
                {
                  "musilon.cooldown_min_sec": Number(minCooldown) || 0,
                  "musilon.cooldown_max_sec": Number(maxCooldown) || 0,
                },
                "Musilon cooldown delays saved"
              )
            }
          >
            Save Cooldown Delays
          </Button>
        </div>
      </div>

      {/* MeloBot Telegram Card */}
      <div className="glass-panel rounded-2xl p-6 space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="text-base font-semibold text-white">
              MeloBot Telegram Session
            </h3>
            <p className="text-xs text-zinc-400 mt-0.5">
              Connect your personal Telegram account via 2-step SMS/App OTP.
            </p>
          </div>
          <Badge variant={tgStatus?.authorized ? "emerald" : "default"}>
            {tgStatus?.display || "Checking..."}
          </Badge>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            variant={tgStatus?.authorized ? "secondary" : "default"}
            onClick={() => setTgModalOpen(true)}
          >
            <Send className="h-3.5 w-3.5" />
            {tgStatus?.authorized
              ? "Re-Connect Telegram"
              : "Connect Telegram Account"}
          </Button>

          <Button
            type="button"
            variant="secondary"
            disabled={fetchingTg}
            onClick={() => void refetchTg()}
          >
            <RefreshCw
              className={cn("h-3.5 w-3.5", fetchingTg && "animate-spin")}
            />
            Check Status
          </Button>

          {tgStatus?.authorized && (
            <Button
              type="button"
              variant="destructive"
              disabled={loggingOutTg}
              onClick={() => void handleTgLogout()}
            >
              <LogOut className="h-3.5 w-3.5" />
              {loggingOutTg ? "Logging Out..." : "Disconnect"}
            </Button>
          )}
        </div>

        <div className="flex flex-wrap items-end gap-3 pt-2 border-t border-white/[0.06]">
          <div className="space-y-1">
            <label className="text-[11px] text-zinc-400">
              Telegram Safe Delay Between Requests (sec)
            </label>
            <Input
              type="number"
              min={0}
              max={30}
              step={0.5}
              value={tgDelay}
              onChange={(e) => setTgDelay(e.target.value)}
              className="w-40 h-9 text-xs font-mono"
            />
          </div>
          <Button
            type="button"
            size="sm"
            variant="secondary"
            disabled={patching}
            onClick={() =>
              void onPatch(
                { "telegram.safe_delay_sec": Number(tgDelay) || 0 },
                "Telegram safe delay updated"
              )
            }
          >
            Save Delay
          </Button>
        </div>
      </div>

      <TelegramLoginModal
        open={tgModalOpen}
        defaultPhone={cfg.telegram.phone}
        onClose={() => setTgModalOpen(false)}
        onAuthorized={() => {
          void refetchTg();
          void queryClient.invalidateQueries({ queryKey: ["settings"] });
        }}
      />
    </div>
  );
}
