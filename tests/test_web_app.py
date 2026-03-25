import json
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
import soundfile as sf

from web_app import (
    ADMIN_COOKIE_NAME,
    WebRecognitionRuntime,
    WebServerOptions,
    build_admin_config_html,
    build_admin_login_html,
    build_arg_parser,
    build_web_page_html,
    decode_wav_bytes,
    get_lan_addresses,
    resolve_web_server_options,
    resolve_service_path,
)
from vocabulary_suggestion_store import VocabularySuggestionStore


def test_build_web_page_html_contains_recording_controls():
    html = build_web_page_html()

    assert "开始录音" in html
    assert "结束录音" in html
    assert "/api/transcribe" in html
    assert "/api/preview" in html
    assert "/api/suggestions" in html
    assert "实时预览" in html
    assert "词汇修正建议" in html
    assert "X-Voice-Session" in html
    assert "voiceinput.web.session_id" in html
    assert "空格开始 / 空格结束" in html
    assert "结束后自动复制到剪贴板" in html
    assert "navigator.clipboard.writeText" in html
    assert "备注（可选）" not in html
    assert "#preview" in html
    assert "min-height: 96px;" in html
    assert "管理员入口" in html
    assert "/api/config" not in html


def test_build_admin_pages_include_login_and_config_controls():
    login_html = build_admin_login_html()
    config_html = build_admin_config_html()

    assert "管理员登录" in login_html
    assert "/api/admin/login" in login_html
    assert "width: min(280px, 100%)" in login_html
    assert "管理员配置" in config_html
    assert "/api/config" in config_html
    assert "退出管理员" in config_html
    assert 'id="backToVoiceBtn"' in config_html
    assert "替换词汇配置" in config_html
    assert "错误词=正确词" in config_html
    assert "语气词配置" in config_html
    assert "词汇修正建议" in config_html
    assert "data-action=\"accept\"" in config_html
    assert "data-action=\"delete\"" in config_html
    assert "width: min(720px, 100%)" in config_html
    assert "minmax(150px, 1fr)" in config_html
    assert "repeat(2, minmax(0, 1fr))" in config_html
    assert "minmax(0, 1.3fr)" in config_html
    assert "box-sizing: border-box" in config_html
    assert "@media (max-width: 900px)" in config_html
    assert '<select id="configWebHost">' in config_html
    assert "127.0.0.1（只服务本机）" in config_html
    assert "0.0.0.0（服务局域网）" in config_html
    assert "window.location.reload()" in config_html


def test_decode_wav_bytes_reads_audio_and_sample_rate():
    buffer = BytesIO()
    original = np.array([0.0, 0.2, -0.2, 0.1], dtype=np.float32)
    sf.write(buffer, original, 16000, format="WAV", subtype="PCM_16")

    audio_data, sample_rate = decode_wav_bytes(buffer.getvalue())

    assert sample_rate == 16000
    assert len(audio_data) == len(original)


def test_web_runtime_transcribe_wav_bytes_uses_serialized_pipeline(tmp_path):
    config = {
        "audio": {
            "input_sample_rate": 48000,
            "target_sample_rate": 16000,
            "channels": 1,
            "dtype": "float32",
        },
        "model": {
            "path": "",
            "device": "",
            "default_language": "中文",
            "supported_languages": ["中文", "英文"],
        },
        "temp": {
            "audio_dir": "temp",
            "audio_filename": "recording.wav",
        },
        "logging": {
            "level": "INFO",
            "format": "%(message)s",
            "file": "logs/voice_input.log",
            "console": False,
        },
        "vad_model_path": "",
        "offline_mode": False,
    }
    recorder = Mock()
    processor = Mock()
    asr_engine = Mock()
    asr_engine.model_path = "model"
    asr_engine.vad_model_path = None
    asr_engine.use_vad = True
    asr_engine.last_error = None

    buffer = BytesIO()
    sf.write(buffer, np.array([0.0, 0.1, -0.1], dtype=np.float32), 16000, format="WAV", subtype="PCM_16")

    with patch("web_app.load_runtime_config", return_value=(config, tmp_path / "config/settings.yaml", False, tmp_path)), patch(
        "web_app.apply_offline_env"
    ), patch("web_app.setup_logging"), patch(
        "web_app.build_runtime",
        return_value=(recorder, processor, asr_engine, tmp_path / "temp/recording.wav", ["中文"]),
    ), patch("web_app.preload_model_or_exit"), patch(
        "web_app.transcribe_recording_serialized",
        return_value="网页识别结果",
    ) as transcribe_mock:
        runtime = WebRecognitionRuntime(Path("/project"))
        result = runtime.transcribe_wav_bytes(buffer.getvalue())

    assert result["text"] == "网页识别结果"
    assert result["language"] == "中文"
    assert result["char_count"] == len("网页识别结果")
    transcribe_mock.assert_called_once()


