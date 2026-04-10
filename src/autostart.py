"""macOS LaunchAgent helpers for voiced desktop autostart."""

from __future__ import annotations

import plistlib
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

SOURCE_ROOT = Path(__file__).resolve().parent.parent


LAUNCH_AGENT_LABEL = "com.voiceinput.voiced"
LAUNCH_AGENT_FILENAME = f"{LAUNCH_AGENT_LABEL}.plist"


def get_launch_agent_path(home: Path | None = None) -> Path:
    """返回当前用户的 LaunchAgent plist 路径。"""
    base_dir = (home or Path.home()) / "Library" / "LaunchAgents"
    return base_dir / LAUNCH_AGENT_FILENAME


def resolve_program_arguments(project_root: Path = SOURCE_ROOT) -> list[str]:
    """解析 voiced 在当前环境下的启动命令。"""
    project_python = project_root / "venv" / "bin" / "python"
    if project_python.exists():
        return [str(project_python), "-m", "desktop_entry"]
    return [sys.executable, "-m", "desktop_entry"]


def get_launch_agent_log_paths(runtime_root: Path) -> tuple[Path, Path]:
    """返回 LaunchAgent stdout/stderr 日志路径。"""
    logs_dir = runtime_root / "logs"
    return logs_dir / "voiced.stdout.log", logs_dir / "voiced.stderr.log"


def generate_launch_agent_plist(
    program_arguments: list[str],
    working_directory: Path,
    runtime_root: Path,
) -> str:
    """生成 voiced 对应的 LaunchAgent plist 内容。"""
    stdout_path, stderr_path = get_launch_agent_log_paths(runtime_root)
    executable_dir = Path(program_arguments[0]).resolve().parent
    path_value = ":".join(
        [
            str(executable_dir),
            "/opt/homebrew/bin",
            "/usr/local/bin",
            "/usr/bin",
            "/bin",
            "/usr/sbin",
            "/sbin",
        ]
    )

    payload = {
        "Label": LAUNCH_AGENT_LABEL,
        "ProgramArguments": program_arguments,
        "RunAtLoad": True,
        "KeepAlive": True,
        "LimitLoadToSessionType": ["Aqua"],
        "WorkingDirectory": str(working_directory),
        "EnvironmentVariables": {
            "PATH": path_value,
        },
        "StandardOutPath": str(stdout_path),
        "StandardErrorPath": str(stderr_path),
    }
    return plistlib.dumps(payload, fmt=plistlib.FMT_XML, sort_keys=False).decode("utf-8")


def install_launch_agent(runtime_root: Path, project_root: Path = SOURCE_ROOT, home: Path | None = None) -> Path:
    """安装并加载 voiced 的 LaunchAgent。"""
    launch_agent_path = get_launch_agent_path(home)
    launch_agent_path.parent.mkdir(parents=True, exist_ok=True)

    stdout_path, stderr_path = get_launch_agent_log_paths(runtime_root)
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)

    plist_content = generate_launch_agent_plist(
        program_arguments=resolve_program_arguments(project_root),
        working_directory=project_root,
        runtime_root=runtime_root,
    )
    launch_agent_path.write_text(plist_content, encoding="utf-8")

    subprocess.run(
        ["launchctl", "unload", "-w", str(launch_agent_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    subprocess.run(["launchctl", "load", "-w", str(launch_agent_path)], check=True)
    return launch_agent_path


def uninstall_launch_agent(home: Path | None = None) -> Path:
    """卸载 voiced 的 LaunchAgent。"""
    launch_agent_path = get_launch_agent_path(home)
    if launch_agent_path.exists():
        subprocess.run(
            ["launchctl", "unload", "-w", str(launch_agent_path)],
            check=False,
            capture_output=True,
            text=True,
        )
        launch_agent_path.unlink()
    return launch_agent_path


def parse_launchctl_status(output: str) -> dict[str, Any]:
    """解析 launchctl list 输出。"""
    pid_match = re.search(r'^\s*"PID"\s*=\s*(\d+);', output, flags=re.MULTILINE)
    if pid_match is None:
        pid_match = re.search(r"^(\d+)\s+\S+\s+" + re.escape(LAUNCH_AGENT_LABEL) + r"$", output, flags=re.MULTILINE)

    exit_match = re.search(r'^\s*"LastExitStatus"\s*=\s*(\d+);', output, flags=re.MULTILINE)
    if exit_match is None:
        exit_match = re.search(r"^\S+\s+(\d+)\s+" + re.escape(LAUNCH_AGENT_LABEL) + r"$", output, flags=re.MULTILINE)

    pid = int(pid_match.group(1)) if pid_match else None
    last_exit_status = int(exit_match.group(1)) if exit_match else None
    loaded = LAUNCH_AGENT_LABEL in output
    return {
        "loaded": loaded,
        "running": pid is not None,
        "pid": pid,
        "last_exit_status": last_exit_status,
    }


def get_launch_agent_status() -> dict[str, Any]:
    """查询 voiced LaunchAgent 当前状态。"""
    result = subprocess.run(
        ["launchctl", "list", LAUNCH_AGENT_LABEL],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return {
            "loaded": False,
            "running": False,
            "pid": None,
            "last_exit_status": None,
        }
    return parse_launchctl_status(result.stdout)
