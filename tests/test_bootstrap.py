import os
from unittest.mock import Mock, patch

from bootstrap import apply_offline_env, build_preload_failure_details, preload_model_or_exit


def test_apply_offline_env_sets_expected_variables():
    with patch.dict(os.environ, {}, clear=True):
        apply_offline_env({"offline_mode": True})

        assert os.environ["MODELSCOPE_OFFLINE"] == "1"
        assert os.environ["HF_HUB_OFFLINE"] == "1"


def test_apply_offline_env_keeps_environment_unchanged_when_disabled():
    with patch.dict(os.environ, {}, clear=True):
        apply_offline_env({"offline_mode": False})

        assert "MODELSCOPE_OFFLINE" not in os.environ
        assert "HF_HUB_OFFLINE" not in os.environ


def test_preload_model_or_exit_returns_on_success():
    logger = Mock()
    status_callback = Mock()

    preload_model_or_exit(lambda **kwargs: True, logger, status_callback=status_callback)

    logger.info.assert_called_once()
    logger.error.assert_not_called()
    status_callback.assert_called_with("正在预加载模型...")


def test_preload_model_or_exit_exits_on_failure():
    logger = Mock()
    status_callback = Mock()

    with patch("builtins.print") as print_mock, patch("bootstrap.sys.exit", side_effect=SystemExit(1)) as exit_mock:
        try:
            preload_model_or_exit(
                lambda **kwargs: False,
                logger,
                status_callback=status_callback,
                failure_details=["detail-a", "detail-b"],
            )
        except SystemExit as exc:
            assert exc.code == 1
        else:
            raise AssertionError("Expected preload_model_or_exit to exit")

    logger.error.assert_called_once()
    assert print_mock.call_count == 3
    exit_mock.assert_called_once_with(1)
    status_callback.assert_called_with("正在预加载模型...")


def test_build_preload_failure_details_reports_path_existence(tmp_path):
    asr_path = tmp_path / "asr"
    vad_path = tmp_path / "vad"
    asr_path.mkdir()

    details = build_preload_failure_details(
        offline_mode=True,
        model_path=asr_path,
        vad_model_path=vad_path,
        use_vad=True,
        last_error="No module named 'transformers'",
    )

    assert "当前离线模式: 开启" in details
    assert any("ASR 模型路径:" in detail and "存在" in detail for detail in details)
    assert any("VAD 模型路径:" in detail and "不存在" in detail for detail in details)
    assert any("最后错误: No module named 'transformers'" == detail for detail in details)
    assert any("离线模式下不会自动下载模型" in detail for detail in details)
