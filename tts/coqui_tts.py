import asyncio
import functools
import io
import json
import re
import typing
from pathlib import Path

from .tts_base import TTSBase, Voice, VoicesIterable, LOGGER

class CoquiTTS(TTSBase):
    """Wraps Coqui TTS (https://github.com/coqui-ai/TTS)"""

    name: str = "tts"

    def __init__(self, models_dir: typing.Union[str, Path]):
        self.models_dir = Path(models_dir)

        self.synthesizers: typing.Dict[str, typing.Any] = {}

        # Run text to speech
        from TTS.utils.synthesizer import Synthesizer
        self.Synthesizer = Synthesizer

        self.tts_voices = {
            # en
            "en_vctk": Voice(
                id="en_vctk",
                name="vctk",
                locale="en-us",
                language="en",
                gender="MF",
                multispeaker=True,
            ),

            # ja
            "ja_kokoro": Voice(
                id="ja_kokoro",
                name="kokoro",
                locale="ja-ja",
                language="ja",
                gender="M",
            ),

            # zh
            "zh_baker": Voice(
                id="zh_baker", name="baker", locale="zh-cn", language="zh", gender="F",
            ),
        }

    def getSynthesizer(self, id: str) -> typing.Any:
        synthesizer = self.synthesizers.get(id)
        if synthesizer is None:
            voice_dir = self.models_dir / id # type: ignore
            vocoder_dir = voice_dir / "vocoder"

            vocoder_checkpoint = ""
            vocoder_config = ""

            if vocoder_dir.is_dir():
                vocoder_checkpoint = str(vocoder_dir / "model_file.pth.tar")
                vocoder_config = str(vocoder_dir / "config.json")

            tts_speakers_file = ""
            speakers_json_path = voice_dir / "speaker_ids.json"
            if speakers_json_path.is_file():
                tts_speakers_file = str(speakers_json_path)

            synthesizer = self.Synthesizer(
                tts_checkpoint=str(voice_dir / "model_file.pth.tar"),
                tts_config_path=str(voice_dir / "config.json"),
                vocoder_checkpoint=vocoder_checkpoint,
                vocoder_config=vocoder_config,
                tts_speakers_file=tts_speakers_file,
            )

            self.synthesizers[id] = synthesizer
        return synthesizer

    async def _voices(self) -> VoicesIterable:
        """Get list of available voices."""
        for voice in self.tts_voices.values():
            model_path = self.models_dir / voice.id # type: ignore
            if model_path.exists():
                if voice.multispeaker and (voice.speakers is None):
                    # Load speaker ids
                    speaker_ids_path = model_path / "speaker_ids.json"
                    if speaker_ids_path.is_file():
                        with open(
                            speaker_ids_path, "r", encoding="utf-8"
                        ) as speaker_ids_file:
                            voice.speakers = json.load(speaker_ids_file)

                yield voice

    async def say(self, text: str, voice_id: str, **kwargs) -> bytes:
        """Speak text as WAV."""
        speaker_id = kwargs.get("speaker_id")

        voice = self.tts_voices.get(voice_id)
        assert voice is not None, f"No Coqui-TTS voice {voice_id}"

        if (voice.multispeaker) and (
            (isinstance(speaker_id, str) and not speaker_id) or (speaker_id is None)
        ):
            if voice.speakers:
                # First speaker name
                speaker_id = next(iter(voice.speakers))
            else:
                # First speaker id
                speaker_id = 0

        synthesizer = self.getSynthesizer(voice.id)

        assert synthesizer is not None

        # Ensure full stop
        text = text.strip()
        if text:
            if voice.id == "zh_baker":
                def mReplacer(m):
                    char = m.group(1)
                    if char == '.'  or char == '．':
                        char = '。'
                    elif ord(char) < 255 :
                        char = chr(ord(m.group(1))+0xfee0)
                    return char
                # merge multi punctuation into one punctuation
                text = re.sub(r'([.!?。！？．])+', mReplacer, text)
                if (text[-1] not in {"。", "？", "！"}):
                    text = text + "。"
            elif (text[-1] not in {".", "?", "!"}):
                text = text + "."

        LOGGER.debug("Prepared Say: %s", text)

        # Run asynchronously in executor
        loop = asyncio.get_running_loop()
        audio = await loop.run_in_executor(
            None,
            functools.partial(
                synthesizer.tts, text, speaker_name=speaker_id,  # type: ignore
            ),
        )

        with io.BytesIO() as wav_io:
            synthesizer.save_wav(audio, wav_io)  # type: ignore

            return wav_io.getvalue()