def test_web_runtime_preview_wav_bytes_uses_stream_audio_path(tmp_path):
    config = {
        "audio": {
            "input_sample_rate": 48000,
            "target_sample_rate": 16000,
            "channels": 1,
            "dtype": "float32",
        },
        "model": {
            "path": "",
            "device": "",
            "default_language": "中文",
            "supported_languages": ["中文", "英文"],
        },
        "temp": {
            "audio_dir": "temp",
            "audio_filename": "recording.wav",
        },
        "logging": {
            "level": "INFO",
            "format": "%(message)s",
            "file": "logs/voice_input.log",
            "console": False,
        },
        "vad_model_path": "",
        "offline_mode": False,
    }
    recorder = Mock()
    processor = Mock()
    processor.process.return_value = np.array([0.0, 0.1, -0.1], dtype=np.float32)
    asr_engine = Mock()
    asr_engine.model_path = "model"
    asr_engine.vad_model_path = None
    asr_engine.use_vad = True
    asr_engine.last_error = None

    buffer = BytesIO()
    sf.write(buffer, np.array([0.0, 0.1, -0.1], dtype=np.float32), 16000, format="WAV", subtype="PCM_16")

    with patch("web_app.load_runtime_config", return_value=(config, tmp_path / "config/settings.yaml", False, tmp_path)), patch(
        "web_app.apply_offline_env"
    ), patch("web_app.setup_logging"), patch(
        "web_app.build_runtime",
        return_value=(recorder, processor, asr_engine, tmp_path / "temp/recording.wav", ["中文"]),
    ), patch("web_app.preload_model_or_exit"), patch(
        "web_app.transcribe_stream_audio_path",
        return_value="实时预览结果",
    ) as preview_mock:
        runtime = WebRecognitionRuntime(Path("/project"))
        result = runtime.preview_wav_bytes(buffer.getvalue())

    assert result["text"] == "实时预览结果"
    assert result["char_count"] == len("实时预览结果")
    preview_mock.assert_called_once()
    assert preview_mock.call_args.args[0] == tmp_path / "temp/web_sessions/default/stream_recording.wav"


def test_web_runtime_preview_wav_bytes_isolates_stream_audio_path_by_session(tmp_path):
    config = {
        "audio": {
            "input_sample_rate": 48000,
            "target_sample_rate": 16000,
            "channels": 1,
            "dtype": "float32",
        },
        "model": {
            "path": "",
            "device": "",
            "default_language": "中文",
            "supported_languages": ["中文", "英文"],
        },
        "temp": {
            "audio_dir": "temp",
            "audio_filename": "recording.wav",
        },
        "logging": {
            "level": "INFO",
            "format": "%(message)s",
            "file": "logs/voice_input.log",
            "console": False,
        },
        "vad_model_path": "",
        "offline_mode": False,
    }
    recorder = Mock()
    processor = Mock()
    processor.process.return_value = np.array([0.0, 0.1, -0.1], dtype=np.float32)
    asr_engine = Mock()
    asr_engine.model_path = "model"
    asr_engine.vad_model_path = None
    asr_engine.use_vad = True
    asr_engine.last_error = None

    buffer = BytesIO()
    sf.write(buffer, np.array([0.0, 0.1, -0.1], dtype=np.float32), 16000, format="WAV", subtype="PCM_16")

    with patch("web_app.load_runtime_config", return_value=(config, tmp_path / "config/settings.yaml", False, tmp_path)), patch(
        "web_app.apply_offline_env"
    ), patch("web_app.setup_logging"), patch(
        "web_app.build_runtime",
        return_value=(recorder, processor, asr_engine, tmp_path / "temp/recording.wav", ["中文"]),
    ), patch("web_app.preload_model_or_exit"), patch(
        "web_app.transcribe_stream_audio_path",
        side_effect=["session-a", "session-b"],
    ) as preview_mock:
        runtime = WebRecognitionRuntime(Path("/project"))
        runtime.preview_wav_bytes(buffer.getvalue(), session_id="alpha")
        runtime.preview_wav_bytes(buffer.getvalue(), session_id="beta")

    first_path = preview_mock.call_args_list[0].args[0]
    second_path = preview_mock.call_args_list[1].args[0]
    assert first_path == tmp_path / "temp/web_sessions/alpha/stream_recording.wav"
    assert second_path == tmp_path / "temp/web_sessions/beta/stream_recording.wav"
    assert first_path != second_path


