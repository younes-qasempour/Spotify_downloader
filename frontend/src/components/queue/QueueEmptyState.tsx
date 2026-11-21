import { ClipboardPaste, Command, Download, FolderOpen } from "lucide-react";
import { Button } from "@/components/ui/button";

interface QueueEmptyStateProps {
  onPasteFromClipboard: () => void;
  onOpenFolder: () => void;
  onOpenPalette: () => void;
}

const CAPABILITY_CHIPS = [
  "Lossless FLAC & 320k MP3",
  "YouTube Music Opus Fallback",
  "Embedded Synced Lyrics",
  "Multi-Format Transcoder",
];

export function QueueEmptyState({
  onPasteFromClipboard,
  onOpenFolder,
  onOpenPalette,
}: QueueEmptyStateProps) {
  return (
    <div className="glass-panel rounded-2xl border border-dashed border-white/[0.12] px-6 py-12 text-center space-y-5">
      <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-emerald-500/12 border border-emerald-500/25 text-emerald-300 shadow-[0_0_30px_-10px_rgba(29,185,84,0.6)]">
        <Download className="h-7 w-7" />
      </div>

      <div className="space-y-1.5">
        <h2 className="text-lg font-semibold text-white">
          Your Download Queue is Empty
        </h2>
        <p className="text-sm text-zinc-400 max-w-md mx-auto leading-relaxed">
          Paste a Spotify, YouTube, or song query above, or drag & drop any music
          link directly anywhere inside this window.
        </p>
      </div>

      <div className="flex flex-wrap items-center justify-center gap-2 max-w-xl mx-auto">
        {CAPABILITY_CHIPS.map((chip) => (
          <span
            key={chip}
            className="rounded-full bg-white/[0.04] border border-white/[0.09] px-3 py-1 text-[11px] font-medium text-zinc-300"
          >
            {chip}
          </span>
        ))}
      </div>

      <div className="flex flex-wrap items-center justify-center gap-2.5 pt-1">
        <Button type="button" variant="secondary" onClick={onPasteFromClipboard}>
          <ClipboardPaste className="h-4 w-4" />
          Paste from Clipboard
        </Button>

        <Button type="button" variant="outline" onClick={onOpenFolder}>
          <FolderOpen className="h-4 w-4" />
          Open Downloads Folder
        </Button>

        <Button type="button" variant="ghost" onClick={onOpenPalette}>
          <Command className="h-4 w-4" />
          Command Palette (Ctrl+K)
        </Button>
      </div>
    </div>
  );
}
