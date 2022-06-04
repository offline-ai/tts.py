import asyncio
import shutil
import shlex

from .tts_base import TTSBase, Voice, VoicesIterable
from ..logger import LOGGER as _LOGGER

class EspeakTTS(TTSBase):
    """Wraps eSpeak (http://espeak.sourceforge.net)"""

    name: str = "espeak"

    def __init__(self):
        self.espeak_prog = "espeak-ng"
        if not shutil.which(self.espeak_prog):
            self.espeak_prog = "espeak"

    async def _voices(self) -> VoicesIterable:
        """Get list of available voices."""
        espeak_cmd = [self.espeak_prog, "--voices"]
        _LOGGER.debug(espeak_cmd)

        proc = await asyncio.create_subprocess_exec(
            *espeak_cmd, stdout=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()

        voices_lines = stdout.decode().splitlines()
        first_line = True
        for line in voices_lines:
            if first_line:
                first_line = False
                continue

            parts = line.split()
            locale = parts[1]
            language = locale.split("-", maxsplit=1)[0]
            if locale == "cmn":
                locale = "zh-cmn"
                language = "zh"
            if locale == "yue":
                locale = "zh-yue"
                language = "zh"

            yield Voice(
                id=locale,
                gender=parts[2][-1],
                name=parts[3],
                locale=locale,
                language=language,
            )

    async def say(self, text: str, voice_id: str, **kwargs) -> bytes:
        """Speak text as WAV."""
        espeak_cmd = [
            self.espeak_prog,
            "-v",
            shlex.quote(str(voice_id)),
            "--stdout",
            shlex.quote(text),
        ]
        _LOGGER.debug(espeak_cmd)

        proc = await asyncio.create_subprocess_exec(
            *espeak_cmd, stdout=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        return stdout
