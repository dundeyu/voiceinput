import wave

import numpy as np

from audio_processor import AudioProcessor


def test_resample_applies_lowpass_before_downsampling():
    processor = AudioProcessor(input_sample_rate=48000, target_sample_rate=16000)
    duration_seconds = 0.05
    sample_count = int(processor.input_sample_rate * duration_seconds)
    timeline = np.arange(sample_count, dtype=np.float64) / processor.input_sample_rate

    low_tone = np.sin(2 * np.pi * 1000 * timeline)
    high_tone = np.sin(2 * np.pi * 12000 * timeline)

    low_resampled = processor.resample(low_tone)
    high_resampled = processor.resample(high_tone)

    low_rms = np.sqrt(np.mean(np.square(low_resampled)))
    high_rms = np.sqrt(np.mean(np.square(high_resampled)))

    assert high_rms < low_rms * 0.25


def test_save_wav_creates_pcm16_mono_file(tmp_path):
    processor = AudioProcessor(input_sample_rate=16000, target_sample_rate=16000)
    audio = np.array([0.0, 0.5, -0.5, 1.2], dtype=np.float32)

    output_path = tmp_path / "sample.wav"
    saved_path = processor.save_wav(audio, str(output_path))

    assert saved_path == str(output_path)
    assert output_path.exists()

    with wave.open(str(output_path), "rb") as wav_file:
        assert wav_file.getnchannels() == 1
        assert wav_file.getsampwidth() == 2
        assert wav_file.getframerate() == 16000
        frames = wav_file.readframes(wav_file.getnframes())

    restored = np.frombuffer(frames, dtype=np.int16)
    assert restored.tolist() == [0, 16384, -16384, 32767]