def test_web_runtime_records_vocabulary_suggestions_to_local_jsonl(tmp_path):
    config = {
        "audio": {
            "input_sample_rate": 48000,
            "target_sample_rate": 16000,
            "channels": 1,
            "dtype": "float32",
        },
        "model": {
            "path": "",
            "device": "",
            "default_language": "中文",
            "supported_languages": ["中文", "英文"],
        },
        "temp": {
            "audio_dir": "temp",
            "audio_filename": "recording.wav",
        },
        "logging": {
            "level": "INFO",
            "format": "%(message)s",
            "file": "logs/voice_input.log",
            "console": False,
        },
        "vad_model_path": "",
        "offline_mode": False,
    }
    recorder = Mock()
    processor = Mock()
    asr_engine = Mock()
    asr_engine.model_path = "model"
    asr_engine.vad_model_path = None
    asr_engine.use_vad = True
    asr_engine.last_error = None

    with patch("web_app.load_runtime_config", return_value=(config, tmp_path / "config/settings.yaml", False, tmp_path)), patch(
        "web_app.apply_offline_env"
    ), patch("web_app.setup_logging"), patch(
        "web_app.build_runtime",
        return_value=(recorder, processor, asr_engine, tmp_path / "temp/recording.wav", ["中文"]),
    ), patch("web_app.preload_model_or_exit"):
        runtime = WebRecognitionRuntime(Path("/project"))
        result = runtime.record_vocabulary_suggestion(
            wrong_text="open cloud",
            suggested_text="claude code",
        )

    suggestions_path = tmp_path / "logs/vocabulary_suggestions.jsonl"
    assert result["ok"] is True
    assert result["storage_path"] == "logs/vocabulary_suggestions.jsonl"
    assert suggestions_path.exists()

    saved_lines = suggestions_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(saved_lines) == 1
    saved_payload = json.loads(saved_lines[0])
    assert saved_payload["wrong_text"] == "open cloud"
    assert saved_payload["suggested_text"] == "claude code"
    assert saved_payload["note"] == ""
    assert saved_payload["created_at"]


def test_web_runtime_get_config_payload_returns_editable_fields(tmp_path):
    config = {
        "offline_mode": False,
        "vad_model_path": "",
        "model": {
            "path": "",
            "device": "",
            "default_language": "中文",
            "supported_languages": ["中文", "英文"],
        },
        "audio": {
            "input_sample_rate": 48000,
            "target_sample_rate": 16000,
            "channels": 1,
            "dtype": "float32",
        },
        "logging": {
            "level": "INFO",
            "format": "%(message)s",
            "file": "logs/voice_input.log",
            "console": False,
        },
        "temp": {
            "audio_dir": "temp",
            "audio_filename": "recording.wav",
        },
        "web": {
            "host": "0.0.0.0",
            "port": 9000,
            "workers": 2,
            "daemon": True,
        },
        "filler_words": ["呃", "嗯", "这个"],
        "vocabulary_corrections": {
            "open cloud": "claude code",
            "cloud code": "claude code",
        },
    }
    recorder = Mock()
    processor = Mock()
    asr_engine = Mock(model_path="model", vad_model_path=None, use_vad=True, last_error=None)
    suggestions_path = tmp_path / "logs/vocabulary_suggestions.jsonl"
    suggestion_store = VocabularySuggestionStore(suggestions_path)
    suggestion_store.record("open cloud", "claude code")
    suggestion_store.record("cloud code", "claude code")

    with patch("web_app.load_runtime_config", return_value=(config, tmp_path / "config/settings.yaml", False, tmp_path)), patch(
        "web_app.apply_offline_env"
    ), patch("web_app.setup_logging"), patch(
        "web_app.build_runtime",
        return_value=(recorder, processor, asr_engine, tmp_path / "temp/recording.wav", ["中文"]),
    ), patch("web_app.preload_model_or_exit"):
        runtime = WebRecognitionRuntime(Path("/project"))
        payload = runtime.get_config_payload()

    assert payload["config_path"] == "config/settings.yaml"
    assert payload["runtime"]["default_language"] == "中文"
    assert payload["runtime"]["device"] == ""
    assert payload["runtime"]["offline_mode"] is False
    assert payload["web"] == {"host": "0.0.0.0", "port": 9000, "workers": 2, "daemon": True}
    assert payload["filler_words"] == ["呃", "嗯", "这个"]
    assert payload["vocabulary_corrections"] == {
        "open cloud": "claude code",
        "cloud code": "claude code",
    }
    assert payload["suggestion_inbox"]["path"] == "logs/vocabulary_suggestions.jsonl"
    assert len(payload["suggestion_inbox"]["items"]) == 2
    assert payload["suggestion_inbox"]["items"][0]["wrong_text"] == "cloud code"


