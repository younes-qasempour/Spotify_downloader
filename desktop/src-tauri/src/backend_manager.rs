use std::io::{Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

#[cfg(target_os = "windows")]
use std::os::windows::process::CommandExt;

#[cfg(target_os = "windows")]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

const BACKEND_PORT: u16 = 8765;

pub struct BackendManager {
    child: Mutex<Option<Child>>,
    port: u16,
}

impl BackendManager {
    pub fn new() -> Arc<Self> {
        Arc::new(Self {
            child: Mutex::new(None),
            port: BACKEND_PORT,
        })
    }

    pub fn is_healthy(&self) -> bool {
        is_backend_healthy(self.port)
    }

    pub fn start(self: &Arc<Self>) {
        if self.is_healthy() {
            eprintln!(
                "[flacify-desktop] Reusing existing backend on 127.0.0.1:{}",
                self.port
            );
            return;
        }

        let spawned = self.spawn_backend_process();
        match spawned {
            Some(child) => {
                if let Ok(mut guard) = self.child.lock() {
                    *guard = Some(child);
                }
                let mgr = Arc::clone(self);
                thread::spawn(move || {
                    let deadline = Instant::now() + Duration::from_secs(15);
                    while Instant::now() < deadline {
                        if mgr.is_healthy() {
                            eprintln!(
                                "[flacify-desktop] Backend ready on 127.0.0.1:{}",
                                mgr.port
                            );
                            return;
                        }
                        thread::sleep(Duration::from_millis(250));
                    }
                    eprintln!(
                        "[flacify-desktop] Warning: backend health probe timed out on port {}",
                        mgr.port
                    );
                });
            }
            None => {
                eprintln!("[flacify-desktop] Failed to locate or spawn Python backend.");
            }
        }
    }

    pub fn shutdown(&self) {
        if let Ok(mut guard) = self.child.lock() {
            if let Some(mut child) = guard.take() {
                let _ = child.kill();
                let _ = child.wait();
            }
        }
    }

    fn spawn_backend_process(&self) -> Option<Child> {
        let port_str = self.port.to_string();

        // 1. Check packaged sidecar executable next to the Tauri binary
        if let Ok(exe_path) = std::env::current_exe() {
            if let Some(exe_dir) = exe_path.parent() {
                let sidecar_candidates = [
                    exe_dir
                        .join("binaries")
                        .join("flacify-backend")
                        .join("flacify-backend.exe"),
                    exe_dir.join("flacify-backend.exe"),
                    exe_dir.join("binaries").join("flacify-backend.exe"),
                ];
                for sidecar in sidecar_candidates {
                    if sidecar.is_file() {
                        let mut cmd = Command::new(&sidecar);
                        cmd.args(["--port", &port_str])
                            .stdin(Stdio::null())
                            .stdout(Stdio::null())
                            .stderr(Stdio::null());
                        #[cfg(target_os = "windows")]
                        cmd.creation_flags(CREATE_NO_WINDOW);
                        if let Ok(child) = cmd.spawn() {
                            return Some(child);
                        }
                    }
                }
            }
        }

        // 2. Fallback to repo Python module (`python -m backend`)
        let repo_root = find_repo_root()?;
        let python_candidates: &[(&str, &[&str])] = &[
            ("python", &["-m", "backend"]),
            ("py", &["-3", "-m", "backend"]),
        ];

        for (bin, base_args) in python_candidates {
            let mut cmd = Command::new(bin);
            cmd.current_dir(&repo_root)
                .args(*base_args)
                .args(["--port", &port_str])
                .env("PYTHONUTF8", "1")
                .stdin(Stdio::null())
                .stdout(Stdio::null())
                .stderr(Stdio::null());
            #[cfg(target_os = "windows")]
            cmd.creation_flags(CREATE_NO_WINDOW);
            if let Ok(child) = cmd.spawn() {
                return Some(child);
            }
        }

        None
    }
}

pub fn is_backend_healthy(port: u16) -> bool {
    let addr: SocketAddr = ([127, 0, 0, 1], port).into();
    let Ok(mut stream) = TcpStream::connect_timeout(&addr, Duration::from_millis(300)) else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_millis(500)));
    let _ = stream.set_write_timeout(Some(Duration::from_millis(500)));

    let req = format!(
        "GET /api/health HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n"
    );
    if stream.write_all(req.as_bytes()).is_err() {
        return false;
    }

    let mut buf = [0_u8; 64];
    match stream.read(&mut buf) {
        Ok(n) if n > 0 => {
            let head = String::from_utf8_lossy(&buf[..n]);
            head.starts_with("HTTP/1.1 200") || head.starts_with("HTTP/1.0 200")
        }
        _ => false,
    }
}

fn find_repo_root() -> Option<PathBuf> {
    let mut seeds: Vec<PathBuf> = Vec::new();
    if let Ok(cwd) = std::env::current_dir() {
        seeds.push(cwd);
    }
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            seeds.push(dir.to_path_buf());
        }
    }

    for seed in seeds {
        let mut cursor = Some(seed.as_path());
        for _ in 0..8 {
            let Some(dir) = cursor else { break };
            if dir.join("backend").join("__main__.py").is_file() {
                return Some(dir.to_path_buf());
            }
            cursor = dir.parent();
        }
    }
    None
}
