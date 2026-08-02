"""Text-to-speech reading (Read Aloud). Piper TTS -- engine is
GPL-3.0-or-later, voices are MIT-licensed.

northern_english_male and alba are bundled (voices/, ships with Slate,
zero setup). southern_english_female and danny are real but optional --
downloaded on first use into ~/.slate/tts-voices/, keeping the repo
from permanently carrying ~180MB of binaries for voices most installs
never touch. Small preview clips for all four (voices/previews/) ship
bundled so a voice can be sampled before committing to its ~60MB
download.

piper is imported lazily inside functions, not at module load -- the
rest of Slate must keep working even if this dependency is missing.
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
        "bundled": True,
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


def load_preview_audio(voice_id: str):
    """Returns (audio_int16_bytes, sample_rate, channels) for this
    voice's bundled preview clip. All 4 preview WAVs ship bundled
    regardless of whether a voice's full model is installed, so every
    voice can be sampled without downloading anything. Uses stdlib
    wave, not a raw-bytes assumption -- real WAV header, not guaranteed
    headerless PCM."""
    import wave
    with wave.open(preview_path(voice_id), "rb") as w:
        return w.readframes(w.getnframes()), w.getframerate(), w.getnchannels()


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


_voice_cache = {}  # voice_id -> loaded PiperVoice, kept for the process's lifetime


def _get_cached_voice(voice_id: str):
    if voice_id in _voice_cache:
        return _voice_cache[voice_id]

    from piper import PiperVoice

    model_path = get_model_path(voice_id)
    if model_path is None:
        raise ValueError(f"Voice '{voice_id}' has not been downloaded yet")

    voice = PiperVoice.load(model_path)
    _voice_cache[voice_id] = voice
    return voice


# Piper's native length_scale=1.0 reads noticeably rushed for
# continuous-prose reading (common for VITS-family TTS models at their
# raw default rate). This shifts what the UI calls "1.0x" to a slower,
# more natural pace; every other speed preset scales proportionally
# FROM this baseline via speed_to_length_scale(), not from Piper's raw
# default -- applied uniformly to every voice in VOICES.
#
# NOT tuned against real audio hardware (this dev environment has zero
# audio output devices) -- 1.15 is a reasonable starting point, needs a
# real-hardware listening pass to confirm.
BASE_LENGTH_SCALE = 1.15


def speed_to_length_scale(user_speed: float) -> float:
    """User-facing speed multiplier (1.0 = the calibrated natural
    default above, NOT Piper's raw native rate) -> Piper's own
    length_scale parameter (inverse relationship: higher length_scale
    is slower speech, lower is faster)."""
    return BASE_LENGTH_SCALE / user_speed


def synthesize(text: str, voice_id: str, length_scale: float = 1.0):
    """Returns (audio_int16_bytes, sample_rate, sample_width, sample_channels,
    chunk_sample_counts) for the whole text (Piper yields one AudioChunk per
    sentence; concatenated here into one buffer). length_scale is Piper's own
    speed control (>1 slower, <1 faster).

    chunk_sample_counts is the number of audio samples EACH sentence-
    chunk contributed, in order -- real per-sentence durations for
    _update_tts_highlight (slate.py) to calibrate the read-along
    highlight per sentence instead of assuming a uniform character rate
    across the whole page. True per-phoneme alignment
    (include_alignments=True) isn't available: these voice exports'
    ONNX session returns only one output tensor (audio), no duration-
    output branch. Per-sentence chunk boundaries are the data that IS
    available.

    PiperVoice.load() alone takes ~1.2s (loading the ONNX model +
    building an onnxruntime session) -- _voice_cache keeps one loaded
    PiperVoice per voice_id for the process's lifetime so repeated
    reads of the same voice don't repay that cost each time.
    """
    voice = _get_cached_voice(voice_id)
    from piper import SynthesisConfig

    config = SynthesisConfig(length_scale=length_scale)
    chunks = list(voice.synthesize(text, config))
    if not chunks:
        return b"", voice.config.sample_rate, 2, 1, []

    audio = b"".join(c.audio_int16_bytes for c in chunks)
    first = chunks[0]
    chunk_sample_counts = [
        len(c.audio_int16_bytes) // (c.sample_width * c.sample_channels) for c in chunks
    ]
    return audio, first.sample_rate, first.sample_width, first.sample_channels, chunk_sample_counts
