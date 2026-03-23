"""ASR识别引擎 - 封装FunASR AutoModel"""

import sys
import os
import logging
from typing import Optional, List
from contextlib import contextmanager, redirect_stdout, redirect_stderr

# 注册FunASRNano模型 - 需要将fun_asr_nano目录加入sys.path
# 这是因为model.py中的from ctc import CTC需要相对导入
import funasr
funasr_dir = os.path.dirname(funasr.__file__)
fun_asr_nano_dir = os.path.join(funasr_dir, 'models', 'fun_asr_nano')
if os.path.exists(fun_asr_nano_dir) and fun_asr_nano_dir not in sys.path:
    sys.path.insert(0, fun_asr_nano_dir)

from funasr import AutoModel
from funasr.utils.load_utils import load_audio_text_image_video
from loading_status import format_loading_status
from model_download import download_model_from_modelscope
from text_processing import filter_filler_words, correct_vocabulary

logger = logging.getLogger(__name__)

# 默认的长音频阈值（秒），超过此阈值使用VAD分段处理
DEFAULT_LONG_AUDIO_THRESHOLD = 30
LEGACY_VAD_MODEL_PATH = os.path.expanduser(
    "~/.cache/modelscope/hub/models/iic/speech_fsmn_vad_zh-cn-16k-common-pytorch"
)


@contextmanager
def suppress_terminal_noise():
    """屏蔽三方模型加载或推理时直接写入终端的输出。"""
    with open(os.devnull, "w", encoding="utf-8") as devnull:
        with redirect_stdout(devnull), redirect_stderr(devnull):
            yield


