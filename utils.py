import typing
import json
import logging
import shutil

from .to_wav import setCacheDir

from .tts import (
  TTSBase,
  CoquiTTS,
  EspeakTTS,
)

from .logger import LOGGER as _LOGGER

def initTTS(args, _DIR):

  _VOICES_DIR = _DIR / "voices"

  TTSBase.langs = args.languages.split(',')

  # Get default language
  _DEFAULT_LANGUAGE = None
  _path = _DIR / "LANGUAGE"
  if _path.is_file():
      _DEFAULT_LANGUAGE = _path.read_text().strip()

  if not _DEFAULT_LANGUAGE:
      if args.language:
          _DEFAULT_LANGUAGE = args.language
      elif TTSBase.langs:
          _DEFAULT_LANGUAGE = TTSBase.langs[0]

      if not _DEFAULT_LANGUAGE:
          _DEFAULT_LANGUAGE = "en"

  _LOGGER.debug("Default language: %s", _DEFAULT_LANGUAGE)
  TTSBase.default_lang = _DEFAULT_LANGUAGE

  _PREFERRED_VOICES: typing.Optional[typing.Dict[str, typing.Any]] = None
  _path = _DIR / "PREFERRED_VOICES"
  if _path.is_file():
      _s = _path.read_text().strip()
      if _s:
          try:
              _PREFERRED_VOICES = json.loads(_s)
          except Exception as e:
              _LOGGER.error("Load PREFERRED_VOICES Error: %s", e)
  if type(_PREFERRED_VOICES) is list:
      for item in _PREFERRED_VOICES: # type: ignore
          if type(item) is str:
              lang, voice = item.split(' ')
              TTSBase.voice_aliases[lang].insert(0, voice)
          elif type(item) is dict:
              TTSBase.voice_aliases[item.get("lang")].insert(0, item.get("voice")) # type: ignore
  if args.preferred_voice:
      for pref_lang, pref_voice in args.preferred_voice:
          TTSBase.voice_aliases[pref_lang].insert(0, pref_voice)

  _LOGGER.debug("preferred_voices: %s", json.dumps(TTSBase.voice_aliases))

  setCacheDir(args.cache)

  # espeak
  if (not args.no_espeak) and shutil.which("espeak-ng"):
      EspeakTTS.register()
  # Coqui-TTS
  if not args.no_coqui:
      try:
          import TTS  # noqa: F401

          coqui_available = True
      except Exception:
          coqui_available = False

          if log_level <= logging.DEBUG:
              _LOGGER.exception("coqui-tts")

      if coqui_available:
          CoquiTTS.register(models_dir=(_VOICES_DIR / "coqui-tts"))

  # asyncio.run(_init())

  _LOGGER.debug("Loaded TTS systems: %s", ", ".join(TTSBase._TTSList.keys()))

  return { "defaultLang": _DEFAULT_LANGUAGE, "TTSList": TTSBase._TTSList}
