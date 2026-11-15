"""Per-persona phonon voices: each persona speaks with its own voice.

Override any of them in ~/.hi/.env with VOICE_<PERSONA>=<phonon voice name> (e.g. VOICE_BUTLER=Edwin);
`GET /tts/voices` lists what phonon offers."""

import hi.config as config

DEFAULT_VOICES = {"butler": "Edwin", "term": "Harper", "docs": "Preston", "web": "Freya"}


def voice_for(persona: str | None) -> str | None:
    """The voice for `persona`, or None to use the global TTS_VOICE."""
    if not persona:
        return None
    return config._env.get(f"VOICE_{persona.upper()}") or DEFAULT_VOICES.get(persona)
