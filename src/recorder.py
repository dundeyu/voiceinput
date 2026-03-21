"""录音模块 - 使用sounddevice捕获麦克风音频"""

import sounddevice as sd
import numpy as np
from typing import Optional
import threading


class AudioRecorder:
    """音频录音器，支持开始/停止录音"""

    def __init__(self, sample_rate: int = 48000, channels: int = 1, dtype: str = "float32"):
        self.sample_rate = sample_rate
        self.channels = channels
        self.dtype = dtype
        self._is_recording = False
        self._audio_data: list = []
        self._lock = threading.Lock()
        self.current_volume = 0.0
        self._stream = None

    def _audio_callback(self, indata: np.ndarray, frames: int, time, status):
        """录音回调函数"""
        # 计算音量 RMS
        if len(indata) > 0:
            self.current_volume = np.sqrt(np.mean(indata**2))

        if status:
            pass # 也可以记录日志
        with self._lock:
            if self._is_recording:
                self._audio_data.append(indata.copy())

    def start_recording(self) -> bool:
        """开始录音"""
        if self._is_recording:
            return False

        with self._lock:
            self._audio_data = []
        try:
            stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype=self.dtype,
                callback=self._audio_callback
            )
            stream.start()
        except Exception:
            with self._lock:
                self._audio_data = []
                self._is_recording = False
            self._stream = None
            raise

        with self._lock:
            self._stream = stream
            self._is_recording = True
        return True

    def stop_recording(self) -> Optional[np.ndarray]:
        """停止录音并返回音频数据"""
        if not self._is_recording:
            return None

        with self._lock:
            self._is_recording = False

        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

        if not self._audio_data:
            return None

        # 合并所有音频块
        audio_data = np.concatenate(self._audio_data, axis=0)
        return audio_data

    @property
    def is_recording(self) -> bool:
        """是否正在录音"""
        return self._is_recording

    def get_current_audio(self) -> Optional[np.ndarray]:
        """获取目前已录音的音频片段副本(不会停止录音)"""
        if not self._is_recording:
            return None

        with self._lock:
            if not self._audio_data:
                return None
            return np.concatenate(self._audio_data, axis=0)

    def get_input_devices(self) -> list:
        """获取可用的输入设备列表"""
        devices = sd.query_devices()
        input_devices = []
        for i, dev in enumerate(devices):
            if dev['max_input_channels'] > 0:
                input_devices.append({
                    'id': i,
                    'name': dev['name'],
                    'channels': dev['max_input_channels'],
                    'default_samplerate': dev['default_samplerate']
                })
        return input_devices
