"""CLI entrypoint for the packaged voice command."""

import logging
import sysconfig
from pathlib import Path

from app_factory import build_runtime, load_config
from bootstrap import apply_offline_env, build_preload_failure_details, preload_model_or_exit
from cli import CLI, copy_to_clipboard
from recording_session import (
    run_streaming_inference,
    should_trigger_preview,
    transcribe_recording,
)
from loading_status import format_loading_status
from runtime_ui import (
    format_idle_preview,
    format_interim_text_block,
    format_recording_header,
    get_audio_volume_bar,
)
from usage_stats import UsageStatsStore


SOURCE_ROOT = Path(__file__).resolve().parent.parent


def get_install_config_dir() -> Path:
    """返回随安装分发的配置目录。"""
    return Path(sysconfig.get_path("data")) / "config"


def _is_relative_to(path: Path, parent: Path) -> bool:
    """兼容 Python 3.10 的 Path 归属判断。"""
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def resolve_config_path(project_root: Path, working_dir: Path | None = None) -> tuple[Path, bool]:
    """解析运行时配置路径，优先使用本地 settings.json。"""
    working_dir = working_dir or Path.cwd()
    install_config_dir = get_install_config_dir()

    primary_candidates = [
        working_dir / "config" / "settings.json",
        project_root / "config" / "settings.json",
        install_config_dir / "settings.json",
    ]
    for primary_path in primary_candidates:
        if primary_path.exists():
            return primary_path, False

    fallback_candidates = [
        working_dir / "config" / "settings.example.json",
        project_root / "config" / "settings.example.json",
        install_config_dir / "settings.example.json",
    ]
    for fallback_path in fallback_candidates:
        if fallback_path.exists():
            return fallback_path, True

    return primary_candidates[0], False


def resolve_runtime_root(config_path: Path, project_root: Path, working_dir: Path | None = None) -> Path:
    """解析模型、日志和临时文件所使用的运行时根目录。"""
    working_dir = working_dir or Path.cwd()
    install_config_dir = get_install_config_dir()

    if _is_relative_to(config_path, install_config_dir):
        return working_dir

    if config_path.parent.name == "config":
        return config_path.parent.parent

    return project_root


def load_runtime_config(project_root: Path, working_dir: Path | None = None) -> tuple[dict, Path, bool, Path]:
    """加载运行时配置，并返回运行时根目录。"""
    config_path, used_example = resolve_config_path(project_root, working_dir=working_dir)
    runtime_root = resolve_runtime_root(config_path, project_root, working_dir=working_dir)
    return load_config(config_path), config_path, used_example, runtime_root


def get_usage_stats_path(config: dict, runtime_root: Path) -> Path:
    """统计文件默认写入日志目录。"""
    logging_config = config.get("logging", {})
    log_file = Path(logging_config.get("file", "logs/voice_input.log"))
    if not log_file.is_absolute():
        log_file = runtime_root / log_file
    return log_file.parent / "usage_stats.json"


_config_path, _used_example_config = resolve_config_path(SOURCE_ROOT)
if _config_path.exists():
    _early_config = load_config(_config_path)
    apply_offline_env(_early_config)


def setup_logging(config: dict, project_root: Path):
    """配置日志。"""
    log_config = config.get("logging", {})
    log_file = project_root / log_config.get("file", "logs/voice_input.log")
    console_enabled = log_config.get("console", False)

    log_file.parent.mkdir(parents=True, exist_ok=True)

    handlers = [logging.FileHandler(log_file, encoding="utf-8")]
    if console_enabled:
        handlers.append(logging.StreamHandler())

    logging.basicConfig(
        level=getattr(logging, log_config.get("level", "INFO")),
        format=log_config.get("format", "%(asctime)s - %(name)s - %(levelname)s - %(message)s"),
        handlers=handlers,
    )


