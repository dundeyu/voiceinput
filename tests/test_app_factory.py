from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app_factory import DEFAULT_VAD_MODEL_PATH, build_runtime, load_config
from voice_entry import (
    load_runtime_config,
    resolve_config_path,
    resolve_runtime_root,
)


def test_load_config_reads_json(tmp_path):
    config_path = tmp_path / "settings.json"
    config_path.write_text('{"offline_mode": true, "model": {"path": "models/demo"}}', encoding="utf-8")

    config = load_config(config_path)

    assert config["offline_mode"] is True
    assert config["model"]["path"] == "models/demo"


def test_build_runtime_wires_components_from_config():
    config = {
        "audio": {
            "input_sample_rate": 48000,
            "target_sample_rate": 16000,
            "channels": 1,
            "dtype": "float32",
        },
        "model": {
            "path": "models/demo",
            "device": "cpu",
            "default_language": "中文",
            "supported_languages": ["中文", "英文"],
        },
        "temp": {
            "audio_dir": "temp",
            "audio_filename": "recording.wav",
        },
        "filler_words": ["嗯"],
        "vocabulary_corrections": {"cloud code": "claude code"},
        "vad_model_path": "",
        "offline_mode": True,
    }

    recorder_instance = Mock(name="recorder")
    processor_instance = Mock(name="processor")
    asr_instance = Mock(name="asr")
    recorder_cls = Mock(return_value=recorder_instance)
    processor_cls = Mock(return_value=processor_instance)
    asr_cls = Mock(return_value=asr_instance)

    fake_modules = {
        "recorder": SimpleNamespace(AudioRecorder=recorder_cls),
        "audio_processor": SimpleNamespace(AudioProcessor=processor_cls),
        "asr_engine": SimpleNamespace(ASREngine=asr_cls),
    }

    with patch.dict("sys.modules", fake_modules):
        recorder, processor, asr_engine, temp_audio_path, supported_languages = build_runtime(
            config,
            Path("/project"),
        )

    assert recorder is recorder_instance
    assert processor is processor_instance
    assert asr_engine is asr_instance
    assert temp_audio_path == Path("/project/temp/recording.wav")
    assert supported_languages == ["中文", "英文"]

    recorder_cls.assert_called_once_with(sample_rate=48000, channels=1, dtype="float32")
    processor_cls.assert_called_once_with(input_sample_rate=48000, target_sample_rate=16000)
    asr_cls.assert_called_once_with(
        model_path=Path("/project/models/demo"),
        device="cpu",
        default_language="中文",
        filler_words=["嗯"],
        vocabulary_corrections={"cloud code": "claude code"},
        vad_model_path=Path("/project") / DEFAULT_VAD_MODEL_PATH,
        offline_mode=True,
    )


def test_resolve_config_path_prefers_local_settings_json(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    settings_path = config_dir / "settings.json"
    settings_path.write_text('{"offline_mode": false}', encoding="utf-8")
    (config_dir / "settings.example.json").write_text('{"offline_mode": true}', encoding="utf-8")

    resolved_path, used_example = resolve_config_path(tmp_path, working_dir=tmp_path)

    assert resolved_path == settings_path
    assert used_example is False


def test_resolve_config_path_prefers_working_directory_settings_json(tmp_path):
    project_root = tmp_path / "project"
    working_dir = tmp_path / "workspace"
    (project_root / "config").mkdir(parents=True)
    (working_dir / "config").mkdir(parents=True)

    repo_settings = project_root / "config" / "settings.json"
    cwd_settings = working_dir / "config" / "settings.json"
    repo_settings.write_text('{"offline_mode": false}', encoding="utf-8")
    cwd_settings.write_text('{"offline_mode": true}', encoding="utf-8")

    resolved_path, used_example = resolve_config_path(project_root, working_dir=working_dir)

    assert resolved_path == cwd_settings
    assert used_example is False


def test_load_runtime_config_falls_back_to_example_file(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    example_path = config_dir / "settings.example.json"
    example_path.write_text('{"offline_mode": true, "model": {"path": "models/demo"}}', encoding="utf-8")

    config, resolved_path, used_example, runtime_root = load_runtime_config(tmp_path, working_dir=tmp_path)

    assert resolved_path == example_path
    assert used_example is True
    assert config["offline_mode"] is True
    assert runtime_root == tmp_path


def test_resolve_runtime_root_uses_working_directory_for_installed_config(tmp_path):
    project_root = tmp_path / "project"
    working_dir = tmp_path / "workspace"
    install_data_root = tmp_path / "venv"
    install_config_dir = install_data_root / "config"
    install_config_dir.mkdir(parents=True)
    config_path = install_config_dir / "settings.example.json"
    config_path.write_text('{"offline_mode": true}', encoding="utf-8")

    with patch("voice_entry.get_install_config_dir", return_value=install_config_dir):
        runtime_root = resolve_runtime_root(config_path, project_root, working_dir=working_dir)

    assert runtime_root == working_dir


def test_load_runtime_config_reads_installed_settings_json(tmp_path):
    project_root = tmp_path / "project"
    working_dir = tmp_path / "workspace"
    install_data_root = tmp_path / "venv"
    install_config_dir = install_data_root / "config"
    install_config_dir.mkdir(parents=True)
    settings_path = install_config_dir / "settings.json"
    settings_path.write_text('{"offline_mode": true, "model": {"path": "models/demo"}}', encoding="utf-8")

    with patch("voice_entry.get_install_config_dir", return_value=install_config_dir):
        config, resolved_path, used_example, runtime_root = load_runtime_config(
            project_root,
            working_dir=working_dir,
        )

    assert resolved_path == settings_path
    assert used_example is False
    assert config["offline_mode"] is True
    assert runtime_root == working_dir