def test_web_runtime_admin_authentication_uses_generated_cookie(tmp_path):
    config = {
        "offline_mode": False,
        "vad_model_path": "",
        "model": {
            "path": "",
            "device": "",
            "default_language": "中文",
            "supported_languages": ["中文", "英文"],
        },
        "audio": {
            "input_sample_rate": 48000,
            "target_sample_rate": 16000,
            "channels": 1,
            "dtype": "float32",
        },
        "logging": {
            "level": "INFO",
            "format": "%(message)s",
            "file": "logs/voice_input.log",
            "console": False,
        },
        "temp": {
            "audio_dir": "temp",
            "audio_filename": "recording.wav",
        },
    }
    recorder = Mock()
    processor = Mock()
    asr_engine = Mock(model_path="model", vad_model_path=None, use_vad=True, last_error=None)

    with patch("web_app.load_runtime_config", return_value=(config, tmp_path / "config/settings.yaml", False, tmp_path)), patch(
        "web_app.apply_offline_env"
    ), patch("web_app.setup_logging"), patch(
        "web_app.build_runtime",
        return_value=(recorder, processor, asr_engine, tmp_path / "temp/recording.wav", ["中文"]),
    ), patch("web_app.preload_model_or_exit"):
        runtime = WebRecognitionRuntime(Path("/project"))

    cookie = runtime.get_admin_cookie_value()
    assert runtime.verify_admin_password("voice8765") is True
    assert runtime.verify_admin_password("wrong") is False
    assert f"{ADMIN_COOKIE_NAME}=" in cookie
    assert runtime.is_admin_authenticated(cookie) is True
    assert runtime.is_admin_authenticated(None) is False
    assert runtime.is_admin_authenticated(f"{ADMIN_COOKIE_NAME}=bad-token") is False


def test_web_runtime_update_config_persists_settings_yaml(tmp_path):
    config = {
        "offline_mode": False,
        "vad_model_path": "",
        "model": {
            "path": "",
            "device": "",
            "default_language": "中文",
            "supported_languages": ["中文", "英文"],
        },
        "audio": {
            "input_sample_rate": 48000,
            "target_sample_rate": 16000,
            "channels": 1,
            "dtype": "float32",
        },
        "logging": {
            "level": "INFO",
            "format": "%(message)s",
            "file": "logs/voice_input.log",
            "console": False,
        },
        "temp": {
            "audio_dir": "temp",
            "audio_filename": "recording.wav",
        },
        "filler_words": ["呃"],
        "vocabulary_corrections": {},
    }
    recorder = Mock()
    processor = Mock()
    asr_engine = Mock(model_path="model", vad_model_path=None, use_vad=True, last_error=None)

    with patch("web_app.load_runtime_config", return_value=(config, tmp_path / "config/settings.example.yaml", True, tmp_path)), patch(
        "web_app.apply_offline_env"
    ), patch("web_app.setup_logging"), patch(
        "web_app.build_runtime",
        return_value=(recorder, processor, asr_engine, tmp_path / "temp/recording.wav", ["中文"]),
    ), patch("web_app.preload_model_or_exit"):
        runtime = WebRecognitionRuntime(Path("/project"))
        result = runtime.update_config(
            {
                "offline_mode": True,
                "model": {
                    "default_language": "英文",
                    "device": "mps",
                },
                "web": {
                    "host": "0.0.0.0",
                    "port": 9001,
                    "workers": 3,
                    "daemon": True,
                },
                "filler_words": "呃\n嗯\n这个",
                "vocabulary_corrections": "open cloud=claude code\ncloud code=claude code",
            }
        )

    persisted_path = tmp_path / "config/settings.yaml"
    assert result["config_path"] == "config/settings.yaml"
    assert persisted_path.exists()

    saved_text = persisted_path.read_text(encoding="utf-8")
    assert 'offline_mode: true' in saved_text
    assert 'default_language: "\\u82f1\\u6587"' not in saved_text
    assert 'default_language: 英文' in saved_text
    assert 'device: mps' in saved_text
    assert 'host: 0.0.0.0' in saved_text
    assert 'port: 9001' in saved_text
    assert 'workers: 3' in saved_text
    assert 'daemon: true' in saved_text
    assert '- 呃' in saved_text
    assert '- 嗯' in saved_text
    assert '- 这个' in saved_text
    assert 'open cloud: claude code' in saved_text
    assert 'cloud code: claude code' in saved_text


