#!/usr/bin/env python3
"""OfflineTTS API Blueprint"""
import dataclasses
import typing
from pathlib import Path
from urllib.parse import parse_qs

from quart import (
    Blueprint,
    Response,
    jsonify as _jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
)
from swagger_ui import api_doc

from .tts.tts_base import TTSBase, LOGGER as _LOGGER
from offlinetts.to_wav import (
    text_to_wav,
)

def clean_nones(value):
    """
    Recursively remove all None values from dictionaries and lists, and returns
    the result as a new dictionary or list.
    """
    if isinstance(value, list):
        return [clean_nones(x) for x in value if x is not None]
    elif isinstance(value, dict):
        return {
            key: clean_nones(val)
            for key, val in value.items()
            if val is not None
        }
    else:
        return value

def jsonify(data, **kwargs) -> "Response":
    data = clean_nones(data)
    return _jsonify(data, **kwargs)

_DIR = Path(__file__).parent
_VERSION = (_DIR / "VERSION").read_text().strip()

def get_blueprint(app) -> Blueprint:

    blueprint = Blueprint('api', __name__)

    @blueprint.route("/api/voices")
    async def app_voices() -> Response:
        """Get available voices."""
        languages = set(request.args.getlist("language"))
        locales = set(request.args.getlist("locale"))
        genders = set(request.args.getlist("gender"))
        tts_names = set(request.args.getlist("tts_name"))

        voices: typing.Dict[str, typing.Any] = {}
        for tts_name, tts in TTSBase._TTSList.items():
            if tts_names and (tts_name not in tts_names):
                # Skip TTS
                continue

            async for voice in tts.voices():
                if languages and (voice.language not in languages):
                    # Skip language
                    continue

                if locales and (voice.locale not in locales):
                    # Skip locale
                    continue

                if genders and (voice.gender not in genders):
                    # Skip gender
                    continue

                # Prepend TTS system name to voice ID
                full_id = f"{tts_name}:{voice.id}"
                voices[full_id] = dataclasses.asdict(voice)

                # Add TTS name
                voices[full_id]["tts_name"] = tts_name

        return jsonify(voices)


    @blueprint.route("/api/languages")
    async def app_languages() -> Response:
        """Get available languages."""
        tts_names = set(request.args.getlist("tts_name"))
        languages: typing.Set[str] = set()

        for tts_name, tts in TTSBase._TTSList.items():
            if tts_names and (tts_name not in tts_names):
                # Skip TTS
                continue

            async for voice in tts.voices():
                languages.add(voice.language)

        return jsonify(list(languages))


    def convert_bool(bool_str: str) -> bool:
        """Convert HTML input string to boolean"""
        return bool_str.strip().lower() in {"true", "yes", "on", "1", "enable"}


    @blueprint.route("/api/tts", methods=["GET", "POST"])
    async def app_say() -> Response:
        """Speak text to WAV."""
        lang = request.args.get("lang", "en")

        voice = request.args.get("voice", "")
        # assert voice, "No voice provided"

        # cache=false or cache=0 disables WAV cache
        use_cache = convert_bool(request.args.get("cache", "false"))

        # Text can come from POST body or GET ?text arg
        if request.method == "POST":
            text = (await request.data).decode()
        else:
            text = request.args.get("text", "")

        assert text, "No text provided"

        speaker_id = str(request.args.get("speakerId", ""))
        if speaker_id and ("#" not in voice):
            voice = f"{voice}#{speaker_id}"

        # SSML settings
        ssml = convert_bool(request.args.get("ssml", "false"))
        ssml_numbers = convert_bool(request.args.get("ssmlNumbers", "true"))
        ssml_dates = convert_bool(request.args.get("ssmlDates", "true"))
        ssml_currency = convert_bool(request.args.get("ssmlCurrency", "true"))

        ssml_args = {
            "verbalize_numbers": ssml_numbers,
            "verbalize_dates": ssml_dates,
            "verbalize_currency": ssml_currency,
        }

        wav_bytes = await text_to_wav(
            text=text,
            voice=voice,
            lang=lang,
            use_cache=use_cache,
            ssml=ssml,
            ssml_args=ssml_args,
        )

        return Response(wav_bytes, mimetype="audio/wav")


    # -----------------------------------------------------------------------------

    # MaryTTS compatibility layer
    @blueprint.route("/process", methods=["GET", "POST"])
    async def api_process():
        """MaryTTS-compatible /process endpoint"""
        if request.method == "POST":
            data = parse_qs((await request.data).decode())
            text = data.get("INPUT_TEXT", [""])[0]
            voice = data.get("VOICE", [""])[0]
        else:
            text = request.args.get("INPUT_TEXT", "")
            voice = request.args.get("VOICE", "")
        ssml = text and text[0] == "<"
        _LOGGER.debug(text)
        wav_bytes = await text_to_wav(
            text,
            voice,
            ssml=ssml,
        )

        return Response(wav_bytes, mimetype="audio/wav")


    @blueprint.route("/voices", methods=["GET"])
    async def api_voices():
        """MaryTTS-compatible /voices endpoint"""
        voices = []
        for tts_name, tts in _TTS.items():
            async for voice in tts.voices():
                # Prepend TTS system name to voice ID
                full_id = f"{tts_name}:{voice.id}"
                voices.append(full_id)

        return "\n".join(voices)


    @blueprint.route("/version", methods=["GET"])
    async def api_version():
        """MaryTTS-compatible /version endpoint"""
        return _VERSION

    # Swagger UI
    api_doc(app, config_path="offlinetts/swagger.yaml", url_prefix="/api", title="OfflineTTS")


    @blueprint.errorhandler(Exception)
    async def handle_error(err) -> typing.Tuple[str, int]:
        """Return error as text."""
        _LOGGER.exception(err)
        return (f"{err.__class__.__name__}: {err}", 500)

    return blueprint
