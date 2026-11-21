import { ClipboardPaste, FolderOpen, Link2, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";

export type PreferredEngine = "auto" | "musilon" | "melobot" | "youtube";

interface QueueIngestionBarProps {
  value: string;
  onChange: (val: string) => void;
  preferredEngine: PreferredEngine;
  onEngineChange: (engine: PreferredEngine) => void;
  autoStart: boolean;
  onAutoStartChange: (autoStart: boolean) => void;
  submitting: boolean;
  onSubmit: () => void;
  onPasteClipboard: () => void;
  onOpenFolder: () => void;
}

export function QueueIngestionBar({
  value,
  onChange,
  preferredEngine,
  onEngineChange,
  autoStart,
  onAutoStartChange,
  submitting,
  onSubmit,
  onPasteClipboard,
  onOpenFolder,
}: QueueIngestionBarProps) {
  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (value.trim() && !submitting) {
        onSubmit();
      }
    }
  };

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit();
      }}
      className="glass-panel rounded-2xl p-4 space-y-3"
    >
      <div className="flex flex-col lg:flex-row gap-3 items-stretch lg:items-start">
        <div className="relative flex-1">
          <Link2 className="pointer-events-none absolute left-3.5 top-3 h-4 w-4 text-zinc-400" />
          <textarea
            rows={1}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Paste Spotify Track / Album / Playlist, YouTube URL, multi-line links (Shift+Enter), or song search..."
            className="min-h-[42px] max-h-32 w-full resize-y rounded-xl border border-white/10 bg-white/[0.04] pl-10 pr-10 py-2.5 text-sm text-zinc-100 placeholder:text-zinc-500 transition-colors focus:border-emerald-500/60 focus:bg-white/[0.06] focus:outline-none"
          />
          <button
            type="button"
            onClick={onPasteClipboard}
            className="absolute right-2.5 top-2 rounded-lg p-1.5 text-zinc-400 hover:bg-white/10 hover:text-white transition-colors cursor-pointer"
            title="Paste from Clipboard"
          >
            <ClipboardPaste className="h-4 w-4" />
          </button>
        </div>

        <div className="flex flex-wrap items-center gap-2 shrink-0">
          <select
            value={preferredEngine}
            onChange={(e) => onEngineChange(e.target.value as PreferredEngine)}
            aria-label="Preferred download engine"
            className="h-[42px] rounded-xl border border-white/10 bg-elevated px-3 text-xs font-medium text-zinc-200 focus:border-emerald-500/60 focus:outline-none cursor-pointer"
          >
            <option value="auto">Engine: Auto Cascade</option>
            <option value="musilon">Engine: Musilon VIP</option>
            <option value="melobot">Engine: MeloBot TG</option>
            <option value="youtube">Engine: YouTube Music</option>
          </select>

          <Button
            type="submit"
            disabled={submitting || !value.trim()}
            className="h-[42px] px-5"
          >
            <Sparkles className="h-4 w-4" />
            {submitting
              ? "Resolving..."
              : autoStart
                ? "Add & Start"
                : "Analyze & Enqueue"}
          </Button>

          <Button
            type="button"
            variant="secondary"
            onClick={onOpenFolder}
            className="h-[42px]"
            title="Open local download directory"
          >
            <FolderOpen className="h-4 w-4" />
            <span className="hidden sm:inline">Open Folder</span>
          </Button>
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-zinc-400 pt-0.5">
        <span>
          Tip: Press <kbd className="rounded bg-white/10 px-1.5 py-0.5 font-mono text-[10px] text-zinc-200">Enter</kbd> to enqueue, <kbd className="rounded bg-white/10 px-1.5 py-0.5 font-mono text-[10px] text-zinc-200">Shift+Enter</kbd> for multiple URLs, or drag links into this window.
        </span>

        <label className="inline-flex items-center gap-2 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={autoStart}
            onChange={(e) => onAutoStartChange(e.target.checked)}
            className="h-3.5 w-3.5 rounded accent-emerald-500 cursor-pointer"
          />
          <span className="text-zinc-300">Auto-start downloads</span>
        </label>
      </div>
    </form>
  );
}