def test_web_runtime_accept_vocabulary_suggestion_updates_config_and_removes_it(tmp_path):
    config = {
        "offline_mode": False,
        "vad_model_path": "",
        "model": {
            "path": "",
            "device": "",
            "default_language": "中文",
            "supported_languages": ["中文", "英文"],
        },
        "audio": {
            "input_sample_rate": 48000,
            "target_sample_rate": 16000,
            "channels": 1,
            "dtype": "float32",
        },
        "logging": {
            "level": "INFO",
            "format": "%(message)s",
            "file": "logs/voice_input.log",
            "console": False,
        },
        "temp": {
            "audio_dir": "temp",
            "audio_filename": "recording.wav",
        },
        "filler_words": [],
        "vocabulary_corrections": {},
    }
    recorder = Mock()
    processor = Mock()
    asr_engine = Mock(model_path="model", vad_model_path=None, use_vad=True, last_error=None)

    with patch("web_app.load_runtime_config", return_value=(config, tmp_path / "config/settings.yaml", False, tmp_path)), patch(
        "web_app.apply_offline_env"
    ), patch("web_app.setup_logging"), patch(
        "web_app.build_runtime",
        return_value=(recorder, processor, asr_engine, tmp_path / "temp/recording.wav", ["中文"]),
    ), patch("web_app.preload_model_or_exit"):
        runtime = WebRecognitionRuntime(Path("/project"))
        suggestion = runtime.suggestion_store.record("open cloud", "claude code")
        result = runtime.accept_vocabulary_suggestion("open cloud", "claude code", suggestion.created_at)

    assert result["vocabulary_corrections"]["open cloud"] == "claude code"
    assert result["suggestion_inbox"]["items"] == []
    saved_text = (tmp_path / "config/settings.yaml").read_text(encoding="utf-8")
    assert "open cloud: claude code" in saved_text


def test_web_runtime_delete_vocabulary_suggestion_removes_it(tmp_path):
    config = {
        "offline_mode": False,
        "vad_model_path": "",
        "model": {
            "path": "",
            "device": "",
            "default_language": "中文",
            "supported_languages": ["中文", "英文"],
        },
        "audio": {
            "input_sample_rate": 48000,
            "target_sample_rate": 16000,
            "channels": 1,
            "dtype": "float32",
        },
        "logging": {
            "level": "INFO",
            "format": "%(message)s",
            "file": "logs/voice_input.log",
            "console": False,
        },
        "temp": {
            "audio_dir": "temp",
            "audio_filename": "recording.wav",
        },
        "filler_words": [],
        "vocabulary_corrections": {},
    }
    recorder = Mock()
    processor = Mock()
    asr_engine = Mock(model_path="model", vad_model_path=None, use_vad=True, last_error=None)

    with patch("web_app.load_runtime_config", return_value=(config, tmp_path / "config/settings.yaml", False, tmp_path)), patch(
        "web_app.apply_offline_env"
    ), patch("web_app.setup_logging"), patch(
        "web_app.build_runtime",
        return_value=(recorder, processor, asr_engine, tmp_path / "temp/recording.wav", ["中文"]),
    ), patch("web_app.preload_model_or_exit"):
        runtime = WebRecognitionRuntime(Path("/project"))
        suggestion = runtime.suggestion_store.record("cloud code", "claude code")
        result = runtime.delete_vocabulary_suggestion("cloud code", "claude code", suggestion.created_at)

    assert result["suggestion_inbox"]["items"] == []


