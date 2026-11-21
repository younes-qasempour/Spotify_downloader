import { useSearchParams } from "react-router-dom";
import {
  Activity,
  CopyCheck,
  FileAudio,
  FolderSync,
  Volume2,
  type LucideIcon,
} from "lucide-react";
import { DuplicateMergerPanel } from "@/components/tools/DuplicateMergerPanel";
import { ExportersPanel } from "@/components/tools/ExportersPanel";
import { LoudnessToolsPanel } from "@/components/tools/LoudnessToolsPanel";
import { MaintenanceToolsPanel } from "@/components/tools/MaintenanceToolsPanel";
import { SpectrumAuditPanel } from "@/components/tools/SpectrumAuditPanel";
import { cn } from "@/lib/utils";

export type ToolsTab =
  | "spectrum"
  | "duplicates"
  | "loudness"
  | "maintenance"
  | "exporters";

const TABS: Array<{ id: ToolsTab; label: string; icon: LucideIcon }> = [
  { id: "spectrum", label: "Spectrum Audit", icon: Activity },
  { id: "duplicates", label: "Duplicate Merger", icon: CopyCheck },
  { id: "loudness", label: "Volume & ReplayGain", icon: Volume2 },
  { id: "maintenance", label: "Repair & Genres", icon: FolderSync },
  { id: "exporters", label: "Exporters", icon: FileAudio },
];

function isValidTab(raw: string | null): raw is ToolsTab {
  return TABS.some((t) => t.id === raw);
}

export function ToolsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const rawTab = searchParams.get("tab");
  const activeTab: ToolsTab = isValidTab(rawTab) ? rawTab : "spectrum";

  const selectTab = (tab: ToolsTab) => {
    setSearchParams({ tab }, { replace: true });
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-2">
        {TABS.map((tab) => {
          const Icon = tab.icon;
          const active = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              type="button"
              onClick={() => selectTab(tab.id)}
              className={cn(
                "inline-flex items-center gap-2 rounded-full px-4 py-2 text-xs font-medium transition-all cursor-pointer border",
                active
                  ? "bg-emerald-500/20 text-emerald-300 border-emerald-500/45 shadow-sm shadow-emerald-500/10"
                  : "bg-white/[0.03] text-zinc-400 border-white/[0.07] hover:bg-white/[0.06] hover:text-zinc-200"
              )}
            >
              <Icon className="h-3.5 w-3.5" />
              {tab.label}
            </button>
          );
        })}
      </div>

      {activeTab === "spectrum" && <SpectrumAuditPanel />}
      {activeTab === "duplicates" && <DuplicateMergerPanel />}
      {activeTab === "loudness" && <LoudnessToolsPanel />}
      {activeTab === "maintenance" && <MaintenanceToolsPanel />}
      {activeTab === "exporters" && <ExportersPanel />}
    </div>
  );
}
