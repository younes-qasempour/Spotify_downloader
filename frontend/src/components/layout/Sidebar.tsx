import { useQuery } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import {
  ChevronLeft,
  ChevronRight,
  Cpu,
  Disc3,
  Download,
  Library,
  ListMusic,
  Pin,
  Settings,
  Wrench,
  X,
} from "lucide-react";
import { NavLink, useNavigate } from "react-router-dom";
import { api } from "@/api/endpoints";
import { apiUrl } from "@/api/client";
import { useAppStore } from "@/stores/appStore";
import { cn } from "@/lib/utils";

interface NavItem {
  to: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  end?: boolean;
  badge?: number | string;
}

export function Sidebar() {
  const navigate = useNavigate();
  const collapsed = useAppStore((s) => s.sidebarCollapsed);
  const mobileOpen = useAppStore((s) => s.mobileNavOpen);
  const toggleSidebar = useAppStore((s) => s.toggleSidebar);
  const setMobileNavOpen = useAppStore((s) => s.setMobileNavOpen);
  const wsStatus = useAppStore((s) => s.wsStatus);
  const backendVersion = useAppStore((s) => s.backendVersion);
  const activeToolProgress = useAppStore((s) => s.activeToolProgress);

  const { data: queueData } = useQuery({
    queryKey: ["queue"],
    queryFn: () => api.queue.list(),
    refetchInterval: wsStatus === "connected" ? false : 15000,
  });

  const { data: playlistsData } = useQuery({
    queryKey: ["playlists"],
    queryFn: () => api.playlists.list(),
    staleTime: 30000,
  });

  const { data: libraryStats } = useQuery({
    queryKey: ["library", "stats"],
    queryFn: () => api.library.stats(),
    staleTime: 30000,
  });

  const { data: settingsData } = useQuery({
    queryKey: ["settings"],
    queryFn: () => api.settings.get(),
    staleTime: 60000,
  });

  const activeQueueCount =
    (queueData?.stats.active ?? 0) + (queueData?.stats.queued ?? 0);

  const navItems: NavItem[] = [
    {
      to: "/",
      label: "Queue",
      icon: Download,
      end: true,
      badge: activeQueueCount > 0 ? activeQueueCount : undefined,
    },
    {
      to: "/playlists",
      label: "Saved Playlists",
      icon: ListMusic,
      badge: playlistsData?.summary.total_playlists || undefined,
    },
    {
      to: "/library",
      label: "Library",
      icon: Library,
      badge: libraryStats?.total_tracks || undefined,
    },
    {
      to: "/tools",
      label: "Audio Tools",
      icon: Wrench,
    },
    {
      to: "/settings",
      label: "Settings",
      icon: Settings,
    },
  ];

  const allPlaylists = playlistsData?.playlists ?? [];
  const pinnedPlaylists = allPlaylists.filter((p) => p.auto_sync);
  const sidebarPlaylists = (
    pinnedPlaylists.length > 0 ? pinnedPlaylists : allPlaylists
  ).slice(0, 7);

  const engineLabel =
    settingsData?.derived.effective_source_engine === "melobot"
      ? "MeloBot TG"
      : "Musilon VIP";

  const renderSidebarContent = (isCompact: boolean, isMobile = false) => (
    <div className="flex h-full flex-col bg-panel/95 border-r border-white/[0.07] select-none">
      {/* Brand Header */}
      <div
        className={cn(
          "flex h-14 items-center border-b border-white/[0.06] px-3.5",
          isCompact ? "justify-center" : "justify-between"
        )}
      >
        <div className="flex items-center gap-2.5 min-w-0">
          <img
            src="/flacify-icon.png"
            alt="Flacify"
            className="h-7 w-7 shrink-0 rounded-lg object-cover shadow-md shadow-emerald-500/20"
            onError={(e) => {
              e.currentTarget.style.display = "none";
            }}
          />
          {!isCompact && (
            <div className="flex items-center gap-2 min-w-0">
              <span className="font-semibold tracking-tight text-white truncate">
                Flacify
              </span>
              <span className="rounded-md bg-emerald-500/15 px-1.5 py-0.5 text-[10px] font-mono font-medium text-emerald-300 border border-emerald-500/25">
                v{backendVersion || "2.0"}
              </span>
            </div>
          )}
        </div>

        {isMobile ? (
          <button
            type="button"
            onClick={() => setMobileNavOpen(false)}
            className="rounded-lg p-1.5 text-zinc-400 hover:bg-white/8 hover:text-white cursor-pointer"
            aria-label="Close navigation"
          >
            <X className="h-4 w-4" />
          </button>
        ) : (
          !isCompact && (
            <button
              type="button"
              onClick={toggleSidebar}
              className="rounded-lg p-1.5 text-zinc-400 hover:bg-white/8 hover:text-white transition-colors cursor-pointer"
              title="Collapse sidebar"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
          )
        )}
      </div>

      {isCompact && !isMobile && (
        <div className="flex justify-center py-2 border-b border-white/[0.05]">
          <button
            type="button"
            onClick={toggleSidebar}
            className="rounded-lg p-1.5 text-zinc-400 hover:bg-white/8 hover:text-white transition-colors cursor-pointer"
            title="Expand sidebar"
          >
            <ChevronRight className="h-4 w-4" />
          </button>
        </div>
      )}

      {/* Primary Navigation */}
      <nav className="px-2.5 pt-3 pb-2 space-y-1">
        {navItems.map((item) => {
          const Icon = item.icon;
          return (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              onClick={() => {
                if (isMobile) setMobileNavOpen(false);
              }}
              title={isCompact ? item.label : undefined}
              className={({ isActive }) =>
                cn(
                  "relative flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-colors",
                  isCompact && "justify-center px-2",
                  isActive
                    ? "text-white"
                    : "text-zinc-400 hover:text-zinc-100 hover:bg-white/[0.04]"
                )
              }
            >
              {({ isActive }) => (
                <>
                  {isActive && (
                    <motion.span
                      layoutId={
                        isMobile
                          ? "sidebar-active-pill-mobile"
                          : "sidebar-active-pill"
                      }
                      transition={{
                        type: "spring",
                        stiffness: 380,
                        damping: 32,
                      }}
                      className="absolute inset-0 rounded-xl bg-white/[0.08] border border-white/[0.08]"
                    />
                  )}
                  <Icon
                    className={cn(
                      "relative z-10 h-4 w-4 shrink-0 transition-colors",
                      isActive ? "text-emerald-bright" : "text-zinc-400"
                    )}
                  />
                  {!isCompact && (
                    <>
                      <span className="relative z-10 flex-1 truncate">
                        {item.label}
                      </span>
                      {item.badge !== undefined && (
                        <span
                          className={cn(
                            "relative z-10 rounded-full px-2 py-0.5 text-[11px] font-mono tabular-nums",
                            isActive
                              ? "bg-emerald-500/20 text-emerald-300"
                              : "bg-white/[0.06] text-zinc-400"
                          )}
                        >
                          {item.badge}
                        </span>
                      )}
                    </>
                  )}
                </>
              )}
            </NavLink>
          );
        })}
      </nav>

      {/* Pinned / Quick Playlists */}
      {!isCompact && (
        <div className="mt-2 flex-1 min-h-0 flex flex-col border-t border-white/[0.06] pt-3 px-2.5">
          <div className="flex items-center justify-between px-2 mb-2">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500">
              {pinnedPlaylists.length > 0 ? "Auto-Sync Pinned" : "Playlists"}
            </span>
            <span className="text-[10px] font-mono text-zinc-500 tabular-nums">
              {sidebarPlaylists.length}
            </span>
          </div>

          <div className="flex-1 overflow-y-auto space-y-1 pr-0.5 pb-4">
            {sidebarPlaylists.length === 0 ? (
              <div className="rounded-xl border border-dashed border-white/[0.07] px-3 py-4 text-center text-xs text-zinc-500">
                Save or pin a Spotify playlist to monitor new tracks.
              </div>
            ) : (
              sidebarPlaylists.map((pl) => (
                <button
                  key={pl.id}
                  type="button"
                  onClick={() => {
                    navigate(`/playlists/${pl.id}`);
                    if (isMobile) setMobileNavOpen(false);
                  }}
                  className="group flex w-full items-center gap-2.5 rounded-xl px-2 py-1.5 text-left hover:bg-white/[0.05] transition-colors cursor-pointer"
                >
                  <div className="relative h-8 w-8 shrink-0 overflow-hidden rounded-lg bg-elevated border border-white/[0.06]">
                    {pl.local_cover || pl.cover_url ? (
                      <img
                        src={
                          pl.local_cover
                            ? apiUrl(
                                `/api/media/cover/collection?name=${encodeURIComponent(pl.name)}`
                              )
                            : pl.cover_url
                        }
                        alt={pl.name}
                        className="h-full w-full object-cover"
                      />
                    ) : (
                      <div className="flex h-full w-full items-center justify-center text-zinc-500">
                        <Disc3 className="h-4 w-4" />
                      </div>
                    )}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1.5">
                      <span className="truncate text-xs font-medium text-zinc-200 group-hover:text-white">
                        {pl.name}
                      </span>
                      {pl.auto_sync && (
                        <Pin className="h-3 w-3 shrink-0 text-emerald-400" />
                      )}
                    </div>
                    <div className="text-[11px] text-zinc-500 font-mono tabular-nums">
                      {pl.downloaded_count}/{pl.total_tracks} tracks
                    </div>
                  </div>
                </button>
              ))
            )}
          </div>
        </div>
      )}

      {/* Spacer when collapsed */}
      {isCompact && <div className="flex-1" />}

      {/* Footer Status Strip */}
      <div className="border-t border-white/[0.06] p-3 space-y-2">
        {!isCompact && activeToolProgress && (
          <div className="rounded-lg bg-emerald-500/10 border border-emerald-500/20 px-2.5 py-1.5">
            <div className="flex items-center justify-between text-[10px] font-medium text-emerald-300">
              <span className="truncate">{activeToolProgress.tool}</span>
              <span className="font-mono tabular-nums">
                {Math.round(activeToolProgress.percent)}%
              </span>
            </div>
            <div className="mt-1 h-1 w-full overflow-hidden rounded-full bg-black/40">
              <div
                className="h-full rounded-full bg-emerald-bright transition-all duration-300"
                style={{
                  width: `${Math.max(4, Math.min(100, activeToolProgress.percent))}%`,
                }}
              />
            </div>
          </div>
        )}

        <div
          className={cn(
            "flex items-center gap-2 text-xs text-zinc-400",
            isCompact ? "justify-center" : "justify-between"
          )}
          title={`WebSocket: ${wsStatus} | Engine: ${engineLabel}`}
        >
          <div className="flex items-center gap-2 min-w-0">
            <span
              className={cn(
                "h-2 w-2 shrink-0 rounded-full",
                wsStatus === "connected"
                  ? "bg-emerald-bright shadow-[0_0_8px_rgba(30,215,96,0.85)]"
                  : wsStatus === "connecting"
                    ? "bg-amber-400 animate-pulse"
                    : "bg-red-400"
              )}
            />
            {!isCompact && (
              <span className="truncate text-[11px]">
                {wsStatus === "connected"
                  ? "Live"
                  : wsStatus === "connecting"
                    ? "Connecting"
                    : "Offline"}
              </span>
            )}
          </div>

          {!isCompact && (
            <span className="inline-flex items-center gap-1 rounded-md bg-white/[0.05] px-2 py-0.5 text-[10px] font-medium text-zinc-300 border border-white/[0.06]">
              <Cpu className="h-3 w-3 text-emerald-400" />
              {engineLabel}
            </span>
          )}
        </div>
      </div>
    </div>
  );

  return (
    <>
      {/* Desktop Collapsible Sidebar */}
      <aside
        className={cn(
          "hidden lg:block shrink-0 transition-[width] duration-200 ease-out h-full z-20",
          collapsed ? "w-[72px]" : "w-[248px]"
        )}
      >
        {renderSidebarContent(collapsed, false)}
      </aside>

      {/* Mobile Drawer */}
      <AnimatePresence>
        {mobileOpen && (
          <div className="fixed inset-0 z-50 lg:hidden flex">
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setMobileNavOpen(false)}
              className="fixed inset-0 bg-black/70 backdrop-blur-sm"
            />
            <motion.div
              initial={{ x: -260 }}
              animate={{ x: 0 }}
              exit={{ x: -260 }}
              transition={{ type: "spring", stiffness: 360, damping: 34 }}
              className="relative z-10 w-[260px] max-w-[82vw] h-full"
            >
              {renderSidebarContent(false, true)}
            </motion.div>
          </div>
        )}
      </AnimatePresence>
    </>
  );
}
