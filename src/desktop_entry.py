"""macOS 桌面全局热键入口：Option+Space 开始/结束录音。"""

from __future__ import annotations

import logging
import subprocess
import sys
import threading
import time

from app_factory import build_runtime
from bootstrap import build_preload_failure_details, preload_model_or_exit
from desktop_hotkey import GlobalHotkeyListener
from desktop_preview import DesktopPreviewOverlay
from recording_session import (
    run_streaming_inference,
    should_trigger_preview,
    transcribe_recording_serialized,
)
from loading_status import format_loading_status
from usage_stats import UsageStatsStore
from voice_entry import SOURCE_ROOT, get_usage_stats_path, load_runtime_config, setup_logging


class DesktopVoiceController:
    """把录音、预览和自动粘贴串起来的桌面模式控制器。"""

    def __init__(self):
        config, config_path, used_example_config, runtime_root = load_runtime_config(SOURCE_ROOT)
        self.config = config
        self.runtime_root = runtime_root
        self.config_path = config_path
        self.used_example_config = used_example_config

        setup_logging(config, runtime_root)
        self.logger = logging.getLogger(__name__)

        self.recorder, self.processor, self.asr_engine, self.temp_audio_path, _supported_languages = build_runtime(
            config,
            runtime_root,
        )
        self.usage_stats_store = UsageStatsStore(get_usage_stats_path(config, runtime_root))
        self.language = config["model"]["default_language"]
        self.preview = DesktopPreviewOverlay()
        self.listener = GlobalHotkeyListener(self.toggle_recording)
        self.is_recording = False
        self.last_inference_time = 0.0
        self.interim_text = ""
        self._inference_lock = threading.Lock()

    def preload_runtime(self) -> None:
        """像 CLI 一样在启动阶段完成模型预加载。"""
        print(format_loading_status(1, 4, "正在初始化运行时组件..."), flush=True)
        preload_model_or_exit(
            self.asr_engine.preload,
            self.logger,
            status_callback=lambda text: print(text, flush=True),
            failure_details=build_preload_failure_details(
                offline_mode=self.config.get("offline_mode", False),
                model_path=self.asr_engine.model_path,
                vad_model_path=self.asr_engine.vad_model_path,
                use_vad=self.asr_engine.use_vad,
                last_error=self.asr_engine.last_error,
            ),
        )

    def _remove_hotkey_artifact(self) -> None:
        """删除 Option+Space 留下的空格。"""
        try:
            from pynput.keyboard import Controller, Key

            keyboard = Controller()
            time.sleep(0.02)
            keyboard.press(Key.backspace)
            keyboard.release(Key.backspace)
        except Exception:
            self.logger.debug("清理热键残留字符失败", exc_info=True)

    def _save_clipboard(self) -> str | None:
        try:
            return subprocess.check_output(["pbpaste"], text=True)
        except Exception:
            return None

    def _restore_clipboard(self, text: str | None) -> None:
        if text is None:
            return
        try:
            subprocess.run(["pbcopy"], input=text, text=True, check=False)
        except Exception:
            return

    def _paste_text(self, text: str) -> bool:
        try:
            original_clipboard = self._save_clipboard()
            subprocess.run(["pbcopy"], input=text, text=True, check=False)
            from pynput.keyboard import Controller, Key

            keyboard = Controller()
            with keyboard.pressed(Key.cmd):
                keyboard.press("v")
                keyboard.release("v")
            threading.Thread(
                target=lambda: (time.sleep(0.5), self._restore_clipboard(original_clipboard)),
                daemon=True,
            ).start()
            return True
        except Exception as exc:
            self.logger.error("自动粘贴失败: %s", exc)
            return False

    def _render_preview_loop(self) -> None:
        while self.is_recording:
            now = time.time()
            if should_trigger_preview(now, self.last_inference_time):
                audio_data = self.recorder.get_current_audio()
                if audio_data is not None and len(audio_data) > 0 and self._inference_lock.acquire(blocking=False):
                    def _do_inference(data):
                        try:
                            text = run_streaming_inference(
                                data,
                                processor=self.processor,
                                asr_engine=self.asr_engine,
                                temp_audio_path=self.temp_audio_path,
                                language=self.language,
                            )
                            if text:
                                self.interim_text = text
                                self.preview.update_text(text)
                        except Exception:
                            self.logger.debug("流式预览识别失败", exc_info=True)
                        finally:
                            self._inference_lock.release()

                    threading.Thread(target=_do_inference, args=(audio_data,), daemon=True).start()
                self.last_inference_time = now

            if not self.interim_text:
                self.preview.update_text("正在聆听...")
            time.sleep(0.08)

    def toggle_recording(self) -> None:
        self._remove_hotkey_artifact()

        if not self.is_recording:
            self.interim_text = ""
            self.last_inference_time = time.time()
            try:
                self.recorder.start_recording()
            except Exception as exc:
                self.logger.error("启动录音失败: %s", exc)
                self.preview.show(f"启动录音失败：{exc}")
                return

            self.is_recording = True
            self.preview.show("正在聆听...")
            self.logger.info("桌面模式开始录音")
            threading.Thread(target=self._render_preview_loop, name="desktop-preview-loop", daemon=True).start()
            return

        self.is_recording = False
        self.preview.update_text("正在识别，请稍候...")
        audio_data = self.recorder.stop_recording()
        self.logger.info("桌面模式停止录音，开始最终识别")

        if audio_data is None:
            self.preview.hide()
            return

        text = transcribe_recording_serialized(
            audio_data,
            processor=self.processor,
            asr_engine=self.asr_engine,
            temp_audio_path=self.temp_audio_path,
            language=self.language,
            inference_lock=self._inference_lock,
        )

        if text:
            self.preview.update_text(text)
            pasted = self._paste_text(text)
            if pasted:
                char_count = len(text.replace("\n", ""))
                snapshot = self.usage_stats_store.record_input(char_count)
                self.logger.info("识别文本已自动粘贴")
                self.preview.update_text(
                    f"已粘贴  本次：{char_count}  今日：{snapshot.today_chars}  累计：{snapshot.total_chars}"
                )
            time.sleep(0.8)

        self.preview.hide()

    def run(self) -> None:
        if self.used_example_config:
            print(
                f"未找到 config/settings.yaml，当前正在使用示例配置: {self.config_path}",
                flush=True,
            )

        self.preload_runtime()
        print("voice desktop 已启动", flush=True)
        print("全局热键: Option+Space", flush=True)
        print("按 Ctrl+C 退出。首次使用需要授予麦克风和辅助功能权限。", flush=True)
        listener_thread = threading.Thread(
            target=self.listener.listen_forever,
            name="desktop-hotkey-listener",
            daemon=True,
        )
        listener_thread.start()
        self.preview.run_event_loop()


def main() -> int:
    controller = DesktopVoiceController()
    try:
        controller.run()
    except KeyboardInterrupt:
        print("\n正在退出 voice desktop ...", flush=True)
        return 0
    except Exception as exc:
        print(f"voice desktop 启动失败: {exc}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
