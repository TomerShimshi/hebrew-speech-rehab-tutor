import datetime as dt
from types import SimpleNamespace

from google.genai import types

from app.config import Settings
from app.live_token import LIVE_WS_URL, create_live_token
from app.prompts import render_tutor_prompt

NOW = dt.datetime(2026, 9, 29, 12, 0, tzinfo=dt.timezone.utc)


class FakeAuthTokens:
    def __init__(self):
        self.config = None

    def create(self, *, config):
        self.config = config
        return SimpleNamespace(name="auth_tokens/fake-ephemeral")


def _mint(**settings_overrides):
    settings = Settings(gemini_api_key="real-secret-key", **settings_overrides)
    client = SimpleNamespace(auth_tokens=FakeAuthTokens())
    prompt = render_tutor_prompt(patient_profile="PROFILE-MARKER")
    live = create_live_token(settings, prompt, client, now=NOW)
    return live, client.auth_tokens.config


def test_token_is_single_use_and_short_lived():
    live, config = _mint()
    assert live.token == "auth_tokens/fake-ephemeral"
    assert live.ws_url == LIVE_WS_URL
    assert config.uses == 1
    assert config.expire_time == NOW + dt.timedelta(minutes=30)
    assert config.new_session_expire_time == NOW + dt.timedelta(minutes=1)


def test_config_locks_prompt_audio_transcription_and_vad():
    _, config = _mint(vad_silence_ms=5000)
    constraints = config.live_connect_constraints
    assert constraints.model == "gemini-3.8-live"
    live_config = constraints.config
    assert "PROFILE-MARKER" in live_config.system_instruction.parts[0].text
    assert live_config.response_modalities == [types.Modality.AUDIO]
    assert live_config.input_audio_transcription.language_codes == ["he-IL"]
    assert live_config.output_audio_transcription is not None
    vad = live_config.realtime_input_config.automatic_activity_detection
    assert vad.silence_duration_ms == 5000
    assert vad.end_of_speech_sensitivity == types.EndSensitivity.END_SENSITIVITY_LOW
    assert live_config.session_resumption is not None


def test_live_models_only_tool_is_end_session():
    _, config = _mint()
    tools = config.live_connect_constraints.config.tools
    names = [fd.name for tool in tools for fd in tool.function_declarations]
    assert names == ["end_session"]


def test_voice_is_pinned_and_optional():
    _, config = _mint()
    voice = config.live_connect_constraints.config.speech_config.voice_config
    assert voice.prebuilt_voice_config.voice_name == "Kore"
    _, config = _mint(live_voice=None)
    assert config.live_connect_constraints.config.speech_config.voice_config is None


def test_vocabulary_biases_transcription():
    settings = Settings(gemini_api_key="k")
    client = SimpleNamespace(auth_tokens=FakeAuthTokens())
    prompt = render_tutor_prompt()
    create_live_token(settings, prompt, client, now=NOW, vocabulary=["ראש פינה", "כנרת"])
    live_config = client.auth_tokens.config.live_connect_constraints.config
    assert live_config.input_audio_transcription.custom_vocabulary == ["ראש פינה", "כנרת"]
    create_live_token(settings, prompt, client, now=NOW)
    live_config = client.auth_tokens.config.live_connect_constraints.config
    assert live_config.input_audio_transcription.custom_vocabulary is None
