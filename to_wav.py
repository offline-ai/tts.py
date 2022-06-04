import asyncio
import re
import typing
import tempfile
import hashlib
import io
import wave
import time
import math
import gruut

from pathlib import Path

from .tts import TTSBase
from .logger import LOGGER as _LOGGER

WAV_AND_SAMPLE_RATE = typing.Tuple[bytes, int]

# Set up WAV cache
_CACHE_DIR: typing.Optional[Path] = None
_CACHE_TEMP_DIR: typing.Optional[tempfile.TemporaryDirectory] = None

def cleanCache():
    # Clean up WAV cache
    if _CACHE_TEMP_DIR is not None:
        _CACHE_TEMP_DIR.cleanup()

def setCacheDir(cache_dir: typing.Optional[typing.Union[str, bool]]):
    if type(cache_dir) is str:
        if cache_dir.lower() in ['true', '1', 't', 'y', 'yes', 'ok']:
            cache_dir = True
        elif cache_dir.lower() in ['false', '0', 'f', 'n', 'no', 'not']:
            cache_dir = None

    if cache_dir is not None:
        if type(cache_dir) == str:
            # User-specified cache directory
            _CACHE_DIR = Path(cache_dir)
        else:
            # Temporary directory
            # pylint: disable=consider-using-with
            _CACHE_TEMP_DIR = tempfile.TemporaryDirectory(prefix="offlinetts_")
            _CACHE_DIR = Path(_CACHE_TEMP_DIR.name)
    else:
        _CACHE_DIR = None       # type: ignore
        _CACHE_TEMP_DIR = None  # type: ignore
    _LOGGER.debug("Caching WAV files in %s", _CACHE_DIR)

def get_cache_key(text: str, voice: str, settings: str = "") -> str:
    """Get hashed WAV name for cache"""
    cache_key_str = f"{text}-{voice}-{settings}"
    return hashlib.sha256(cache_key_str.encode("utf-8")).hexdigest()


