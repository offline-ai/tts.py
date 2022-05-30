# Offline TTS


## Credit

* [Coqui-TTS](http://coqui.ai/)
* [ESpeaker](http://espeak.sourceforge.net)
* Main Inspired by [OpenTTS](https://github.com/synesthesiam/opentts).
  * Great Thanks. Without [OpenTTS](https://github.com/synesthesiam/opentts) there would be no Offline TTS.

## TODO

* [X] Upgrade Coqui-TTS from 0.3.1 to latest version 0.7.0dev
  * [X] fix: Check if optional dependencies are installed before loading ZH/JA phonememizer
  * [X] Remove matplotlib (It is only useful during the train analysis phase).
  * [X] Optimal Coqui-TTS  Models Size
  * [ ] Optimal Coqui-TTS  Models on Embedded device
* [X] Espeak Chinese locale missing
* [X] Show used languages only
* [X] Can not use [SSML](#ssml) on HA
* [X] Can not modify options on HA for the `/data/options.json` cannot read via common user.
* [ ] Add preferred voice for language option
