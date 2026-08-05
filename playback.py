"""Playback for synthesized Read Aloud audio, via sounddevice.

Real gap: sounddevice has no built-in pause/resume, only start/stop of
a stream. Implemented here with a streaming callback that tracks a
paused flag and the current sample position directly -- pause holds
the position (resume continues from exactly there), not just a stop
that would lose it.

NOT live-verified against real audio hardware -- WSL2 exposes zero audio
output devices regardless of libportaudio2 install state, a WSL/
passthrough limitation, not a code issue. The callback's own position/
pause logic is still fully tested by calling it directly with synthetic
buffers, bypassing the need for a real device.
"""
import numpy as np

# Guarded the same way tts.py guards `import piper` -- sounddevice is
# excluded from this build (Slate.spec) whenever Read Aloud itself is
# (tts.ENGINE_AVAILABLE gates every real call site that constructs a
# Player and invokes play()/_callback()/stop(), all in slate.py). Player
# itself is instantiated unconditionally at app startup though (a real,
# separate object-existence vs. feature-availability split from tts.py's
# own pattern), so THIS import must survive sounddevice's absence -- sd
# only gets touched inside methods those call sites already never reach
# when the engine is unavailable. An unguarded import here crashed the
# whole app at launch once sounddevice actually stopped being bundled
# (real regression, caught live 2026-08-03: "ModuleNotFoundError: No
# module named 'sounddevice'" at slate.py's own top-level import chain,
# before any gating logic ever ran).
try:
    import sounddevice as sd
except ImportError:
    sd = None


class Player:
    def __init__(self):
        self._stream = None
        self._audio = None  # numpy int16 array, shape (n_samples, channels)
        self._position = 0
        self._paused = False
        self._sample_rate = None
        self._channels = 1

    def load(self, audio_int16_bytes: bytes, sample_rate: int, channels: int = 1):
        """Stops any current playback and loads new audio, ready to
        play from the start."""
        self.stop()
        samples = np.frombuffer(audio_int16_bytes, dtype=np.int16)
        self._audio = samples.reshape(-1, channels)
        self._position = 0
        self._sample_rate = sample_rate
        self._channels = channels

    def _callback(self, outdata, frames, time_info, status):
        """The real playback state machine. Public so tests can call it
        directly with synthetic (outdata, frames) without a real
        audio device -- see module docstring."""
        if self._paused or self._audio is None:
            outdata[:] = 0
            return
        remaining = len(self._audio) - self._position
        if remaining <= 0:
            outdata[:] = 0
            raise sd.CallbackStop()
        n = min(frames, remaining)
        outdata[:n] = self._audio[self._position:self._position + n]
        if n < frames:
            outdata[n:] = 0
        self._position += n

    def play(self):
        """(Re)starts playback from the current position -- the same
        call resumes after pause() (position was held, not reset) or
        starts fresh after load()."""
        if self._audio is None:
            return
        self._paused = False
        if self._stream is not None and not self._stream.active:
            # Reaching end-of-audio raises sd.CallbackStop() from inside
            # _callback, which stops the PortAudio stream but does NOT
            # close it. Opening a second OutputStream on top of a still-
            # open native handle crashes on Windows audio backends
            # (WASAPI/DirectSound) -- always release a dead stream
            # before opening a new one, same as stop() already does.
            self._stream.close()
            self._stream = None
        if self._stream is None:
            self._stream = sd.OutputStream(
                samplerate=self._sample_rate,
                channels=self._channels,
                dtype="int16",
                callback=self._callback,
            )
            self._stream.start()

    def pause(self):
        """Holds the current position -- play() resumes from exactly
        here, real pause/resume, not stop-and-restart-from-zero."""
        self._paused = True

    def stop(self):
        """Unlike pause(), resets position to the start."""
        self._paused = False
        self._position = 0
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def is_playing(self) -> bool:
        return self._stream is not None and self._stream.active and not self._paused

    def is_paused(self) -> bool:
        """Distinct from "not is_playing()" -- that's also true right
        after playback reaches the natural end of the audio (no more
        samples left, _callback's own sd.CallbackStop() path), which
        is NOT a pause. Slate's "read entire document" auto-advance
        (do_read_document, slate.py) needs to tell those two apart:
        pause() should never trigger advancing to the next page,
        reaching the real end of a page's audio should."""
        return self._paused

    def has_audio(self) -> bool:
        """Something is loaded (playing, paused, or freshly load()ed
        and not yet played) -- distinct from is_playing(), which is
        only True while actively producing sound. Needed to decide
        whether to start a fresh read or just toggle pause/resume."""
        return self._audio is not None

    @property
    def progress(self) -> float:
        """0.0-1.0 fraction of the loaded audio already played, for a
        real progress indicator -- 0.0 if nothing is loaded."""
        if self._audio is None or len(self._audio) == 0:
            return 0.0
        return self._position / len(self._audio)