def main():
    """主函数。"""
    config, config_path, used_example_config, runtime_root = load_runtime_config(SOURCE_ROOT)
    apply_offline_env(config)

    if used_example_config:
        print(
            f"未找到 config/settings.json，正在使用示例配置: {config_path}。"
            " 如需自定义，请复制为 config/settings.json 后再启动。"
        )

    setup_logging(config, runtime_root)
    logger = logging.getLogger(__name__)
    logger.info("启动语音输入工具")
    supported_languages = config["model"]["supported_languages"]
    usage_stats_store = UsageStatsStore(get_usage_stats_path(config, runtime_root))

    interim_text = ""
    last_inference_time = 0
    import threading
    stream_inference_lock = threading.Lock()

    def render_recording_status():
        """渲染录音中的动态UI。"""
        import sys
        import time

        nonlocal interim_text, last_inference_time

        while cli.is_recording:
            vol = recorder.current_volume
            bar = get_audio_volume_bar(vol)
            dot = "🔴" if int(time.time() * 2) % 2 == 0 else "⭕"

            current_time = time.time()
            if should_trigger_preview(current_time, last_inference_time):
                audio_data = recorder.get_current_audio()
                if audio_data is not None and len(audio_data) > 0:
                    try:
                        if stream_inference_lock.acquire(blocking=False):

                            def _do_inference(data):
                                nonlocal interim_text
                                try:
                                    text = run_streaming_inference(
                                        data,
                                        processor=processor,
                                        asr_engine=asr_engine,
                                        temp_audio_path=temp_audio_path,
                                        language=cli.get_current_language(),
                                    )
                                    if text:
                                        interim_text = text
                                except Exception:
                                    pass
                                finally:
                                    stream_inference_lock.release()

                            threading.Thread(target=_do_inference, args=(audio_data,), daemon=True).start()
                    except Exception:
                        pass
                last_inference_time = current_time

            display_text = format_recording_header(dot, cli.get_current_language(), bar)

            if interim_text:
                sys.stdout.write(display_text + format_interim_text_block(interim_text))
            else:
                sys.stdout.write(display_text + format_idle_preview(cli.get_current_language()))

            sys.stdout.flush()
            time.sleep(0.05)

        sys.stdout.write("\r\033[K\033[?25h")
        sys.stdout.flush()

    def on_record_toggle():
        """录音切换回调。"""
        import sys
        import threading
        import time

        nonlocal interim_text, last_inference_time

        if not cli.is_recording:
            interim_text = ""
            last_inference_time = time.time()
            try:
                recorder.start_recording()
            except Exception as e:
                logger.error(f"启动录音失败: {e}")
                cli.show_result(f"启动录音失败：{e}", is_success=False)
                return

            cli.is_recording = True
            sys.stdout.write("\033[?25l")
            sys.stdout.flush()
            threading.Thread(target=render_recording_status, daemon=True).start()

        else:
            cli.is_recording = False
            sys.stdout.write("\033[?25h\r\033[K")
            sys.stdout.flush()

            cli.is_processing = True
            audio_data = recorder.stop_recording()

            if audio_data is not None:
                with cli.show_loading("语音引擎疯狂计算中..."):
                    text = transcribe_recording(
                        audio_data,
                        processor=processor,
                        asr_engine=asr_engine,
                        temp_audio_path=temp_audio_path,
                        language=cli.get_current_language(),
                    )

                if text:
                    if copy_to_clipboard(text):
                        snapshot = usage_stats_store.record_input(len(text.replace("\n", "")))
                        cli.show_result(
                            text,
                            status_note="已复制到剪贴板",
                            status_details=[
                                f"本次：{len(text.replace('\n', ''))}",
                                f"今日：{snapshot.today_chars}",
                                f"累计：{snapshot.total_chars}",
                            ],
                        )
                    else:
                        cli.show_result(text)
                else:
                    cli.show_result("未能识别出任何内容，请靠近麦克风重试。", is_success=False)
            else:
                cli.show_result("录音失败或没有声音数据。", is_success=False)

            cli.is_processing = False

    def on_language_switch():
        """语言切换回调。"""
        new_lang = cli.switch_language()
        logger.info(f"切换语言: {new_lang}")
        return new_lang

    cli = CLI(
        on_record_toggle=on_record_toggle,
        on_language_switch=on_language_switch,
        supported_languages=supported_languages,
    )

    with cli.show_loading("正在准备运行时...") as update_loading:
        update_loading(format_loading_status(1, 4, "正在初始化运行时组件..."))
        recorder, processor, asr_engine, temp_audio_path, supported_languages = build_runtime(
            config,
            runtime_root,
            status_callback=lambda text: update_loading(format_loading_status(1, 4, text)),
        )
        preload_model_or_exit(
            asr_engine.preload,
            logger,
            status_callback=update_loading,
            failure_details=build_preload_failure_details(
                offline_mode=config.get("offline_mode", False),
                model_path=asr_engine.model_path,
                vad_model_path=asr_engine.vad_model_path,
                use_vad=asr_engine.use_vad,
                last_error=asr_engine.last_error,
            ),
        )

    cli.supported_languages = supported_languages

    try:
        cli.run()
    except KeyboardInterrupt:
        print("\n程序已终止")
    finally:
        logger.info("程序结束")
