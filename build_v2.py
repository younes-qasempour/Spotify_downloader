"""
Flacify v2.0 Windows Packaging & Standalone Installer Build Pipeline.

Steps:
1. Typecheck & build React + Vite production frontend (`frontend/dist/`).
2. Compile Tauri v2 Windows desktop executable (`desktop/src-tauri/target/release/flacify.exe`).
3. Freeze FastAPI + core Python backend sidecar (`dist/flacify-backend/`).
4. Assemble unified bundle at `dist/Flacify-v2/` with sidecar under `binaries/flacify-backend/`.
5. Compile Inno Setup installer (`dist/installer/Flacify_Setup_v2.0.0.exe`).
"""

import argparse
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


def get_app_version(repo_root: Path) -> str:
    init_py = repo_root / "core" / "__init__.py"
    text = init_py.read_text(encoding="utf-8")
    match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', text)
    return match.group(1) if match else "2.0.0"


def log(msg: str) -> None:
    print(f"\n[BUILD v2.0] {msg}")


def run_step(cmd: list[str], cwd: Path, env: dict[str, str] | None = None) -> None:
    print(f"  > {' '.join(cmd)} (cwd={cwd})")
    res = subprocess.run(cmd, cwd=str(cwd), env=env, check=False)
    if res.returncode != 0:
        raise RuntimeError(f"Command failed ({res.returncode}): {' '.join(cmd)}")


def find_iscc() -> Path | None:
    which_iscc = shutil.which("iscc") or shutil.which("ISCC")
    if which_iscc:
        return Path(which_iscc)
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Inno Setup 6" / "ISCC.exe",
    ]
    for cand in candidates:
        if cand.is_file():
            return cand
    return None


def compute_sha256(file_path: Path) -> str:
    h = hashlib.sha256()
    with open(file_path, "rb") as fh:
        while chunk := fh.read(65536):
            h.update(chunk)
    return h.hexdigest()


def build_frontend(repo_root: Path) -> None:
    log("Building React + TypeScript frontend (`frontend/dist`)...")
    frontend_dir = repo_root / "frontend"
    npm_bin = "npm.cmd" if os.name == "nt" else "npm"
    run_step([npm_bin, "run", "typecheck"], cwd=frontend_dir)
    run_step([npm_bin, "run", "build"], cwd=frontend_dir)


def build_tauri_desktop(repo_root: Path) -> Path:
    log("Compiling Tauri v2 desktop shell (`flacify.exe`)...")
    desktop_dir = repo_root / "desktop"
    npm_bin = "npm.cmd" if os.name == "nt" else "npm"
    env = os.environ.copy()
    cargo_bin = str(Path.home() / ".cargo" / "bin")
    if cargo_bin not in env.get("PATH", ""):
        env["PATH"] = f"{cargo_bin}{os.pathsep}{env.get('PATH', '')}"

    run_step([npm_bin, "run", "build:exe"], cwd=desktop_dir, env=env)
    exe_path = desktop_dir / "src-tauri" / "target" / "release" / "flacify.exe"
    if not exe_path.is_file():
        raise FileNotFoundError(f"Missing Tauri binary after build: {exe_path}")
    return exe_path


def build_backend_sidecar(repo_root: Path) -> Path:
    log("Freezing FastAPI backend sidecar (`backend.spec`)...")
    build_work = repo_root / "build" / "backend"
    dist_backend = repo_root / "dist" / "flacify-backend"
    for p in (build_work, dist_backend):
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)

    run_step(
        [sys.executable, "-m", "PyInstaller", "backend.spec", "--noconfirm"],
        cwd=repo_root,
    )
    backend_exe = dist_backend / "flacify-backend.exe"
    if not backend_exe.is_file():
        raise FileNotFoundError(f"Missing frozen backend sidecar: {backend_exe}")
    return dist_backend


def assemble_v2_bundle(repo_root: Path, tauri_exe: Path, backend_dir: Path) -> Path:
    log("Assembling unified `dist/Flacify-v2/` application bundle...")
    bundle_dir = repo_root / "dist" / "Flacify-v2"
    if bundle_dir.exists():
        shutil.rmtree(bundle_dir)
    bundle_dir.mkdir(parents=True, exist_ok=True)

    target_app_exe = bundle_dir / "Flacify.exe"
    shutil.copy2(tauri_exe, target_app_exe)

    target_sidecar_dir = bundle_dir / "binaries" / "flacify-backend"
    shutil.copytree(backend_dir, target_sidecar_dir)

    print(f"  Desktop Exe : {target_app_exe} ({target_app_exe.stat().st_size:,} bytes)")
    print(f"  Backend Dir : {target_sidecar_dir}")
    return bundle_dir


def compile_installer(repo_root: Path, iscc_path: Path, app_version: str) -> Path:
    log(f"Compiling Inno Setup v{app_version} installer via {iscc_path}...")
    iss_path = repo_root / "installer_v2.iss"
    installer_out_dir = repo_root / "dist" / "installer"
    installer_out_dir.mkdir(parents=True, exist_ok=True)

    run_step([str(iscc_path), str(iss_path)], cwd=repo_root)
    setup_exe = installer_out_dir / f"Flacify_Setup_v{app_version}.exe"
    if not setup_exe.is_file():
        matches = sorted(installer_out_dir.glob("Flacify_Setup_v2*.exe"), reverse=True)
        if matches:
            setup_exe = matches[0]
        else:
            raise FileNotFoundError(f"Expected installer not found: {setup_exe}")

    size_mb = setup_exe.stat().st_size / (1024 * 1024)
    digest = compute_sha256(setup_exe)
    log(f"Flacify v{app_version} Installer Ready!")
    print(f"  Location : {setup_exe}")
    print(f"  Size     : {size_mb:.2f} MB ({setup_exe.stat().st_size:,} bytes)")
    print(f"  SHA-256  : {digest}")
    return setup_exe


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Flacify v2.x Desktop + Web Bundle")
    parser.add_argument(
        "--skip-installer",
        action="store_true",
        help="Skip Inno Setup installer compilation even if ISCC.exe is present",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent
    app_version = get_app_version(repo_root)
    build_frontend(repo_root)
    tauri_exe = build_tauri_desktop(repo_root)
    backend_dir = build_backend_sidecar(repo_root)
    bundle_dir = assemble_v2_bundle(repo_root, tauri_exe, backend_dir)

    if args.skip_installer:
        log(f"Bundle assembled (--skip-installer): {bundle_dir}")
        return

    iscc = find_iscc()
    if iscc is None:
        log("Notice: Inno Setup (ISCC.exe) not found; skipping installer compilation.")
        print(f"  Portable bundle ready at: {bundle_dir}")
        return

    compile_installer(repo_root, iscc, app_version)


if __name__ == "__main__":
    main()
