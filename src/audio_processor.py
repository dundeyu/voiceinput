"""音频处理模块 - 重采样和格式转换"""

import numpy as np
import soundfile as sf
from pathlib import Path
from scipy import signal


class AudioProcessor:
    """音频处理器，负责重采样、格式转换和保存"""

    def __init__(self, input_sample_rate: int = 48000, target_sample_rate: int = 16000):
        self.input_sample_rate = input_sample_rate
        self.target_sample_rate = target_sample_rate

    def resample(self, audio_data: np.ndarray) -> np.ndarray:
        """
        重采样音频数据
        将输入采样率转换为目标采样率(16kHz)
        """
        if audio_data is None or len(audio_data) == 0:
            raise ValueError("音频数据为空")

        if self.input_sample_rate == self.target_sample_rate:
            return audio_data.astype(np.float32)

        num_samples = int(len(audio_data) * self.target_sample_rate / self.input_sample_rate)
        if num_samples <= 0:
            raise ValueError("重采样后的音频长度无效")

        if len(audio_data) == 1:
            return np.repeat(audio_data.astype(np.float32), num_samples)

        resampled = signal.resample_poly(
            audio_data.astype(np.float64),
            up=self.target_sample_rate,
            down=self.input_sample_rate,
        )

        return resampled.astype(np.float32)

    def to_mono(self, audio_data: np.ndarray) -> np.ndarray:
        """
        转换为单声道
        如果是多声道，取平均值
        """
        if audio_data.ndim > 1:
            return np.mean(audio_data, axis=1)
        return audio_data.flatten()

    def normalize(self, audio_data: np.ndarray) -> np.ndarray:
        """
        归一化音频数据
        确保数据在[-1, 1]范围内
        """
        max_val = np.max(np.abs(audio_data))
        if max_val > 0:
            return audio_data / max_val
        return audio_data

    def process(self, audio_data: np.ndarray) -> np.ndarray:
        """
        完整的音频处理流程
        1. 转单声道
        2. 重采样
        3. 归一化
        """
        # 转单声道
        mono = self.to_mono(audio_data)

        # 重采样
        resampled = self.resample(mono)

        # 归一化
        normalized = self.normalize(resampled)

        return normalized

    def save_wav(self, audio_data: np.ndarray, filepath: str, sample_rate: int = None) -> str:
        """
        保存音频数据为WAV文件

        Args:
            audio_data: 音频数据
            filepath: 保存路径
            sample_rate: 采样率，默认使用目标采样率

        Returns:
            保存的文件路径
        """
        if sample_rate is None:
            sample_rate = self.target_sample_rate

        filepath = Path(filepath)
        filepath.parent.mkdir(parents=True, exist_ok=True)

        audio_data = np.clip(np.asarray(audio_data, dtype=np.float32), -1.0, 1.0)
        sf.write(str(filepath), audio_data, sample_rate, subtype="PCM_16")
        return str(filepath)