def test_web_runtime_initializes_multiple_workers(tmp_path):
    config = {
        "audio": {
            "input_sample_rate": 48000,
            "target_sample_rate": 16000,
            "channels": 1,
            "dtype": "float32",
        },
        "model": {
            "path": "",
            "device": "",
            "default_language": "中文",
            "supported_languages": ["中文", "英文"],
        },
        "temp": {
            "audio_dir": "temp",
            "audio_filename": "recording.wav",
        },
        "logging": {
            "level": "INFO",
            "format": "%(message)s",
            "file": "logs/voice_input.log",
            "console": False,
        },
        "vad_model_path": "",
        "offline_mode": False,
    }

    runtime_triplets = [
        (Mock(), Mock(), Mock(model_path="model-a", vad_model_path=None, use_vad=True, last_error=None), tmp_path / "temp/recording.wav", ["中文"]),
        (Mock(), Mock(), Mock(model_path="model-b", vad_model_path=None, use_vad=True, last_error=None), tmp_path / "temp/recording.wav", ["中文"]),
    ]

    with patch("web_app.load_runtime_config", return_value=(config, tmp_path / "config/settings.yaml", False, tmp_path)), patch(
        "web_app.apply_offline_env"
    ), patch("web_app.setup_logging"), patch(
        "web_app.build_runtime",
        side_effect=runtime_triplets,
    ) as build_runtime_mock, patch("web_app.preload_model_or_exit") as preload_mock:
        runtime = WebRecognitionRuntime(Path("/project"), worker_count=2)

    assert runtime.worker_count == 2
    assert len(runtime.workers) == 2
    assert [worker.worker_id for worker in runtime.workers] == [0, 1]
    assert build_runtime_mock.call_count == 2
    assert preload_mock.call_count == 2


def test_build_arg_parser_supports_workers_option():
    parser = build_arg_parser()

    args = parser.parse_args(
        [
            "--host",
            "0.0.0.0",
            "--port",
            "9000",
            "--workers",
            "3",
            "--daemon",
            "--pid-file",
            "tmp/voice-web.pid",
        ]
    )

    assert args.host == "0.0.0.0"
    assert args.port == 9000
    assert args.workers == 3
    assert args.daemon is True
    assert args.pid_file == "tmp/voice-web.pid"


def test_resolve_web_server_options_prefers_config_defaults():
    config = {
        "web": {
            "host": "0.0.0.0",
            "port": 9988,
            "workers": 3,
            "daemon": True,
        }
    }
    parser = build_arg_parser()
    args = parser.parse_args([])

    resolved = resolve_web_server_options(config, args)

    assert resolved == WebServerOptions(host="0.0.0.0", port=9988, workers=3, daemon=True)


def test_resolve_web_server_options_allows_cli_override():
    config = {
        "web": {
            "host": "0.0.0.0",
            "port": 9988,
            "workers": 3,
            "daemon": False,
        }
    }
    parser = build_arg_parser()
    args = parser.parse_args(["--host", "127.0.0.1", "--port", "8765", "--workers", "1", "--daemon"])

    resolved = resolve_web_server_options(config, args)

    assert resolved == WebServerOptions(host="127.0.0.1", port=8765, workers=1, daemon=True)


def test_get_lan_addresses_filters_loopback(monkeypatch):
    monkeypatch.setattr("web_app.socket.gethostname", lambda: "machine")
    monkeypatch.setattr("web_app.socket.getfqdn", lambda: "machine.local")

    def fake_gethostbyname_ex(hostname):
        if hostname == "localhost":
            return ("localhost", [], ["127.0.0.1"])
        return (hostname, [], ["127.0.0.1", "192.168.1.23"])

    monkeypatch.setattr("web_app.socket.gethostbyname_ex", fake_gethostbyname_ex)

    class FakeSocket:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def connect(self, addr):
            return None

        def getsockname(self):
            return ("10.0.0.8", 54321)

    monkeypatch.setattr("web_app.socket.socket", lambda *args, **kwargs: FakeSocket())

    addresses = get_lan_addresses()

    assert addresses == ["10.0.0.8", "192.168.1.23"]


def test_resolve_service_path_uses_project_root_for_relative_path(tmp_path):
    resolved = resolve_service_path(tmp_path, "logs/custom.pid", "logs/voice-web.pid")

    assert resolved == tmp_path / "logs/custom.pid"


def test_resolve_service_path_uses_default_when_path_empty(tmp_path):
    resolved = resolve_service_path(tmp_path, "", "logs/voice-web.pid")

    assert resolved == tmp_path / "logs/voice-web.pid"
