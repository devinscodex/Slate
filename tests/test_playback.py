"""playback.py's Player: the real position/pause state machine, tested
by calling _callback() directly with synthetic buffers -- no real
audio device needed (this dev environment has none anyway, see the
module's own docstring). Play/stop/is_playing (the parts that DO touch
a real sounddevice.OutputStream) aren't exercised here since that
needs actual hardware; the callback logic they'd drive is what's
tested instead.
"""
import numpy as np

import playback


def _make_audio(n_samples, channels=1):
    # a simple 0..N-1 ramp so it's easy to assert exactly which samples
    # ended up in the output buffer
    samples = np.arange(n_samples, dtype=np.int16)
    return samples.tobytes(), n_samples


def test_load_resets_position_and_stores_audio_shape():
    p = playback.Player()
    audio_bytes, n = _make_audio(100)
    p.load(audio_bytes, sample_rate=22050, channels=1)
    assert p._position == 0
    assert p._audio.shape == (100, 1)
    assert p._sample_rate == 22050


def test_callback_fills_output_and_advances_position():
    p = playback.Player()
    audio_bytes, n = _make_audio(100)
    p.load(audio_bytes, sample_rate=22050, channels=1)

    outdata = np.zeros((10, 1), dtype=np.int16)
    p._callback(outdata, 10, None, None)
    assert list(outdata[:, 0]) == list(range(10))
    assert p._position == 10

    outdata2 = np.zeros((10, 1), dtype=np.int16)
    p._callback(outdata2, 10, None, None)
    assert list(outdata2[:, 0]) == list(range(10, 20))
    assert p._position == 20


def test_callback_pads_with_zero_on_final_partial_frame():
    p = playback.Player()
    audio_bytes, n = _make_audio(15)  # not a clean multiple of 10
    p.load(audio_bytes, sample_rate=22050, channels=1)

    outdata = np.zeros((10, 1), dtype=np.int16)
    p._callback(outdata, 10, None, None)
    assert list(outdata[:, 0]) == list(range(10))

    outdata2 = np.full((10, 1), -1, dtype=np.int16)  # pre-fill with a sentinel
    p._callback(outdata2, 10, None, None)
    assert list(outdata2[:5, 0]) == list(range(10, 15))
    assert list(outdata2[5:, 0]) == [0, 0, 0, 0, 0]  # padded, sentinel overwritten


def test_callback_raises_callback_stop_when_audio_exhausted():
    import sounddevice as sd

    p = playback.Player()
    audio_bytes, n = _make_audio(5)
    p.load(audio_bytes, sample_rate=22050, channels=1)
    p._position = 5  # already at the end

    outdata = np.full((10, 1), -1, dtype=np.int16)
    try:
        p._callback(outdata, 10, None, None)
        assert False, "expected CallbackStop"
    except sd.CallbackStop:
        pass
    assert list(outdata[:, 0]) == [0] * 10  # silence, not leftover sentinel


def test_pause_holds_position_does_not_advance_or_error():
    p = playback.Player()
    audio_bytes, n = _make_audio(100)
    p.load(audio_bytes, sample_rate=22050, channels=1)
    p._position = 30
    p.pause()

    outdata = np.full((10, 1), -1, dtype=np.int16)
    p._callback(outdata, 10, None, None)
    assert list(outdata[:, 0]) == [0] * 10  # silence while paused
    assert p._position == 30  # NOT advanced -- resuming continues from here


def test_stop_resets_position_to_zero():
    p = playback.Player()
    audio_bytes, n = _make_audio(100)
    p.load(audio_bytes, sample_rate=22050, channels=1)
    p._position = 42
    p.stop()
    assert p._position == 0
    assert p._paused is False


def test_progress_reflects_position_as_a_fraction():
    p = playback.Player()
    audio_bytes, n = _make_audio(100)
    p.load(audio_bytes, sample_rate=22050, channels=1)
    assert p.progress == 0.0
    p._position = 25
    assert p.progress == 0.25
    p._position = 100
    assert p.progress == 1.0


def test_progress_is_zero_with_nothing_loaded():
    p = playback.Player()
    assert p.progress == 0.0


def test_is_playing_false_with_no_stream():
    p = playback.Player()
    assert p.is_playing() is False
