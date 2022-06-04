import logging

LOG_LEVEL = logging.INFO

LOGGER = logging.getLogger("tts")

def setLogLevel(logLevel):
  if type(logLevel) is str:
    logLevel = logging._nameToLevel.get(logLevel)
  if logLevel:
    LOG_LEVEL = logLevel
  logging.basicConfig(level=LOG_LEVEL)
  return LOG_LEVEL
