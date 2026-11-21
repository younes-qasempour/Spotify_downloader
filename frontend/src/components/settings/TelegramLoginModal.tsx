import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { KeyRound, Loader2, Phone, Send, ShieldCheck, X } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/api/endpoints";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

interface TelegramLoginModalProps {
  open: boolean;
  defaultPhone?: string;
  onClose: () => void;
  onAuthorized: () => void;
}

export function TelegramLoginModal({
  open,
  defaultPhone = "",
  onClose,
  onAuthorized,
}: TelegramLoginModalProps) {
  const [step, setStep] = useState<"phone" | "verify">("phone");
  const [phone, setPhone] = useState(defaultPhone);
  const [phoneCodeHash, setPhoneCodeHash] = useState<string>("");
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [needsPassword, setNeedsPassword] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setStep("phone");
    setPhone(defaultPhone || "");
    setPhoneCodeHash("");
    setCode("");
    setPassword("");
    setNeedsPassword(false);
    setErrorMsg(null);
  }, [defaultPhone, open]);

  const handleSendCode = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!phone.trim() || submitting) return;
    setSubmitting(true);
    setErrorMsg(null);
    try {
      const res = await api.settings.telegramSendCode(phone.trim());
      if (res.success && res.phone_code_hash) {
        setPhoneCodeHash(res.phone_code_hash);
        setStep("verify");
        toast.info("Verification code sent to your Telegram app");
      } else {
        setErrorMsg(res.error || "Could not send Telegram verification code.");
      }
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "Failed to send code.");
    } finally {
      setSubmitting(false);
    }
  };

  const handleVerify = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!code.trim() || submitting) return;
    setSubmitting(true);
    setErrorMsg(null);
    try {
      const res = await api.settings.telegramVerify({
        code: code.trim(),
        phone: phone.trim(),
        phone_code_hash: phoneCodeHash || undefined,
        password: needsPassword && password ? password : password || undefined,
      });
      if (res.success) {
        toast.success("Telegram account connected");
        onAuthorized();
        onClose();
      } else if (res.needs_password) {
        setNeedsPassword(true);
        setErrorMsg(
          res.error ||
            "2-Step Verification is enabled on this account. Enter your Telegram cloud password."
        );
      } else {
        setErrorMsg(res.error || "Verification failed. Check code and retry.");
      }
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "Verification error.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <AnimatePresence>
      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={submitting ? undefined : onClose}
            className="fixed inset-0 bg-black/75 backdrop-blur-sm"
          />

          <motion.div
            initial={{ opacity: 0, scale: 0.96, y: 10 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.96, y: 10 }}
            className="relative z-10 w-full max-w-md rounded-2xl glass-panel p-6 shadow-2xl space-y-4"
          >
            <div className="flex items-start justify-between gap-3">
              <div className="flex items-center gap-2.5">
                <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-sky-500/15 text-sky-300 border border-sky-500/30">
                  <Send className="h-4 w-4" />
                </div>
                <div>
                  <h2 className="text-base font-semibold text-white">
                    Connect Telegram (MeloBot)
                  </h2>
                  <p className="text-xs text-zinc-400">
                    {step === "phone"
                      ? "Step 1 of 2 — Send login code to Telegram"
                      : needsPassword
                        ? "2FA Cloud Password Required"
                        : "Step 2 of 2 — Enter 5-digit verification code"}
                  </p>
                </div>
              </div>
              <button
                type="button"
                disabled={submitting}
                onClick={onClose}
                className="rounded-lg p-1.5 text-zinc-400 hover:bg-white/10 hover:text-white disabled:opacity-40 cursor-pointer"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            {errorMsg && (
              <div className="rounded-xl border border-amber-500/35 bg-amber-500/10 p-3 text-xs text-amber-200">
                {errorMsg}
              </div>
            )}

            {step === "phone" ? (
              <form onSubmit={handleSendCode} className="space-y-4">
                <div className="space-y-1.5">
                  <label className="text-xs font-medium text-zinc-300 flex items-center gap-1.5">
                    <Phone className="h-3.5 w-3.5 text-zinc-400" />
                    Telegram Phone Number (International Format)
                  </label>
                  <Input
                    value={phone}
                    onChange={(e) => setPhone(e.target.value)}
                    placeholder="+15551234567"
                    required
                    autoFocus
                  />
                  <p className="text-[11px] text-zinc-500">
                    Include country code, e.g. `+98912...` or `+1...`.
                  </p>
                </div>

                <div className="flex items-center justify-end gap-2 pt-2 border-t border-white/[0.06]">
                  <Button
                    type="button"
                    variant="ghost"
                    disabled={submitting}
                    onClick={onClose}
                  >
                    Cancel
                  </Button>
                  <Button type="submit" disabled={submitting || !phone.trim()}>
                    {submitting && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                    Send Verification Code
                  </Button>
                </div>
              </form>
            ) : (
              <form onSubmit={handleVerify} className="space-y-4">
                <div className="space-y-1.5">
                  <label className="text-xs font-medium text-zinc-300 flex items-center gap-1.5">
                    <KeyRound className="h-3.5 w-3.5 text-zinc-400" />
                    5-Digit Telegram Code
                  </label>
                  <Input
                    value={code}
                    onChange={(e) => setCode(e.target.value)}
                    placeholder="12345"
                    required
                    autoFocus
                    className="font-mono tracking-widest"
                  />
                </div>

                {needsPassword && (
                  <div className="space-y-1.5">
                    <label className="text-xs font-medium text-zinc-300 flex items-center gap-1.5">
                      <ShieldCheck className="h-3.5 w-3.5 text-amber-300" />
                      Telegram 2FA Cloud Password
                    </label>
                    <Input
                      type="password"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      placeholder="Enter your 2-step verification password"
                      required
                    />
                  </div>
                )}

                <div className="flex items-center justify-between gap-2 pt-2 border-t border-white/[0.06]">
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    disabled={submitting}
                    onClick={() => {
                      setStep("phone");
                      setErrorMsg(null);
                    }}
                  >
                    Change Number
                  </Button>
                  <Button type="submit" disabled={submitting || !code.trim()}>
                    {submitting && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                    Verify & Connect
                  </Button>
                </div>
              </form>
            )}
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  );
}
