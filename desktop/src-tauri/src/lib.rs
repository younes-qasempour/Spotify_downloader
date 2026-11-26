mod backend_manager;

use backend_manager::BackendManager;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use tauri::menu::{Menu, MenuItem, PredefinedMenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{
    Emitter, LogicalSize, Manager, PhysicalPosition, PhysicalSize, Position, RunEvent, Size,
    WindowEvent,
};

#[derive(Clone, Copy)]
struct SavedMainWindow {
    width: u32,
    height: u32,
    x: i32,
    y: i32,
    maximized: bool,
}

#[derive(Default)]
struct MiniPlayerWindowState {
    saved: Mutex<Option<SavedMainWindow>>,
}

#[derive(Default)]
struct AppExitState {
    confirmed: AtomicBool,
}

fn clamp_window_to_work_area(window: &tauri::WebviewWindow, logical_w: f64, logical_h: f64) {
    let Ok(Some(monitor)) = window.current_monitor() else {
        return;
    };
    let work = monitor.work_area();
    let scale = window.scale_factor().unwrap_or(1.0);
    let win_w = (logical_w * scale).round() as i32;
    let win_h = (logical_h * scale).round() as i32;
    let pad = (16.0 * scale).round() as i32;

    let min_x = work.position.x + pad;
    let min_y = work.position.y + pad;
    let max_x = (work.position.x + work.size.width as i32 - win_w - pad).max(min_x);
    let max_y = (work.position.y + work.size.height as i32 - win_h - pad).max(min_y);

    let cur_pos = window
        .outer_position()
        .unwrap_or(PhysicalPosition::new(min_x, min_y));
    let clamped_x = cur_pos.x.clamp(min_x, max_x);
    let clamped_y = cur_pos.y.clamp(min_y, max_y);

    if clamped_x != cur_pos.x || clamped_y != cur_pos.y {
        let _ = window.set_position(Position::Physical(PhysicalPosition::new(
            clamped_x, clamped_y,
        )));
    }
}

#[tauri::command]
fn enter_mini_player(
    window: tauri::WebviewWindow,
    state: tauri::State<'_, MiniPlayerWindowState>,
    width: f64,
    height: f64,
    always_on_top: bool,
) -> Result<(), String> {
    if let Ok(mut guard) = state.saved.lock() {
        if guard.is_none() {
            let maximized = window.is_maximized().unwrap_or(false);
            let inner = window.inner_size().unwrap_or(PhysicalSize::new(1360, 860));
            let pos = window.outer_position().unwrap_or(PhysicalPosition::new(80, 60));
            *guard = Some(SavedMainWindow {
                width: inner.width,
                height: inner.height,
                x: pos.x,
                y: pos.y,
                maximized,
            });
        }
    }

    if window.is_maximized().unwrap_or(false) {
        window.unmaximize().map_err(|e| e.to_string())?;
    }

    window
        .set_min_size(Some(Size::Logical(LogicalSize::new(300.0, 152.0))))
        .map_err(|e| e.to_string())?;

    let clamped_w = width.clamp(300.0, 960.0);
    let clamped_h = height.clamp(152.0, 960.0);
    window
        .set_size(Size::Logical(LogicalSize::new(clamped_w, clamped_h)))
        .map_err(|e| e.to_string())?;

    clamp_window_to_work_area(&window, clamped_w, clamped_h);

    window
        .set_always_on_top(always_on_top)
        .map_err(|e| e.to_string())?;
    Ok(())
}

#[tauri::command]
fn exit_mini_player(
    window: tauri::WebviewWindow,
    state: tauri::State<'_, MiniPlayerWindowState>,
) -> Result<(), String> {
    window.set_always_on_top(false).map_err(|e| e.to_string())?;

    window
        .set_min_size(Some(Size::Logical(LogicalSize::new(1024.0, 680.0))))
        .map_err(|e| e.to_string())?;

    let snapshot = state
        .saved
        .lock()
        .ok()
        .and_then(|mut guard| guard.take());

    if let Some(saved) = snapshot {
        let target_w = saved.width.max(1024);
        let target_h = saved.height.max(680);
        window
            .set_size(Size::Physical(PhysicalSize::new(target_w, target_h)))
            .map_err(|e| e.to_string())?;

        let (mut restore_x, mut restore_y) = (saved.x, saved.y);
        if !saved.maximized {
            if let Ok(Some(monitor)) = window.current_monitor() {
                let work = monitor.work_area();
                let max_x =
                    (work.position.x + work.size.width as i32 - target_w as i32).max(work.position.x);
                let max_y = (work.position.y + work.size.height as i32 - target_h as i32)
                    .max(work.position.y);
                restore_x = restore_x.clamp(work.position.x, max_x);
                restore_y = restore_y.clamp(work.position.y, max_y);
            }
        }

        window
            .set_position(Position::Physical(PhysicalPosition::new(
                restore_x, restore_y,
            )))
            .map_err(|e| e.to_string())?;
        if saved.maximized {
            window.maximize().map_err(|e| e.to_string())?;
        }
    } else {
        window
            .set_size(Size::Logical(LogicalSize::new(1360.0, 860.0)))
            .map_err(|e| e.to_string())?;
        let _ = window.center();
    }

    Ok(())
}

#[tauri::command]
fn resize_mini_player(window: tauri::WebviewWindow, width: f64, height: f64) -> Result<(), String> {
    let clamped_w = width.clamp(300.0, 960.0);
    let clamped_h = height.clamp(152.0, 960.0);
    window
        .set_size(Size::Logical(LogicalSize::new(clamped_w, clamped_h)))
        .map_err(|e| e.to_string())?;
    clamp_window_to_work_area(&window, clamped_w, clamped_h);
    Ok(())
}

#[tauri::command]
fn set_mini_always_on_top(window: tauri::WebviewWindow, pinned: bool) -> Result<(), String> {
    window.set_always_on_top(pinned).map_err(|e| e.to_string())
}

#[tauri::command]
fn quit_app(
    app: tauri::AppHandle,
    backend: tauri::State<'_, Arc<BackendManager>>,
    exit_state: tauri::State<'_, AppExitState>,
) {
    exit_state.confirmed.store(true, Ordering::SeqCst);
    backend.shutdown();
    if let Some(tray) = app.tray_by_id("flacify-tray") {
        let _ = tray.set_visible(false);
    }
    app.exit(0);
}

fn show_main_window(app: &tauri::AppHandle) {
    if let Some(win) = app.get_webview_window("main") {
        let _ = win.unminimize();
        let _ = win.show();
        let _ = win.set_focus();
    }
}

fn hide_main_window(app: &tauri::AppHandle) {
    if let Some(win) = app.get_webview_window("main") {
        let _ = win.hide();
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let backend = BackendManager::new();
    let backend_manage = backend.clone();
    let backend_setup = backend.clone();
    let backend_tray = backend.clone();
    let backend_run = backend.clone();

    let app = tauri::Builder::default()
        .manage(MiniPlayerWindowState::default())
        .manage(AppExitState::default())
        .manage(backend_manage)
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            show_main_window(app);
        }))
        .plugin(tauri_plugin_dialog::init())
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                let confirmed = window
                    .try_state::<AppExitState>()
                    .map(|s| s.confirmed.load(Ordering::SeqCst))
                    .unwrap_or(false);
                if confirmed {
                    return;
                }

                if let Some(state) = window.try_state::<MiniPlayerWindowState>() {
                    let in_mini = state
                        .saved
                        .lock()
                        .ok()
                        .map(|g| g.is_some())
                        .unwrap_or(false);
                    if in_mini {
                        api.prevent_close();
                        let _ = window.emit("flacify://exit-mini-player", ());
                        return;
                    }
                }

                api.prevent_close();
                let _ = window.unminimize();
                let _ = window.show();
                let _ = window.set_focus();
                let _ = window.emit("flacify://request-close", ());
            }
        })
        .invoke_handler(tauri::generate_handler![
            enter_mini_player,
            exit_mini_player,
            resize_mini_player,
            set_mini_always_on_top,
            quit_app
        ])
        .setup(move |app| {
            backend_setup.start();

            let show_item = MenuItem::with_id(app, "show", "Show Flacify", true, None::<&str>)?;
            let mini_item =
                MenuItem::with_id(app, "mini_player", "Toggle Mini Player", true, None::<&str>)?;
            let hide_item = MenuItem::with_id(app, "hide", "Hide to Tray", true, None::<&str>)?;
            let separator = PredefinedMenuItem::separator(app)?;
            let quit_item = MenuItem::with_id(app, "quit", "Quit Flacify", true, None::<&str>)?;
            let menu = Menu::with_items(
                app,
                &[&show_item, &mini_item, &hide_item, &separator, &quit_item],
            )?;

            let tray_backend = backend_tray.clone();
            let mut tray_builder = TrayIconBuilder::with_id("flacify-tray")
                .menu(&menu)
                .tooltip("Flacify — Lossless Audio Studio")
                .show_menu_on_left_click(false)
                .on_menu_event(move |app, event| match event.id.as_ref() {
                    "show" => show_main_window(app),
                    "mini_player" => {
                        show_main_window(app);
                        let _ = app.emit("flacify://toggle-mini-player", ());
                    }
                    "hide" => hide_main_window(app),
                    "quit" => {
                        if let Some(exit_state) = app.try_state::<AppExitState>() {
                            exit_state.confirmed.store(true, Ordering::SeqCst);
                        }
                        tray_backend.shutdown();
                        if let Some(tray) = app.tray_by_id("flacify-tray") {
                            let _ = tray.set_visible(false);
                        }
                        app.exit(0);
                    }
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        show_main_window(tray.app_handle());
                    }
                });

            if let Some(icon) = app.default_window_icon().cloned() {
                tray_builder = tray_builder.icon(icon);
            }
            tray_builder.build(app)?;

            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building Flacify Tauri desktop application");

    app.run(move |_app_handle, event| {
        if let RunEvent::Exit = event {
            backend_run.shutdown();
        }
    });
}
