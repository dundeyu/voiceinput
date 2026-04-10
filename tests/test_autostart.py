from unittest.mock import Mock, patch

from autostart import (
    LAUNCH_AGENT_LABEL,
    generate_launch_agent_plist,
    get_launch_agent_log_paths,
    get_launch_agent_path,
    get_launch_agent_status,
    install_launch_agent,
    parse_launchctl_status,
    resolve_program_arguments,
    uninstall_launch_agent,
)
from voice_entry import _handle_autostart_command, main


def test_generate_launch_agent_plist_contains_required_keys(tmp_path):
    plist_text = generate_launch_agent_plist(
        program_arguments=["/tmp/project/venv/bin/python", "-m", "desktop_entry"],
        working_directory=tmp_path,
        runtime_root=tmp_path,
    )

    assert LAUNCH_AGENT_LABEL in plist_text
    assert "<key>RunAtLoad</key>" in plist_text
    assert "<key>KeepAlive</key>" in plist_text
    assert "<key>LimitLoadToSessionType</key>" in plist_text
    assert "<string>Aqua</string>" in plist_text
    assert "<key>WorkingDirectory</key>" in plist_text
    assert "<key>StandardOutPath</key>" in plist_text
    assert "<key>StandardErrorPath</key>" in plist_text


def test_get_launch_agent_log_paths_under_logs_directory(tmp_path):
    stdout_path, stderr_path = get_launch_agent_log_paths(tmp_path)

    assert stdout_path == tmp_path / "logs" / "voiced.stdout.log"
    assert stderr_path == tmp_path / "logs" / "voiced.stderr.log"


def test_resolve_program_arguments_prefers_project_venv(tmp_path):
    project_root = tmp_path / "project"
    python_path = project_root / "venv" / "bin" / "python"
    python_path.parent.mkdir(parents=True)
    python_path.write_text("", encoding="utf-8")

    args = resolve_program_arguments(project_root)

    assert args == [str(python_path), "-m", "desktop_entry"]


def test_install_launch_agent_writes_plist_and_loads_agent(tmp_path):
    home_dir = tmp_path / "home"
    project_root = tmp_path / "project"
    runtime_root = tmp_path / "runtime"
    python_path = project_root / "venv" / "bin" / "python"
    python_path.parent.mkdir(parents=True)
    python_path.write_text("", encoding="utf-8")

    with patch("autostart.subprocess.run") as run_mock:
        launch_agent_path = install_launch_agent(runtime_root, project_root=project_root, home=home_dir)

    assert launch_agent_path == home_dir / "Library" / "LaunchAgents" / "com.voiceinput.voiced.plist"
    assert launch_agent_path.exists()
    assert any(call.args[0][:3] == ["launchctl", "unload", "-w"] for call in run_mock.call_args_list)
    assert any(call.args[0][:3] == ["launchctl", "load", "-w"] for call in run_mock.call_args_list)


def test_uninstall_launch_agent_unloads_and_removes_plist(tmp_path):
    home_dir = tmp_path / "home"
    launch_agent_path = get_launch_agent_path(home_dir)
    launch_agent_path.parent.mkdir(parents=True)
    launch_agent_path.write_text("demo", encoding="utf-8")

    with patch("autostart.subprocess.run") as run_mock:
        removed_path = uninstall_launch_agent(home=home_dir)

    assert removed_path == launch_agent_path
    assert not launch_agent_path.exists()
    run_mock.assert_called_once()
    assert run_mock.call_args.args[0][:3] == ["launchctl", "unload", "-w"]


def test_parse_launchctl_status_handles_running_service():
    output = '''{
    "Label" = "com.voiceinput.voiced";
    "PID" = 1234;
    "LastExitStatus" = 0;
};
'''

    status = parse_launchctl_status(output)

    assert status == {
        "loaded": True,
        "running": True,
        "pid": 1234,
        "last_exit_status": 0,
    }


def test_parse_launchctl_status_handles_loaded_but_not_running_service():
    output = '''{
    "Label" = "com.voiceinput.voiced";
    "LastExitStatus" = 78;
};
'''

    status = parse_launchctl_status(output)

    assert status == {
        "loaded": True,
        "running": False,
        "pid": None,
        "last_exit_status": 78,
    }


def test_get_launch_agent_status_returns_not_loaded_when_launchctl_fails():
    result = Mock(returncode=113, stdout="", stderr="Could not find service")

    with patch("autostart.subprocess.run", return_value=result):
        status = get_launch_agent_status()

    assert status == {
        "loaded": False,
        "running": False,
        "pid": None,
        "last_exit_status": None,
    }


def test_handle_autostart_install_prints_success_message(tmp_path, capsys):
    args = Mock(autostart_command="install")

    with patch("voice_entry.install_launch_agent", return_value=tmp_path / "agent.plist"):
        exit_code = _handle_autostart_command(args, tmp_path)

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "已安装 voiced 开机自启动" in captured.out


def test_handle_autostart_status_prints_running_pid(tmp_path, capsys):
    args = Mock(autostart_command="status")

    with patch(
        "voice_entry.get_launch_agent_status",
        return_value={"loaded": True, "running": True, "pid": 4321, "last_exit_status": 0},
    ):
        exit_code = _handle_autostart_command(args, tmp_path)

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PID: 4321" in captured.out


def test_main_routes_autostart_before_loading_runtime_config(tmp_path):
    with patch("sys.argv", ["voice", "autostart", "status"]), patch(
        "voice_entry._resolve_runtime_root_for_autostart", return_value=tmp_path
    ), patch("voice_entry._handle_autostart_command", return_value=0) as handle_mock, patch(
        "voice_entry.load_runtime_config", side_effect=AssertionError("should not load runtime config")
    ):
        exit_code = main()

    assert exit_code == 0
    handle_mock.assert_called_once()