async def text_to_wav(
    text: str,
    voice: str,
    lang: str = TTSBase.default_lang,
    vocoder: typing.Optional[str] = None,
    denoiser_strength: typing.Optional[float] = None,
    noise_scale: typing.Optional[float] = None,
    length_scale: typing.Optional[float] = None,
    use_cache: bool = True,
    ssml: bool = False,
    ssml_args: typing.Optional[typing.Dict[str, typing.Any]] = None,
) -> bytes:
    """Runs TTS for each line and accumulates all audio into a single WAV."""
    if not voice:
        voice = TTSBase.get_preferred_voice(lang)
    assert voice, "No voice provided"

    # Look up in cache
    wav_bytes = bytes()
    cache_path: typing.Optional[Path] = None

    if use_cache and (_CACHE_DIR is not None):
        # Ensure unique cache id for different denoiser values
        settings_str = f"denoiser_strength={denoiser_strength};noise_scale={noise_scale};length_scale={length_scale};ssml={ssml}"
        cache_key = get_cache_key(text=text, voice=voice, settings=settings_str)
        cache_path = _CACHE_DIR / f"{cache_key}.wav"
        if cache_path.is_file():
            try:
                _LOGGER.debug("Loading from cache: %s", cache_path)
                wav_bytes = cache_path.read_bytes()
                return wav_bytes
            except Exception:
                # Allow synthesis to proceed if cache fails
                _LOGGER.exception("cache load")

    # -------------------------------------------------------------------------
    # Synthesis
    # -------------------------------------------------------------------------

    # Synthesize text and accumulate into a single WAV file.
    _LOGGER.info("Synthesizing with %s (%s char(s))... ssml:%s", voice, len(text), ssml)
    start_time = time.time()

    if ssml:
        wavs_gen = ssml_to_wavs(
            ssml_text=text,
            default_voice=voice,
            default_lang=lang,
            ssml_args=ssml_args,
            # Larynx settings
            vocoder=vocoder,
            denoiser_strength=denoiser_strength,
            noise_scale=noise_scale,
            length_scale=length_scale,
        )
    else:
        wavs_gen = text_to_wavs(
            text=text,
            voice=voice,
            # Larynx settings
            vocoder=vocoder,
            denoiser_strength=denoiser_strength,
            noise_scale=noise_scale,
            length_scale=length_scale,
        )

    wavs = [result async for result in wavs_gen]
    assert wavs, "No audio returned from synthesis"

    # Final output WAV will use the maximum sample rate
    sample_rates = set(sample_rate for (_wav, sample_rate) in wavs)
    final_sample_rate = max(sample_rates)
    final_sample_width = 2  # bytes (16-bit)
    final_n_channels = 1  # mono

    with io.BytesIO() as final_wav_io:
        final_wav_file: wave.Wave_write = wave.open(final_wav_io, "wb")
        with final_wav_file:
            final_wav_file.setframerate(final_sample_rate)
            final_wav_file.setsampwidth(final_sample_width)
            final_wav_file.setnchannels(final_n_channels)

            # Copy audio from each syntheiszed WAV to the final output.
            # If rate/width/channels do not match, resample with sox.
            for synth_wav_bytes, _synth_sample_rate in wavs:
                with io.BytesIO(synth_wav_bytes) as synth_wav_io:
                    synth_wav_file: wave.Wave_read = wave.open(synth_wav_io, "rb")

                    # Check settings
                    if (
                        (synth_wav_file.getframerate() != final_sample_rate)
                        or (synth_wav_file.getsampwidth() != final_sample_width)
                        or (synth_wav_file.getnchannels() != final_n_channels)
                    ):
                        # Upsample with sox
                        sox_cmd = [
                            "sox",
                            "-t",
                            "wav",
                            "-",
                            "-t",
                            "raw",
                            "-r",
                            str(final_sample_rate),
                            "-b",
                            str(final_sample_width * 8),  # bits
                            "-c",
                            str(final_n_channels),
                            "-",
                        ]
                        _LOGGER.debug(sox_cmd)
                        proc = await asyncio.create_subprocess_exec(
                            *sox_cmd,
                            stdin=asyncio.subprocess.PIPE,
                            stdout=asyncio.subprocess.PIPE,
                        )
                        resampled_raw_bytes, _ = await proc.communicate(
                            input=synth_wav_bytes
                        )
                        final_wav_file.writeframes(resampled_raw_bytes)
                    else:
                        # Settings match, can write frames directly
                        final_wav_file.writeframes(
                            synth_wav_file.readframes(synth_wav_file.getnframes())
                        )

        final_wav_bytes = final_wav_io.getvalue()

    end_time = time.time()
    _LOGGER.debug(
        "Synthesized %s byte(s) in %s second(s)",
        len(final_wav_bytes),
        end_time - start_time,
    )

    if final_wav_bytes and (cache_path is not None):
        try:
            _LOGGER.debug("Writing to cache: %s", cache_path)
            cache_path.write_bytes(final_wav_bytes)
        except Exception:
            # Continue if a cache write fails
            _LOGGER.exception("cache save")

    return final_wav_bytes


async def text_to_wavs(
    text: str, voice: str, **say_args
) -> typing.AsyncIterable[WAV_AND_SAMPLE_RATE]:
    voice = TTSBase.resolve_voice(voice)

    assert ":" in voice, f"Invalid voice: {voice}"
    tts_name, voice_id = voice.split(":", maxsplit=1)
    tts = TTSBase.get(tts_name)
    assert tts, f"No TTS named {tts_name}"

    if "#" in voice_id:
        voice_id, speaker_id = voice_id.split("#", maxsplit=1)
        say_args["speaker_id"] = speaker_id

    # Process by line with single TTS
    for line_index, line in enumerate(text.strip().splitlines()):
        line = line.strip()
        if not line:
            continue

        _LOGGER.debug("Synthesizing line %s: %s", line_index + 1, line)
        line_wav_bytes = await tts.say(line, voice_id, **say_args)

        assert line_wav_bytes, f"No WAV audio from line: {line_index+1}"
        _LOGGER.debug(
            "Got %s WAV byte(s) for line %s", len(line_wav_bytes), line_index + 1,
        )

        with io.BytesIO(line_wav_bytes) as line_wav_io:
            line_wav_file: wave.Wave_read = wave.open(line_wav_io, "rb")
            with line_wav_file:
                yield (line_wav_bytes, line_wav_file.getframerate())


