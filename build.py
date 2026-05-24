"""End-to-end build script for the JobHunt Windows installer.

Run with the project venv active:

    python build.py            # full release build
    python build.py --skip-installer   # PyInstaller only (faster, dev)
    python build.py --skip-pyinstaller # just rebuild the .iss -> .exe step

Pipeline:

    1.  Generate installer/JobHunt.ico from the embedded raven PNG
        (multi-resolution: 16, 32, 48, 64, 128, 256).
    2.  Run PyInstaller against jobhunt.spec -> dist/JobHunt/JobHunt.exe.
    3.  Run Inno Setup (ISCC.exe) against installer/JobHunt.iss
        -> installer/Output/JobHunt-Setup-<version>.exe.

Prerequisites (install once):

    pip install -r build_requirements.txt
    # Inno Setup 6 from https://jrsoftware.org/isinfo.php
    # (default path C:\\Program Files (x86)\\Inno Setup 6\\ISCC.exe — auto-detected)

The output .exe is what you upload to a GitHub Release. The in-app auto-updater
(jobhunt/updater.py) will find it the next time any friend launches an older
version.
"""

from __future__ import annotations

import argparse
import io
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
ICON_PATH = ROOT / "installer" / "JobHunt.ico"
SPEC_PATH = ROOT / "jobhunt.spec"
ISS_PATH = ROOT / "installer" / "JobHunt.iss"
DIST_DIR = ROOT / "dist" / "JobHunt"


# ----------------------------------------------------------------------------
# Step 1 — generate the .ico from the embedded PNG
# ----------------------------------------------------------------------------


def generate_icon() -> None:
    """Decode the embedded raven PNG and write a multi-resolution .ico.

    Inno Setup and the Windows shell both want a .ico for the installer EXE
    and the installed shortcut. Pillow handles the PNG-to-ICO conversion and
    can pack multiple sizes into one file so the icon renders crisply at
    every Windows zoom level (16 px task tray -> 256 px Explorer thumbnail)."""
    try:
        from PIL import Image
    except ImportError:
        sys.exit(
            "ERROR: Pillow is required to generate the icon.\n"
            "Run: pip install -r build_requirements.txt"
        )

    # Import the embedded bytes directly — avoids depending on Qt at build time.
    sys.path.insert(0, str(ROOT))
    from jobhunt.assets._logo_data import LOGO_PNG_BYTES

    img = Image.open(io.BytesIO(LOGO_PNG_BYTES)).convert("RGBA")
    ICON_PATH.parent.mkdir(parents=True, exist_ok=True)
    sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    img.save(ICON_PATH, format="ICO", sizes=sizes)
    print(f"  [OK] wrote {ICON_PATH.relative_to(ROOT)} "
          f"({', '.join(f'{w}px' for w, _ in sizes)})")


# ----------------------------------------------------------------------------
# Step 2 — PyInstaller
# ----------------------------------------------------------------------------


def run_pyinstaller() -> None:
    """Invoke PyInstaller against jobhunt.spec.

    --clean wipes the build cache (otherwise stale hidden-imports survive
    across version bumps). --noconfirm answers "yes, overwrite dist/" so the
    build doesn't stall waiting for stdin."""
    if not SPEC_PATH.exists():
        sys.exit(f"ERROR: {SPEC_PATH} not found.")
    cmd = [sys.executable, "-m", "PyInstaller", str(SPEC_PATH),
           "--clean", "--noconfirm"]
    print(f"  $ {' '.join(cmd)}")
    subprocess.check_call(cmd, cwd=ROOT)
    if not (DIST_DIR / "JobHunt.exe").exists():
        sys.exit(f"ERROR: PyInstaller finished but {DIST_DIR / 'JobHunt.exe'} is missing.")
    print(f"  [OK] {DIST_DIR.relative_to(ROOT)}/JobHunt.exe")


# ----------------------------------------------------------------------------
# Step 3 — Inno Setup
# ----------------------------------------------------------------------------


def _find_iscc() -> str | None:
    """Return a path to ISCC.exe, searching common Inno Setup install dirs.
    Returns None if Inno Setup isn't on this machine — caller will explain."""
    # Honor an explicit override so users with weird install paths can
    # `set ISCC=...` and ship.
    env = os.environ.get("ISCC")
    if env and Path(env).exists():
        return env
    candidates = [
        r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        r"C:\Program Files\Inno Setup 6\ISCC.exe",
    ]
    for c in candidates:
        if Path(c).exists():
            return c
    on_path = shutil.which("ISCC")
    if on_path:
        return on_path
    return None


def run_inno_setup(version: str) -> None:
    iscc = _find_iscc()
    if iscc is None:
        sys.exit(
            "ERROR: Inno Setup 6 not found.\n"
            "Install from https://jrsoftware.org/isinfo.php, then re-run."
        )
    # /D<name>=<value> sets a preprocessor define inside the .iss. We pass
    # the version (so the output filename and AppVersion line up with what
    # the updater compares against) and the dist dir (so the .iss can stay
    # blissfully unaware of where PyInstaller actually wrote its output).
    cmd = [
        iscc,
        f"/DAppVersion={version}",
        f"/DDistDir={DIST_DIR}",
        str(ISS_PATH),
    ]
    print(f"  $ {' '.join(cmd)}")
    subprocess.check_call(cmd, cwd=ISS_PATH.parent)

    out = ISS_PATH.parent / "Output" / f"JobHunt-Setup-{version}.exe"
    if not out.exists():
        sys.exit(f"ERROR: ISCC reported success but {out} is missing.")
    print(f"  [OK] {out.relative_to(ROOT)}")


# ----------------------------------------------------------------------------
# Driver
# ----------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="Build JobHunt installer")
    parser.add_argument("--skip-icon", action="store_true",
                        help="Reuse installer/JobHunt.ico instead of regenerating.")
    parser.add_argument("--skip-pyinstaller", action="store_true",
                        help="Skip PyInstaller (reuse the existing dist/ tree).")
    parser.add_argument("--skip-installer", action="store_true",
                        help="Stop after PyInstaller — don't run Inno Setup.")
    args = parser.parse_args()

    sys.path.insert(0, str(ROOT))
    from jobhunt.__version__ import __version__

    print(f"Building JobHunt v{__version__}")
    print()

    if args.skip_icon and ICON_PATH.exists():
        print(f"[1/3] Icon: reusing {ICON_PATH.relative_to(ROOT)}")
    else:
        print("[1/3] Icon: generating multi-resolution .ico from embedded PNG")
        generate_icon()
    print()

    if args.skip_pyinstaller:
        print("[2/3] PyInstaller: SKIPPED (--skip-pyinstaller)")
    else:
        print("[2/3] PyInstaller: bundling Python + Qt + jobhunt -> dist/JobHunt/")
        run_pyinstaller()
    print()

    if args.skip_installer:
        print("[3/3] Inno Setup: SKIPPED (--skip-installer)")
        print()
        print("Done. dist/JobHunt/JobHunt.exe is runnable directly.")
        return 0

    print("[3/3] Inno Setup: wrapping dist/JobHunt -> installer/Output/")
    run_inno_setup(__version__)
    print()
    print(f"Done. Upload installer/Output/JobHunt-Setup-{__version__}.exe to GitHub Releases.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
