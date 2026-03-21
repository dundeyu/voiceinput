from unittest.mock import patch

from recorder import AudioRecorder


class FakeStream:
    def __init__(self):
        self.started = False
        self.stopped = False
        self.closed = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def close(self):
        self.closed = True


def test_start_recording_success_sets_state_and_starts_stream():
    recorder = AudioRecorder()
    fake_stream = FakeStream()

    with patch("recorder.sd.InputStream", return_value=fake_stream):
        started = recorder.start_recording()

    assert started is True
    assert recorder.is_recording is True
    assert recorder._stream is fake_stream
    assert fake_stream.started is True


def test_start_recording_failure_rolls_back_state():
    recorder = AudioRecorder()
    recorder._audio_data = [[[1.0]]]

    with patch("recorder.sd.InputStream", side_effect=RuntimeError("mic unavailable")):
        try:
            recorder.start_recording()
        except RuntimeError as exc:
            assert str(exc) == "mic unavailable"
        else:
            raise AssertionError("Expected start_recording to raise RuntimeError")

    assert recorder.is_recording is False
    assert recorder._stream is None
    assert recorder._audio_data == []


def test_stop_recording_returns_concatenated_audio_and_releases_stream():
    recorder = AudioRecorder()
    fake_stream = FakeStream()
    recorder._stream = fake_stream
    recorder._is_recording = True
    recorder._audio_data = [
        [[1.0], [2.0]],
        [[3.0]],
    ]

    with patch("recorder.np.concatenate", return_value="merged-audio") as concatenate_mock:
        audio = recorder.stop_recording()

    assert recorder.is_recording is False
    assert recorder._stream is None
    assert fake_stream.stopped is True
    assert fake_stream.closed is True
    concatenate_mock.assert_called_once_with(recorder._audio_data, axis=0)
    assert audio == "merged-audio"
