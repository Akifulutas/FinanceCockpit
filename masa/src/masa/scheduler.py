"""macOS launchd Plist Generator and Schedule Manager (İP-12).

Design Invariants:
1. Native launchd XML plists generated via python's standard plistlib.
2. Scheduled timings:
   - Sabah: Monday-Friday 09:30 CET (Tahmin üretici: 5 ETF + 5 hisse).
   - Akşam: Monday-Friday 17:40 CET (Tahmin uzlaşma & Pano güncelleme).
   - Cuma: Friday 18:00 CET (Haftalık karne & Rapor konsolidasyonu).
3. Absolute paths: Uses fully qualified wrapper path (etf-masa) and masa/var/logs for stdout/stderr.
4. Idempotent install and uninstall operations.
"""

from __future__ import annotations

import logging
from pathlib import Path
import plistlib
import shutil
import subprocess
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_LAUNCHAGENTS_DIR = Path.home() / "Library" / "LaunchAgents"

JOB_SPECS = [
    {
        "label": "com.etf.masa.sabah",
        "description": "Sabah 09:30 CET Günlük Tahmin Üretici (5 ETF + 5 Hisse)",
        "subcommand": ["tahmin", "uret"],
        "intervals": [
            {"Weekday": w, "Hour": 9, "Minute": 30} for w in range(1, 6)  # Mon-Fri
        ],
    },
    {
        "label": "com.etf.masa.aksam",
        "description": "Akşam 17:40 CET Kapanış Tahmin Uzlaşması ve Pano",
        "subcommand": ["tahmin", "uzlas"],
        "intervals": [
            {"Weekday": w, "Hour": 17, "Minute": 40} for w in range(1, 6)  # Mon-Fri
        ],
    },
    {
        "label": "com.etf.masa.cuma",
        "description": "Cuma 18:00 CET Haftalık Tahmin Karnesi ve Pano",
        "subcommand": ["tahmin", "karne", "--detay"],
        "intervals": [
            {"Weekday": 5, "Hour": 18, "Minute": 0}  # Friday 18:00
        ],
    },
]


def find_executable_wrapper() -> Path:
    """Find etf-masa wrapper script or masa CLI executable."""
    # Try ETF/etf-masa wrapper first
    current_dir = Path(__file__).resolve().parent.parent.parent.parent
    wrapper = current_dir / "etf-masa"
    if wrapper.exists() and os_is_executable(wrapper):
        return wrapper

    # Try masa/.venv/bin/masa
    venv_masa = current_dir / "masa" / ".venv" / "bin" / "masa"
    if venv_masa.exists():
        return venv_masa

    return Path("/usr/local/bin/masa")


def os_is_executable(p: Path) -> bool:
    import os
    return os.access(p, os.X_OK)


