import { isTauriEnvironment } from "@/api/client";

export interface DialogFilter {
  name: string;
  extensions: string[];
}

export function isDesktopApp(): boolean {
  return isTauriEnvironment();
}

export async function pickDirectory(
  title = "Select Folder",
  defaultPath?: string
): Promise<string | null> {
  if (!isDesktopApp()) return null;
  const { open } = await import("@tauri-apps/plugin-dialog");
  const selected = await open({
    directory: true,
    multiple: false,
    title,
    defaultPath: defaultPath?.trim() || undefined,
  });
  return typeof selected === "string" ? selected : null;
}

export async function pickFile(
  title = "Select File",
  filters?: DialogFilter[],
  defaultPath?: string
): Promise<string | null> {
  if (!isDesktopApp()) return null;
  const { open } = await import("@tauri-apps/plugin-dialog");
  const selected = await open({
    directory: false,
    multiple: false,
    title,
    filters,
    defaultPath: defaultPath?.trim() || undefined,
  });
  return typeof selected === "string" ? selected : null;
}

export async function saveFile(
  title = "Save File",
  defaultPath?: string,
  filters?: DialogFilter[]
): Promise<string | null> {
  if (!isDesktopApp()) return null;
  const { save } = await import("@tauri-apps/plugin-dialog");
  const selected = await save({
    title,
    defaultPath: defaultPath?.trim() || undefined,
    filters,
  });
  return typeof selected === "string" ? selected : null;
}

export async function minimizeDesktopWindow(): Promise<void> {
  if (!isDesktopApp()) return;
  const { getCurrentWindow } = await import("@tauri-apps/api/window");
  await getCurrentWindow().minimize();
}

export async function toggleMaximizeDesktopWindow(): Promise<void> {
  if (!isDesktopApp()) return;
  const { getCurrentWindow } = await import("@tauri-apps/api/window");
  await getCurrentWindow().toggleMaximize();
}

export async function closeDesktopWindow(): Promise<void> {
  if (!isDesktopApp()) return;
  const { getCurrentWindow } = await import("@tauri-apps/api/window");
  await getCurrentWindow().close();
}

export async function hideDesktopToTray(): Promise<void> {
  if (!isDesktopApp()) return;
  const { getCurrentWindow } = await import("@tauri-apps/api/window");
  await getCurrentWindow().hide();
}

export async function isDesktopWindowMaximized(): Promise<boolean> {
  if (!isDesktopApp()) return false;
  const { getCurrentWindow } = await import("@tauri-apps/api/window");
  return getCurrentWindow().isMaximized();
}

export type DesktopResizeDirection =
  | "East"
  | "North"
  | "NorthEast"
  | "NorthWest"
  | "South"
  | "SouthEast"
  | "SouthWest"
  | "West";

export async function enterDesktopMiniPlayer(
  width: number,
  height: number,
  alwaysOnTop: boolean
): Promise<void> {
  if (!isDesktopApp()) return;
  const { invoke } = await import("@tauri-apps/api/core");
  await invoke("enter_mini_player", {
    width,
    height,
    alwaysOnTop,
  });
}

export async function exitDesktopMiniPlayer(): Promise<void> {
  if (!isDesktopApp()) return;
  const { invoke } = await import("@tauri-apps/api/core");
  await invoke("exit_mini_player");
}

export async function resizeDesktopMiniPlayer(
  width: number,
  height: number
): Promise<void> {
  if (!isDesktopApp()) return;
  const { invoke } = await import("@tauri-apps/api/core");
  await invoke("resize_mini_player", { width, height });
}

export async function setDesktopAlwaysOnTop(pinned: boolean): Promise<void> {
  if (!isDesktopApp()) return;
  const { invoke } = await import("@tauri-apps/api/core");
  await invoke("set_mini_always_on_top", { pinned });
}

export async function startDesktopResizeDragging(
  direction: DesktopResizeDirection
): Promise<void> {
  if (!isDesktopApp()) return;
  const { getCurrentWindow } = await import("@tauri-apps/api/window");
  await getCurrentWindow().startResizeDragging(direction);
}

export async function quitDesktopApp(): Promise<void> {
  if (!isDesktopApp()) return;
  const { invoke } = await import("@tauri-apps/api/core");
  await invoke("quit_app");
}

export async function listenDesktopMiniPlayerToggle(
  handler: () => void
): Promise<() => void> {
  if (!isDesktopApp()) return () => {};
  const { listen } = await import("@tauri-apps/api/event");
  return listen("flacify://toggle-mini-player", () => {
    handler();
  });
}

export async function listenDesktopMiniPlayerExit(
  handler: () => void
): Promise<() => void> {
  if (!isDesktopApp()) return () => {};
  const { listen } = await import("@tauri-apps/api/event");
  return listen("flacify://exit-mini-player", () => {
    handler();
  });
}

export async function listenDesktopCloseRequest(
  handler: () => void
): Promise<() => void> {
  if (!isDesktopApp()) return () => {};
  const { listen } = await import("@tauri-apps/api/event");
  return listen("flacify://request-close", () => {
    handler();
  });
}
