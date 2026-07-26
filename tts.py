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


# Real, deliberate calibration (Devin, 2026-07-25: "make the default
# audio reading voice slower, more natural pace... do this for all
# voices. that is '1.0x' speed, base other speeds around that once we
# get a good natural default reading cadence"). Piper's own native
# length_scale=1.0 reads noticeably rushed for continuous-prose
# reading -- a common report for VITS-family TTS models at their raw
# default rate, not specific to any one voice here. This shifts what
# the UI calls "1.0x" to a slower, more natural pace; every other
# speed preset (0.75x/1.25x/1.5x/2.0x, see slate.py's Speed menu)
# scales proportionally FROM this new baseline via speed_to_length_
# scale() below, not from Piper's raw default -- the whole speed
# range moves together as one calibrated unit, applied uniformly to
# every voice in VOICES (nothing here is voice-specific).
#
# NOT tuned by ear here -- confirmed live: this dev environment (WSL2)
# has zero real audio output devices (sd.query_devices() returns an
# empty list). 1.15 is a reasonable starting point (VITS-family models
# commonly read ~10-20% too fast at their raw default), not a value
# verified against real playback -- needs Devin's live listen on real
# Windows hardware and a follow-up adjustment if it's still off.
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
    real speed control (>1 slower, <1 faster) -- confirmed live via
    SynthesisConfig's actual signature, not guessed.

    chunk_sample_counts (added 2026-07-26, real "TTS indicator too fast"
    fix) is the number of audio samples EACH sentence-chunk contributed,
    in order -- real, measured per-sentence durations for
    _update_tts_highlight (slate.py) to calibrate the read-along
    highlight per sentence instead of assuming one uniform character
    rate across the whole page. True per-PHONEME alignment
    (voice.synthesize(..., include_alignments=True)) was investigated
    first and ruled out: confirmed live against the actual bundled/
    downloadable voice models that the ONNX session returns only one
    output tensor (audio) -- these specific voice exports were never
    built with the duration-output branch alignment needs, not
    something a config flag can turn on. Per-sentence chunk boundaries
    are the real data that IS available without that.

    Real perf finding, not assumed: PiperVoice.load() alone takes
    ~1.2s (loading the ~60MB ONNX model + building an onnxruntime
    session) -- reloading it on every single call, as this function
    originally did, meant every "Read this page" repaid that full cost
    even for the SAME voice back-to-back. _voice_cache keeps one
    loaded PiperVoice per voice_id for the process's lifetime instead.
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