class ASREngine:
    """语音识别引擎，懒加载模型"""

    def __init__(
        self,
        model_path: str,
        device: str = "cpu",
        default_language: str = "中文",
        filler_words: List[str] = None,
        vocabulary_corrections: dict = None,
        use_vad: bool = True,
        long_audio_threshold: float = DEFAULT_LONG_AUDIO_THRESHOLD,
        vad_model_path: str = None,
        offline_mode: bool = False
    ):
        self.model_path = model_path
        self.device = device
        self.default_language = default_language
        self.filler_words = filler_words or []
        self.vocabulary_corrections = vocabulary_corrections or {}
        self.use_vad = use_vad
        self.long_audio_threshold = long_audio_threshold
        self.vad_model_path = str(vad_model_path) if vad_model_path else None
        self.offline_mode = offline_mode
        self._model = None  # FunASRNano 实例
        self._model_kwargs: dict = {}
        self._vad_model: Optional[AutoModel] = None
        self._is_loaded = False

    def _resolve_vad_model_path(self) -> str | None:
        """解析最终使用的本地 VAD 模型路径。"""
        if self.vad_model_path and os.path.exists(self.vad_model_path):
            return self.vad_model_path

        if os.path.exists(LEGACY_VAD_MODEL_PATH):
            logger.info(f"回退使用旧版VAD缓存路径: {LEGACY_VAD_MODEL_PATH}")
            return LEGACY_VAD_MODEL_PATH

        return self.vad_model_path

    def load_model(self, status_callback=None) -> bool:
        """加载模型"""
        if self._is_loaded:
            return True

        try:
            # 离线模式：设置环境变量禁止网络访问
            if self.offline_mode:
                os.environ['MODELSCOPE_OFFLINE'] = '1'
                os.environ['HF_HUB_OFFLINE'] = '1'
                logger.info("离线模式已启用，禁止网络访问")

            # 先加载VAD模型
            if self.use_vad:
                logger.info("正在加载VAD模型...")
                if status_callback:
                    status_callback(format_loading_status(2, 4, "正在加载 VAD 模型..."))
                resolved_vad_path = self._resolve_vad_model_path()

                # 检查本地VAD模型是否存在
                if resolved_vad_path and os.path.exists(resolved_vad_path):
                    logger.info(f"使用本地VAD模型: {resolved_vad_path}")
                    vad_model_to_use = resolved_vad_path
                else:
                    logger.warning(f"本地VAD模型不存在: {self.vad_model_path}")
                    if self.offline_mode:
                        logger.error("离线模式下无法下载模型，请手动下载VAD模型")
                        return False
                    if status_callback:
                        status_callback(format_loading_status(2, 4, "未找到本地 VAD，正在尝试联网获取..."))
                    vad_model_to_use = download_model_from_modelscope(
                        "fsmn-vad",
                        status_callback=lambda text: status_callback(format_loading_status(2, 4, text))
                        if status_callback
                        else None,
                        label="VAD 模型",
                    )

                with suppress_terminal_noise():
                    self._vad_model = AutoModel(
                        model=vad_model_to_use,
                        device=self.device,
                        disable_update=True,
                        disable_pbar=True,
                        disable_log=True,
                        log_level="ERROR",
                    )
                logger.info("VAD模型加载完成")

            # 使用 FunASRNano.from_pretrained 直接加载 ASR 模型
            # 这比 AutoModel 更稳定，特别是分段处理时
            # 延迟导入以避免模块级别的循环依赖
            from funasr.models.fun_asr_nano.model import FunASRNano

            logger.info(f"正在加载ASR模型: {self.model_path}")
            asr_model_to_use = self.model_path
            if status_callback:
                if os.path.exists(str(self.model_path)):
                    status_callback(format_loading_status(3, 4, "正在加载本地 ASR 模型..."))
                else:
                    status_callback(format_loading_status(3, 4, "未找到本地 ASR，正在尝试联网获取..."))
                    asr_model_to_use = download_model_from_modelscope(
                        str(self.model_path),
                        status_callback=lambda text: status_callback(format_loading_status(3, 4, text))
                        if status_callback
                        else None,
                        label="ASR 模型",
                    )
            with suppress_terminal_noise():
                self._model, self._model_kwargs = FunASRNano.from_pretrained(
                    model=asr_model_to_use,
                    device=self.device,
                    disable_pbar=True,
                    disable_log=True
                )
            self._model.eval()
            self._model_kwargs['device'] = self.device

            self._is_loaded = True
            if status_callback:
                status_callback(format_loading_status(4, 4, "模型加载完成，正在准备界面..."))
            logger.info("模型加载完成")
            return True
        except Exception as e:
            logger.error(f"模型加载失败: {e}")
            return False

    def transcribe(
        self,
        audio_path: str,
        language: str = None,
        hotwords: List[str] = None
    ) -> Optional[str]:
        """
        识别音频文件

        Args:
            audio_path: 音频文件路径
            language: 语言，默认使用配置的默认语言
            hotwords: 热词列表

        Returns:
            识别文本
        """
        if not self._is_loaded:
            if not self.load_model():
                return None

        if language is None:
            language = self.default_language

        try:
            # 检测音频长度，决定是否使用VAD分段处理
            audio_duration = self._get_audio_duration(audio_path)
            logger.info(f"音频时长: {audio_duration:.2f}秒")

            if self.use_vad and self._vad_model and audio_duration > self.long_audio_threshold:
                logger.info(f"音频时长超过{self.long_audio_threshold}秒，使用VAD分段处理")
                return self._transcribe_with_vad(audio_path, language, hotwords)
            else:
                return self._transcribe_direct(audio_path, language, hotwords)

        except Exception as e:
            import traceback
            logger.error(f"识别失败: {e}\n{traceback.format_exc()}")
            return None

    def _get_audio_duration(self, audio_path: str) -> float:
        """获取音频时长（秒）"""
        try:
            speech = load_audio_text_image_video(audio_path, fs=16000)
            if speech is None:
                logger.warning(f"加载音频失败，返回0: {audio_path}")
                return 0.0
            return len(speech) / 16000.0
        except Exception as e:
            logger.warning(f"获取音频时长失败: {e}，默认返回0")
            return 0.0

    def _transcribe_direct(
        self,
        audio_path: str,
        language: str,
        hotwords: List[str] = None
    ) -> Optional[str]:
        """直接识别音频（短音频）"""
        # 使用 FunASRNano.inference 方法
        res = self._model.inference(
            data_in=[audio_path],
            **self._model_kwargs,
            language=language,
            itn=True,
            hotwords=hotwords if hotwords else [],
        )

        if res and len(res) > 0 and res[0] is not None and len(res[0]) > 0:
            text = res[0][0]["text"]
            logger.info(f"原始识别结果: {text}")
            # 过滤口语词
            text = self._filter_filler_words(text)
            if text != res[0][0]["text"]:
                logger.info(f"过滤后结果: {text}")

            # 词汇替换/纠错
            corrected_text = self._correct_vocabulary(text)
            if corrected_text != text:
                logger.info(f"词汇纠错后结果: {corrected_text[:100]}")
                text = corrected_text

            return text

        logger.warning(f"模型推理返回空结果: res={res}")
        return None

    def _transcribe_with_vad(
        self,
        audio_path: str,
        language: str,
        hotwords: List[str] = None
    ) -> Optional[str]:
        """使用VAD分段识别长音频"""
        import tempfile

        try:
            # VAD检测语音段
            vad_res = self._vad_model.generate(
                input=[audio_path],
                disable_pbar=True,
                disable_log=True,
            )
            if not vad_res or len(vad_res) == 0:
                logger.warning("VAD检测失败，尝试直接识别")
                return self._transcribe_direct(audio_path, language, hotwords)

            vad_segments = vad_res[0]["value"]
            logger.info(f"VAD检测到 {len(vad_segments)} 个语音段")

            # 加载音频
            speech = load_audio_text_image_video(audio_path, fs=16000)

            if speech is None:
                logger.error("加载音频失败")
                return self._transcribe_direct(audio_path, language, hotwords)

            # 转换为 numpy 数组
            if hasattr(speech, 'numpy'):
                speech = speech.numpy()

            # 分段识别
            results = []
            for i, seg in enumerate(vad_segments):
                start_sample = int(seg[0] * 16)  # ms to samples (16kHz)
                end_sample = int(seg[1] * 16)
                segment = speech[start_sample:end_sample]

                if segment is None or len(segment) < 1600:  # 跳过小于0.1秒的段
                    continue

                # 保存为临时文件再识别（FunASRNano 不支持直接传入 tensor 数据）
                temp_path = None
                try:
                    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
                        temp_path = f.name
                    from audio_processor import AudioProcessor

                    AudioProcessor(input_sample_rate=16000, target_sample_rate=16000).save_wav(
                        segment,
                        temp_path,
                        sample_rate=16000,
                    )

                    res = self._model.inference(
                        data_in=[temp_path],
                        **self._model_kwargs,
                        language=language,
                        itn=True,
                        hotwords=hotwords if hotwords else [],
                    )

                    # 删除临时文件
                    if temp_path and os.path.exists(temp_path):
                        os.unlink(temp_path)

                    if res and len(res) > 0 and res[0] is not None and len(res[0]) > 0:
                        results.append(res[0][0]["text"])
                except Exception as e:
                    logger.warning(f"段 {i} 识别失败: {e}")
                    if temp_path and os.path.exists(temp_path):
                        os.unlink(temp_path)

            if not results:
                logger.warning("所有分段识别结果为空，尝试直接识别")
                return self._transcribe_direct(audio_path, language, hotwords)

            # 合并结果
            combined_text = " ".join(results)
            logger.info(f"原始识别结果(合并): {combined_text[:100]}...")

            # 过滤口语词
            text = self._filter_filler_words(combined_text)
            if text != combined_text:
                logger.info(f"过滤后结果: {text[:100]}...")

            # 词汇替换/纠错
            corrected_text = self._correct_vocabulary(text)
            if corrected_text != text:
                logger.info(f"词汇纠错后结果: {corrected_text[:100]}")
                text = corrected_text

            return text

        except Exception as e:
            logger.error(f"VAD分段识别失败: {e}，尝试直接识别")
            return self._transcribe_direct(audio_path, language, hotwords)

    def _filter_filler_words(self, text: str) -> str:
        """过滤口语词并清理标点。"""
        return filter_filler_words(text, self.filler_words)

    def _correct_vocabulary(self, text: str) -> str:
        """专有名词/易错词替换纠错。"""
        return correct_vocabulary(text, self.vocabulary_corrections)

    @property
    def is_loaded(self) -> bool:
        """模型是否已加载"""
        return self._is_loaded

    def preload(self, status_callback=None):
        """预加载模型"""
        if not self._is_loaded:
            return self.load_model(status_callback=status_callback)
        return True
