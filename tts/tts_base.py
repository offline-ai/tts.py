"""Text to speech wrappers for OpenTTS"""
from __future__ import annotations
import asyncio
import functools
import io
import json
import logging
import itertools
import platform
import re
import shlex
import shutil
import tempfile
import typing
from collections import defaultdict
from abc import ABCMeta
from dataclasses import dataclass
from pathlib import Path
from zipfile import ZipFile

from ..logger import LOGGER

_LOOP = asyncio.get_event_loop()

# -----------------------------------------------------------------------------

@dataclass
class Voice:
    """Single TTS voice."""

    id: str
    name: str
    gender: str
    language: str
    locale: str
    tag: typing.Optional[typing.Dict[str, typing.Any]] = None
    multispeaker: bool = False
    speakers: typing.Optional[typing.Dict[str, int]] = None


VoicesIterable = typing.AsyncGenerator[Voice, None]

class TTSException(Exception):
    pass

class TTSRegisterException(Exception):
    pass

class TTSBase(metaclass=ABCMeta):
    """Base class of TTS systems."""

    # the allowed languages
    langs: typing.List[str] = []
    default_lang: str = 'en'
    voice_aliases: typing.Dict[str, typing.List[typing.Any]] = defaultdict(list)
    _TTSList: typing.Dict[str, TTSBase] = {}
    # the TTS Engine Name
    name: str = ''
    # the models dir
    models_dir: typing.Optional[Path] = None

    @classmethod
    def get_preferred_voice(Cls, lang: str) -> str:
        LOGGER.debug("voice_aliases: %s", str(Cls.voice_aliases))
        voices = Cls.voice_aliases.get(lang)
        result = ""
        if voices:
            result = voices[0]
        return result
    @classmethod
    def create(Cls, **kwargs):
        """models_dir"""
        instance = Cls(**kwargs)
        async_run_and_get(instance._init())
        return instance

    async def _init(self):
        async for voice in self.voices():
            self.add_voice_aliases(voice)

    async def _voices(self) -> VoicesIterable:
        """Get list of available voices."""
        yield Voice("", "", "", "", "")

    async def voices(self) -> VoicesIterable:
        """Get list of allowed voices."""
        voices = self._voices()
        async for voice in voices:
            if voice.language in TTSBase.langs:
                yield voice

    async def say(self, text: str, voice_id: str, **kwargs) -> bytes:
        """Speak text as WAV."""
        return bytes()

    @classmethod
    def add_voice_aliases(Cls, voice: typing.Union[str, Voice], lang: str = ''):
        if isinstance(voice, Voice):
            if not lang:
                lang = voice.language
            voice = Cls.name + ':' + voice.id

        if lang and voice:
            aliases = Cls.voice_aliases[lang]
            if not aliases:
                aliases = Cls.voice_aliases[lang] = []
            if voice not in aliases:
                # type: ignore
                aliases.append(voice)

    @classmethod
    def register(TTSClass: typing.Type[TTSBase], name: typing.Optional[str] = None, **kwargs):
        _TTSList = TTSBase._TTSList
        if not name:
            name = TTSClass.name
        name = name.lower()
        obj = _TTSList.get(name)
        if obj is None:
            obj = TTSClass.create(**kwargs)
            # await obj._init()
            _TTSList[name] = obj
        else:
            raise TTSRegisterException('already exists')
        return obj

    @staticmethod
    def get(name: str) -> TTSBase:
        return TTSBase._TTSList.get(name.lower()) # type: ignore

    @staticmethod
    def unregister(name: str) -> typing.Optional[TTSBase]:
        return TTSBase._TTSList.pop(name, None)

    @staticmethod
    def resolve_voice(voice: str, fallback_voice: typing.Optional[str] = None) -> str:
        """Resolve a voice or language based on aliases"""
        _VOICE_ALIASES = TTSBase.voice_aliases
        _TTSList = TTSBase._TTSList
        original_voice = voice

        if "#" in voice:
            # Remove speaker id
            # tts:voice#speaker_id
            voice, _speaker_id = voice.split("#", maxsplit=1)

        # Resolve voices in order:
        # 1. Aliases in order of preference
        # 2. fallback voice provided
        # 3. Original voice
        # 4. espeak voice

        fallback_voices = []
        if fallback_voice is not None:
            fallback_voices.append(fallback_voice)

        fallback_voices.append(original_voice)

        alias_key = voice.lower()
        if alias_key not in _VOICE_ALIASES:
            # en-US -> en
            alias_key = re.split(r"[-_]", alias_key, maxsplit=1)[0]

        if ":" not in voice:
            fallback_voices.append(f"espeak:{voice}")

        for preferred_voice in itertools.chain(_VOICE_ALIASES[alias_key], fallback_voices):
            tts, _voice_id = preferred_voice.split(":", maxsplit=1)
            if tts in _TTSList:
                # If TTS system is loaded, assume voice will be present
                return preferred_voice

        raise ValueError(f"Cannot resolve voice: {voice}")

def async_run_and_get(coro):
    task = _LOOP.create_task(coro)
    # pending = asyncio.all_tasks(loop)
    _LOOP.run_until_complete(task)

    # asyncio.get_running_loop().run_until_complete(task)
    return task.result()
