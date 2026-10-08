import os
import sys
import shutil
import subprocess
import hashlib
from pathlib import Path


def log(msg: str):
    print(f"\n[BUILD] {msg}")


def check_and_install_pyinstaller():
    """Ensures PyInstaller is installed in the active Python environment."""
    try:
        import PyInstaller
        log(f"PyInstaller is installed (v{PyInstaller.__version__})")
        return True
    except ImportError:
        log("PyInstaller not detected. Installing via pip...")
        res = subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"], check=False)
        if res.returncode == 0:
            log("PyInstaller installed successfully.")
            return True
        else:
            log("ERROR: Failed to install PyInstaller via pip.")
            return False


def ensure_icon(repo_root: Path):
    """Ensures assets/icon.ico exists, generating it from source images if needed."""
    ico_path = repo_root / "assets" / "icon.ico"
    if ico_path.exists() and ico_path.stat().st_size > 1000:
        log(f"Application icon found at {ico_path} ({ico_path.stat().st_size:,} bytes)")
        return True

    convert_script = repo_root / "assets" / "convert_icon.py"
    if convert_script.exists():
        log("Running convert_icon.py to generate assets/icon.ico...")
        res = subprocess.run([sys.executable, str(convert_script)], cwd=str(repo_root), check=False)
        if res.returncode == 0 and ico_path.exists():
            log(f"Icon generated successfully at {ico_path}")
            return True
    log("WARNING: assets/icon.ico not found and could not be generated.")
    return False


def clean_build_artifacts(repo_root: Path):
    """Purges previous build/ and dist/Flacify folders."""
    log("Cleaning previous build artifacts...")
    for folder in [repo_root / "build", repo_root / "dist" / "Flacify"]:
        if folder.exists():
            try:
                shutil.rmtree(folder)
                print(f"  Removed: {folder}")
            except Exception as e:
                print(f"  Warning: could not delete {folder}: {e}")


def run_pyinstaller(repo_root: Path):
    """Compiles the application into dist/Flacify via PyInstaller."""
    log("Running PyInstaller with app.spec...")
    spec_file = repo_root / "app.spec"
    if not spec_file.exists():
        raise FileNotFoundError(f"Missing {spec_file}")

    cmd = [sys.executable, "-m", "PyInstaller", "app.spec", "--noconfirm"]
    print(f"  Command: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(repo_root), check=False)
    if result.returncode != 0:
        raise RuntimeError(f"PyInstaller failed with exit code {result.returncode}")

    target_exe = repo_root / "dist" / "Flacify" / "Flacify.exe"
    if not target_exe.exists():
        raise FileNotFoundError(f"PyInstaller completed but executable not found: {target_exe}")

    exe_size = target_exe.stat().st_size
    log(f"PyInstaller build succeeded! Output: {target_exe} ({exe_size / (1024 * 1024):.2f} MB)")
    return target_exe


def find_iscc() -> Path | None:
    """Locates the Inno Setup Compiler executable (ISCC.exe)."""
    # 1. System PATH
    which_iscc = shutil.which("iscc") or shutil.which("ISCC")
    if which_iscc:
        return Path(which_iscc)

    # 2. Standard Program Files paths
    candidates = [
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Inno Setup 5" / "ISCC.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
    ]
    for c in candidates:
        if c.exists() and c.is_file():
            return c

    return None


def run_inno_setup(repo_root: Path, iscc_path: Path):
    """Compiles installer.iss into dist/installer/Flacify_Setup_v1.0.0.exe."""
    log(f"Compiling Inno Setup installer using {iscc_path}...")
    iss_file = repo_root / "installer.iss"
    if not iss_file.exists():
        raise FileNotFoundError(f"Missing {iss_file}")

    installer_out_dir = repo_root / "dist" / "installer"
    installer_out_dir.mkdir(parents=True, exist_ok=True)

    cmd = [str(iscc_path), str(iss_file)]
    print(f"  Command: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(repo_root), check=False)
    if result.returncode != 0:
        raise RuntimeError(f"ISCC compilation failed with exit code {result.returncode}")

    setup_exe = installer_out_dir / "Flacify_Setup_v1.0.1.exe"
    if not setup_exe.exists():
        # Fallback to any Flacify_Setup_*.exe found in installer_out_dir
        matches = list(installer_out_dir.glob("Flacify_Setup_*.exe"))
        if matches:
            setup_exe = matches[0]
        else:
            raise FileNotFoundError(f"Installer compilation completed but {setup_exe} not found")

    size_mb = setup_exe.stat().st_size / (1024 * 1024)
    # Compute sha256
    h = hashlib.sha256()
    with open(setup_exe, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)

    log(f"Installer built successfully!")
    print(f"  Location : {setup_exe}")
    print(f"  Size     : {size_mb:.2f} MB ({setup_exe.stat().st_size:,} bytes)")
    print(f"  SHA-256  : {h.hexdigest()}")
    return setup_exe


def main():
    repo_root = Path(__file__).resolve().parent
    log("==================================================")
    log("  Flacify — Windows Packaging & Release Pipeline  ")
    log("==================================================")

    # 1. Ensure Python dependencies
    if not check_and_install_pyinstaller():
        sys.exit(1)

    # 2. Ensure Icon
    ensure_icon(repo_root)

    # 3. Clean
    clean_build_artifacts(repo_root)

    # 4. PyInstaller Freeze
    try:
        app_exe = run_pyinstaller(repo_root)
    except Exception as e:
        log(f"FATAL: PyInstaller build failed: {e}")
        sys.exit(1)

    # 5. Inno Setup Compiler
    iscc_path = find_iscc()
    if iscc_path:
        log(f"Inno Setup Compiler detected at {iscc_path}")
        try:
            setup_exe = run_inno_setup(repo_root, iscc_path)
            log("SUCCESS: End-to-end packaging pipeline complete!")
            print(f"\nSummary:")
            print(f"  Standalone App : {app_exe}")
            print(f"  Setup Package  : {setup_exe}")
        except Exception as e:
            log(f"ERROR: Inno Setup compilation failed: {e}")
            sys.exit(1)
    else:
        log("NOTICE: Inno Setup compiler (ISCC.exe) was not found on this system.")
        print("  The standalone application is ready at:")
        print(f"    {app_exe}")
        print("\n  To compile the Windows installer (.iss into .exe):")
        print("    1. Install Inno Setup via Windows Terminal:")
        print("       winget install JRSoftware.InnoSetup")
        print("    2. Re-run this build script:")
        print("       python build_windows.py")


if __name__ == "__main__":
    main()