async def ssml_to_wavs(
    ssml_text: str,
    default_lang: str,
    default_voice: str,
    ssml_args: typing.Optional[typing.Dict[str, typing.Any]] = None,
    **say_args,
) -> typing.AsyncIterable[WAV_AND_SAMPLE_RATE]:
    if ssml_args is None:
        ssml_args = {}

    for sent_index, sentence in enumerate(
        gruut.sentences(
            ssml_text,
            lang=default_lang,
            ssml=True,
            explicit_lang=False,
            phonemes=False,
            pos=False,
            **ssml_args,
        )
    ):
        sent_text = sentence.text_with_ws
        if not sent_text.strip():
            # Skip empty sentences
            continue

        sent_voice = None
        if sentence.voice:
            sent_voice = sentence.voice
        elif sentence.lang: # and (sentence.lang != default_lang):
            if default_voice:
                voice = default_voice
                if "#" in voice:
                    voice, _ = default_voice.split("#", maxsplit=1)
                if ":" in voice:
                    _, lang = voice.split(":", maxsplit=1)
                lang = re.split(r"[-_]", lang, maxsplit=1)[0]
                if lang == sentence.lang:
                    sent_voice = default_voice
            if not sent_voice:
                sent_voice = sentence.lang
        else:
            sent_voice = default_voice

        sent_voice = TTSBase.resolve_voice(sent_voice)

        assert ":" in sent_voice, f"Invalid voice format: {sent_voice}"
        tts_name, voice_id = sent_voice.split(":")
        tts = TTSBase.get(tts_name)
        assert tts, f"No TTS named {tts_name}"

        if "#" in voice_id:
            voice_id, speaker_id = voice_id.split("#", maxsplit=1)
            say_args["speaker_id"] = speaker_id
        else:
            # Need to remove speaker id for single speaker voices
            say_args.pop("speaker_id", None)

        _LOGGER.debug(
            "Synthesizing sentence %s with voice %s: %s",
            sent_index + 1,
            sent_voice,
            sent_text.strip(),
        )

        sent_wav_bytes = await tts.say(sent_text, voice_id, **say_args)
        assert sent_wav_bytes, f"No WAV audio from sentence: {sent_text}"
        _LOGGER.debug(
            "Got %s WAV byte(s) for line %s", len(sent_wav_bytes), sent_index + 1,
        )

        # Add WAV bytes and sample rate to list.
        # We will resample everything and append audio at the end.
        with io.BytesIO(sent_wav_bytes) as sent_wav_io:
            sent_wav_file: wave.Wave_read = wave.open(sent_wav_io, "rb")
            with sent_wav_file:
                sample_rate = sent_wav_file.getframerate()
                sample_width = sent_wav_file.getsampwidth()
                n_channels = sent_wav_file.getnchannels()

                # Add pauses from SSML <break> tags
                pause_before_ms = sentence.pause_before_ms
                if sentence.words:
                    # Add pause from first word
                    pause_before_ms += sentence.words[0].pause_before_ms

                if pause_before_ms > 0:
                    pause_before_sec = pause_before_ms / 1000
                    yield (
                        make_silence_wav(
                            pause_before_sec, sample_rate, sample_width, n_channels,
                        ),
                        sample_rate,
                    )

                yield (sent_wav_bytes, sample_rate)

                pause_after_ms = sentence.pause_after_ms
                if sentence.words:
                    # Add pause from last word
                    pause_after_ms += sentence.words[-1].pause_after_ms

                if pause_after_ms > 0:
                    pause_after_sec = pause_after_ms / 1000
                    yield (
                        make_silence_wav(
                            pause_after_sec, sample_rate, sample_width, n_channels,
                        ),
                        sample_rate,
                    )


def make_silence_wav(
    seconds: float, sample_rate: int, sample_width: int, num_channels: int
) -> bytes:
    """Create a WAV file with silence"""
    with io.BytesIO() as wav_io:
        wav_file: wave.Wave_write = wave.open(wav_io, "wb")
        with wav_file:
            wav_file.setframerate(sample_rate)
            wav_file.setsampwidth(sample_width)
            wav_file.setnchannels(num_channels)

            num_zeros = int(
                math.ceil(seconds * sample_rate * sample_width * num_channels)
            )
            wav_file.writeframes(bytes(num_zeros))

        return wav_io.getvalue()