def generate_plist_dict(
    spec: Dict[str, Any],
    executable: Optional[Path] = None,
    log_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Build a python dict representing a valid launchd XML plist."""
    exe = executable or find_executable_wrapper()
    label = spec["label"]

    base_log = log_dir or (exe.parent / "masa" / "var" / "logs" if exe.name == "etf-masa" else exe.parent.parent / "var" / "logs")
    base_log.mkdir(parents=True, exist_ok=True)

    stdout_log = str(base_log / f"{label}.stdout.log")
    stderr_log = str(base_log / f"{label}.stderr.log")

    program_args = [str(exe)] + spec["subcommand"]

    return {
        "Label": label,
        "ProgramArguments": program_args,
        "StartCalendarInterval": spec["intervals"],
        "StandardOutPath": stdout_log,
        "StandardErrorPath": stderr_log,
        "RunAtLoad": False,
        "EnvironmentVariables": {
            "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
            "PYTHONUNBUFFERED": "1",
        },
    }


def render_plist_xml(spec: Dict[str, Any], executable: Optional[Path] = None, log_dir: Optional[Path] = None) -> bytes:
    """Serialize launchd job specification to valid XML plist bytes."""
    data = generate_plist_dict(spec, executable=executable, log_dir=log_dir)
    return plistlib.dumps(data, fmt=plistlib.FMT_XML)


def install_jobs(
    dest_dir: Optional[Path] = None,
    executable: Optional[Path] = None,
    run_launchctl: bool = True,
) -> List[Path]:
    """Generate plists, copy to LaunchAgents directory, and load into launchd."""
    target_dir = dest_dir or DEFAULT_LAUNCHAGENTS_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    installed_files: List[Path] = []
    for spec in JOB_SPECS:
        plist_content = render_plist_xml(spec, executable=executable)
        plist_path = target_dir / f"{spec['label']}.plist"
        plist_path.write_bytes(plist_content)
        installed_files.append(plist_path)

        if run_launchctl and shutil.which("launchctl"):
            try:
                # Unload first if previously loaded, then load
                subprocess.run(["launchctl", "unload", str(plist_path)], capture_output=True, check=False)
                subprocess.run(["launchctl", "load", str(plist_path)], capture_output=True, check=False)
            except Exception as exc:
                logger.warning(f"launchctl load hatası ({spec['label']}): {exc}")

    return installed_files


def uninstall_jobs(
    dest_dir: Optional[Path] = None,
    run_launchctl: bool = True,
) -> List[Path]:
    """Unload from launchd and remove plist files."""
    target_dir = dest_dir or DEFAULT_LAUNCHAGENTS_DIR
    removed_files: List[Path] = []

    for spec in JOB_SPECS:
        plist_path = target_dir / f"{spec['label']}.plist"
        if plist_path.exists():
            if run_launchctl and shutil.which("launchctl"):
                try:
                    subprocess.run(["launchctl", "unload", str(plist_path)], capture_output=True, check=False)
                except Exception:
                    pass
            plist_path.unlink(missing_ok=True)
            removed_files.append(plist_path)

    return removed_files


def get_schedule_status(dest_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Inspect installed launchd job status dynamically."""
    target_dir = dest_dir or DEFAULT_LAUNCHAGENTS_DIR
    results: List[Dict[str, Any]] = []

    launchd_status: Dict[str, Dict[str, Any]] = {}
    if shutil.which("launchctl"):
        try:
            res = subprocess.run(["launchctl", "list"], capture_output=True, text=True, check=False)
            if res.returncode == 0:
                for line in res.stdout.splitlines():
                    parts = line.strip().split()
                    if len(parts) >= 3:
                        pid_str, status_str, lbl = parts[0], parts[1], parts[2]
                        if lbl.startswith("com.etf.masa"):
                            last_code = None
                            if status_str != "-" and (status_str.isdigit() or (status_str.startswith("-") and status_str[1:].isdigit())):
                                last_code = int(status_str)
                            launchd_status[lbl] = {
                                "loaded": True,
                                "pid": int(pid_str) if pid_str.isdigit() else None,
                                "last_exit_code": last_code,
                            }
        except Exception:
            pass

    for spec in JOB_SPECS:
        label = spec["label"]
        plist_path = target_dir / f"{label}.plist"
        is_installed = plist_path.exists()
        info = launchd_status.get(label, {"loaded": False, "last_exit_code": None})

        if "sabah" in label:
            sched = "Pzt-Cum 09:30 CET"
        elif "aksam" in label:
            sched = "Pzt-Cum 17:40 CET"
        elif "cuma" in label:
            sched = "Cuma 18:00 CET"
        else:
            sched = "Zamanlanmış"

        log_lines: List[str] = []
        try:
            exe = find_executable_wrapper()
            base_log = exe.parent / "masa" / "var" / "logs" if exe.name == "etf-masa" else exe.parent.parent / "var" / "logs"
            out_log = base_log / f"{label}.stdout.log"
            err_log = base_log / f"{label}.stderr.log"
            for lpath in [err_log, out_log]:
                if lpath.exists():
                    lines = lpath.read_text(encoding="utf-8", errors="replace").splitlines()
                    if lines:
                        log_lines.extend(lines[-5:])
        except Exception:
            pass

        results.append({
            "label": label,
            "description": spec["description"],
            "schedule": sched,
            "installed": is_installed,
            "loaded": info["loaded"],
            "last_exit_code": info["last_exit_code"],
            "plist_path": str(plist_path) if is_installed else None,
            "log_lines": log_lines[-5:] if log_lines else [],
        })

    return results
