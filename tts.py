"""Text-to-speech reading (Read Aloud). Piper TTS -- engine is
GPL-3.0-or-later, voices are MIT-licensed, both real FOSS confirmed
live (not assumed) before choosing this over paid alternatives.

Voice choice (Devin's own listening tests, 3 real rounds -- a plain
sentence, a numbers/punctuation/date/currency stress test, then a
public-domain narrative passage across the finalists): northern_english_male
is the one bundled voice (voices/, ships with Slate, zero setup). alba,
southern_english_female, and danny are real but optional -- downloaded
on first use into ~/.slate/tts-voices/ (same config convention as
recent.py/gate.py/theme.py), keeping the repo itself from permanently
carrying ~180MB of binaries for voices most installs will never touch.
Small preview clips for all four (voices/previews/, a few hundred KB
each, all reading the same passage for a fair comparison) ship bundled
so a voice can be sampled before committing to its ~60MB download.

piper is imported lazily inside functions, not at module load -- the
rest of Slate must keep working even if these dependencies are somehow
missing (matches _set_window_icon's fail-soft branding load).
"""
import os
import urllib.request
from pathlib import Path

CONFIG_DIR = Path.home() / ".slate"
DOWNLOADED_VOICES_DIR = CONFIG_DIR / "tts-voices"
BUNDLED_VOICES_DIR = Path(__file__).parent / "voices"
PREVIEWS_DIR = BUNDLED_VOICES_DIR / "previews"

HUGGINGFACE_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main"

VOICES = {
    "northern_english_male": {
        "label": "Northern English Male",
        "hf_path": "en/en_GB/northern_english_male/medium/en_GB-northern_english_male-medium",
        "bundled": True,
        "sample_rate": 22050,
    },
    "alba": {
        "label": "Alba (GB Female)",
        "hf_path": "en/en_GB/alba/medium/en_GB-alba-medium",
        "bundled": False,
        "sample_rate": 22050,
    },
    "southern_english_female": {
        "label": "Southern English Female",
        "hf_path": "en/en_GB/southern_english_female/low/en_GB-southern_english_female-low",
        "bundled": False,
        "sample_rate": 16000,
    },
    "danny": {
        "label": "Danny (US Male)",
        "hf_path": "en/en_US/danny/low/en_US-danny-low",
        "bundled": False,
        "sample_rate": 16000,
    },
}


def _onnx_filename(voice_id: str) -> str:
    return os.path.basename(VOICES[voice_id]["hf_path"]) + ".onnx"


def _bundled_onnx_path(voice_id: str) -> Path:
    return BUNDLED_VOICES_DIR / _onnx_filename(voice_id)


def _downloaded_onnx_path(voice_id: str) -> Path:
    return DOWNLOADED_VOICES_DIR / _onnx_filename(voice_id)


def preview_path(voice_id: str) -> str:
    return str(PREVIEWS_DIR / f"{voice_id}.wav")


def is_available(voice_id: str) -> bool:
    """True if this voice's real model is already usable -- bundled
    with Slate, or already downloaded in a previous session."""
    return _bundled_onnx_path(voice_id).exists() or _downloaded_onnx_path(voice_id).exists()


def get_model_path(voice_id: str):
    """Real .onnx path if available (bundled takes priority over a
    downloaded copy, though both should never coexist in practice), or
    None if this voice hasn't been downloaded yet."""
    bundled = _bundled_onnx_path(voice_id)
    if bundled.exists():
        return str(bundled)
    downloaded = _downloaded_onnx_path(voice_id)
    if downloaded.exists():
        return str(downloaded)
    return None


def download_voice(voice_id: str, progress_callback=None) -> str:
    """Download a voice's .onnx + .onnx.json into ~/.slate/tts-voices/.
    progress_callback(bytes_so_far, total_bytes) if given, called only
    for the (large) .onnx file, not its tiny .json sidecar. Downloads
    to a .part temp path first and renames on success, so a failed/
    interrupted download never leaves a half-written file that
    is_available() would wrongly treat as usable."""
    info = VOICES[voice_id]
    DOWNLOADED_VOICES_DIR.mkdir(parents=True, exist_ok=True)
    filename = os.path.basename(info["hf_path"])
    onnx_dest = DOWNLOADED_VOICES_DIR / f"{filename}.onnx"
    json_dest = DOWNLOADED_VOICES_DIR / f"{filename}.onnx.json"

    def _report(block_count, block_size, total_size):
        if progress_callback is not None:
            progress_callback(min(block_count * block_size, total_size), total_size)

    for url, dest, hook in (
        (f"{HUGGINGFACE_BASE}/{info['hf_path']}.onnx", onnx_dest, _report),
        (f"{HUGGINGFACE_BASE}/{info['hf_path']}.onnx.json", json_dest, None),
    ):
        tmp_dest = dest.with_name(dest.name + ".part")
        urllib.request.urlretrieve(url, tmp_dest, reporthook=hook)
        tmp_dest.replace(dest)

    return str(onnx_dest)


def synthesize(text: str, voice_id: str, length_scale: float = 1.0):
    """Returns (audio_int16_bytes, sample_rate, sample_width, sample_channels)
    for the whole text (Piper yields one AudioChunk per sentence;
    concatenated here into one buffer). length_scale is Piper's own
    real speed control (>1 slower, <1 faster) -- confirmed live via
    SynthesisConfig's actual signature, not guessed."""
    from piper import PiperVoice, SynthesisConfig

    model_path = get_model_path(voice_id)
    if model_path is None:
        raise ValueError(f"Voice '{voice_id}' has not been downloaded yet")

    voice = PiperVoice.load(model_path)
    config = SynthesisConfig(length_scale=length_scale)
    chunks = list(voice.synthesize(text, config))
    if not chunks:
        return b"", voice.config.sample_rate, 2, 1

    audio = b"".join(c.audio_int16_bytes for c in chunks)
    first = chunks[0]
    return audio, first.sample_rate, first.sample_width, first.sample_channels
