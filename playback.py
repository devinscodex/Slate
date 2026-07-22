"""Playback for synthesized Read Aloud audio, via sounddevice.

Real gap: sounddevice has no built-in pause/resume, only start/stop of
a stream. Implemented here with a streaming callback that tracks a
paused flag and the current sample position directly -- pause holds
the position (resume continues from exactly there), not just a stop
that would lose it.

NOT live-verified against real audio hardware: this dev environment
(WSL2) exposes zero audio output devices even with libportaudio2
installed (confirmed live: sd.query_devices() returns an empty list) --
a WSL/passthrough limitation, not something in this code. The real
Windows deployment target has no such gap (sounddevice's wheel bundles
PortAudio with normal native device access). The callback's own
position/pause LOGIC is still fully real-tested here, by calling it
directly with synthetic buffers -- same technique already used for the
Windows-only font-registry and DWM-titlebar code that can't be
exercised on this box either.
"""
import numpy as np
import sounddevice as sd


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
        if self._stream is None or not self._stream.active:
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

    @property
    def progress(self) -> float:
        """0.0-1.0 fraction of the loaded audio already played, for a
        real progress indicator -- 0.0 if nothing is loaded."""
        if self._audio is None or len(self._audio) == 0:
            return 0.0
        return self._position / len(self._audio)
