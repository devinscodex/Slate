"""tts.py: voice registry, bundled-vs-downloaded resolution, download
(mocked -- no real network in the test suite), and REAL synthesis using
the actual bundled northern_english_male model (genuine Piper
inference, not mocked, since that model ships in the repo already).
"""
import os

import pytest

import tts


def test_every_voice_has_the_same_metadata_shape():
    required_keys = {"label", "hf_path", "bundled", "sample_rate"}
    for voice_id, info in tts.VOICES.items():
        assert required_keys == set(info.keys()), voice_id


def test_exactly_one_voice_is_bundled():
    """Only northern_english_male ships bundled -- the other 3 (incl.
    alba) are real but optional, downloaded on first use, keeping the
    installer from permanently carrying every voice's ~60MB model."""
    bundled = {v for v, info in tts.VOICES.items() if info["bundled"]}
    assert bundled == {"northern_english_male"}


def test_bundled_voice_is_actually_available_without_downloading():
    assert tts.is_available("northern_english_male") is True
    assert tts.get_model_path("northern_english_male") is not None
    assert os.path.exists(tts.get_model_path("northern_english_male"))


def test_non_bundled_voices_are_not_available_until_downloaded():
    for voice_id in ("alba", "southern_english_female", "danny"):
        assert tts.is_available(voice_id) is False
        assert tts.get_model_path(voice_id) is None


def test_every_voice_has_a_real_bundled_preview_clip():
    for voice_id in tts.VOICES:
        path = tts.preview_path(voice_id)
        assert os.path.exists(path), voice_id
        assert os.path.getsize(path) > 1000, voice_id  # a real clip, not an empty stub


def test_download_voice_writes_onnx_and_json_then_becomes_available(tmp_path, monkeypatch):
    """Real network access is never exercised in the test suite --
    urllib.request.urlretrieve is monkeypatched to just write fake
    bytes, so this tests the real file-placement/rename logic
    (.part -> final name) without hitting HuggingFace."""
    written = []

    def fake_urlretrieve(url, filename, reporthook=None):
        with open(filename, "wb") as f:
            f.write(b"fake model bytes" if url.endswith(".onnx") else b"{}")
        written.append((url, str(filename)))
        if reporthook is not None:
            reporthook(1, 100, 100)

    monkeypatch.setattr(tts.urllib.request, "urlretrieve", fake_urlretrieve)

    assert tts.is_available("southern_english_female") is False
    result_path = tts.download_voice("southern_english_female")
    assert tts.is_available("southern_english_female") is True
    assert result_path == tts.get_model_path("southern_english_female")
    assert os.path.exists(result_path)
    assert os.path.exists(result_path + ".json")
    # downloaded via a .part temp name, not left behind after success
    assert not os.path.exists(result_path + ".part")


def test_download_voice_reports_progress(monkeypatch):
    def fake_urlretrieve(url, filename, reporthook=None):
        with open(filename, "wb") as f:
            f.write(b"x")
        if reporthook is not None:
            reporthook(1, 50, 100)

    monkeypatch.setattr(tts.urllib.request, "urlretrieve", fake_urlretrieve)

    seen = []
    tts.download_voice("danny", progress_callback=lambda done, total: seen.append((done, total)))
    assert seen == [(50, 100)]


def test_synthesize_unavailable_voice_raises_clear_error():
    with pytest.raises(ValueError, match="not been downloaded"):
        tts.synthesize("hello", "southern_english_female")


def test_synthesize_bundled_voice_produces_real_audio():
    """Genuine Piper inference against the real bundled model -- not
    mocked, since northern_english_male.onnx actually ships in the repo."""
    audio, sample_rate, sample_width, channels, chunk_sample_counts = tts.synthesize(
        "This is a real test.", "northern_english_male"
    )
    assert len(audio) > 1000  # real audio data, not empty
    assert sample_rate == 22050
    assert sample_width == 2  # 16-bit PCM
    assert channels == 1
    assert chunk_sample_counts  # real per-sentence durations
    assert sum(chunk_sample_counts) == len(audio) // (sample_width * channels)


def test_synthesize_length_scale_changes_audio_duration():
    """Piper's own real length_scale (speed) parameter -- a real
    number, not assumed: a larger length_scale (slower) must produce
    MORE audio samples for the same text than a smaller one (faster)."""
    fast_audio, _, _, _, _ = tts.synthesize("This is a somewhat longer test sentence.", "northern_english_male", length_scale=0.7)
    slow_audio, _, _, _, _ = tts.synthesize("This is a somewhat longer test sentence.", "northern_english_male", length_scale=1.5)
    assert len(slow_audio) > len(fast_audio)


def test_synthesize_caches_the_loaded_voice_across_calls():
    """PiperVoice.load() alone takes ~1.2s (loading the ~60MB model +
    building an onnxruntime session) -- reloading it on every call
    meant every 'Read this page' repaid that cost even for the same
    voice back-to-back. Confirms the same PiperVoice object is reused,
    not a fresh one built each time."""
    tts._voice_cache.clear()  # isolate from whatever earlier tests already warmed
    tts.synthesize("First call.", "northern_english_male")
    assert "northern_english_male" in tts._voice_cache
    first_instance = tts._voice_cache["northern_english_male"]

    tts.synthesize("Second call.", "northern_english_male")
    assert tts._voice_cache["northern_english_male"] is first_instance  # same object, not reloaded


def test_speed_to_length_scale_calibrates_around_a_slower_natural_default():
    """The default audio reading voice is calibrated to a slower, more
    natural pace than Piper's raw native rate: "1.0x" (user_speed=1.0)
    must map to BASE_LENGTH_SCALE, not Piper's raw native 1.0 -- and
    every other speed preset must scale proportionally FROM that new
    baseline, not from Piper's raw default."""
    assert tts.speed_to_length_scale(1.0) == tts.BASE_LENGTH_SCALE
    assert tts.BASE_LENGTH_SCALE > 1.0  # a real, deliberate slowdown from Piper's native rate

    # Faster/slower presets stay proportional to the SAME calibrated
    # baseline (higher user_speed -> lower length_scale -> faster speech).
    assert tts.speed_to_length_scale(2.0) == tts.BASE_LENGTH_SCALE / 2.0
    assert tts.speed_to_length_scale(0.75) == tts.BASE_LENGTH_SCALE / 0.75
    assert tts.speed_to_length_scale(2.0) < tts.speed_to_length_scale(1.0) < tts.speed_to_length_scale(0.75)
