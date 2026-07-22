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
    bundled = [v for v, info in tts.VOICES.items() if info["bundled"]]
    assert bundled == ["northern_english_male"]


def test_bundled_voice_is_actually_available_without_downloading():
    assert tts.is_available("northern_english_male") is True
    assert tts.get_model_path("northern_english_male") is not None
    assert os.path.exists(tts.get_model_path("northern_english_male"))


def test_non_bundled_voice_is_not_available_until_downloaded():
    assert tts.is_available("alba") is False
    assert tts.get_model_path("alba") is None


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

    assert tts.is_available("alba") is False
    result_path = tts.download_voice("alba")
    assert tts.is_available("alba") is True
    assert result_path == tts.get_model_path("alba")
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
        tts.synthesize("hello", "alba")


def test_synthesize_bundled_voice_produces_real_audio():
    """Genuine Piper inference against the real bundled model -- not
    mocked, since northern_english_male.onnx actually ships in the repo."""
    audio, sample_rate, sample_width, channels = tts.synthesize(
        "This is a real test.", "northern_english_male"
    )
    assert len(audio) > 1000  # real audio data, not empty
    assert sample_rate == 22050
    assert sample_width == 2  # 16-bit PCM
    assert channels == 1


def test_synthesize_length_scale_changes_audio_duration():
    """Piper's own real length_scale (speed) parameter -- a real
    number, not assumed: a larger length_scale (slower) must produce
    MORE audio samples for the same text than a smaller one (faster)."""
    fast_audio, _, _, _ = tts.synthesize("This is a somewhat longer test sentence.", "northern_english_male", length_scale=0.7)
    slow_audio, _, _, _ = tts.synthesize("This is a somewhat longer test sentence.", "northern_english_male", length_scale=1.5)
    assert len(slow_audio) > len(fast_audio)
