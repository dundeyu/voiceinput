import os
from unittest.mock import Mock, patch

from bootstrap import apply_offline_env, preload_model_or_exit


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
            preload_model_or_exit(lambda **kwargs: False, logger, status_callback=status_callback)
        except SystemExit as exc:
            assert exc.code == 1
        else:
            raise AssertionError("Expected preload_model_or_exit to exit")

    logger.error.assert_called_once()
    print_mock.assert_called_once()
    exit_mock.assert_called_once_with(1)
    status_callback.assert_called_with("正在预加载模型...")
