"""Mints one-use ephemeral tokens for the browser's direct Gemini Live connection.

The whole session config (model, system instruction, voice, VAD, transcription)
is locked into the token server-side, so the browser -- which only ever sees
the token, never the API key -- cannot change the tutor's prompt.
"""

import datetime as dt
from dataclasses import dataclass

from google import genai
from google.genai import types

from app.config import Settings
from app.prompts import TutorPrompt
from app.schemas import VoiceSettings

LIVE_WS_URL = (
    "wss://generativelanguage.googleapis.com/ws/"
    "google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContentConstrained"
)


END_SESSION_TOOL = types.FunctionDeclaration(
    name="end_session",
    description=(
        "Hang up and end today's practice session. Like a goodbye between two people, BOTH "
        "sides must say goodbye first: call this only in the turn AFTER he has said goodbye "
        "back to you (or when he himself said goodbye / asked to stop). NEVER call it in the "
        "same turn as your own goodbye -- say goodbye, then wait for his reply."
    ),
    # NON_BLOCKING: she can finish her goodbye while the app handles the hang-up.
    behavior=types.Behavior.NON_BLOCKING,
)


@dataclass(frozen=True)
class LiveToken:
    token: str
    model: str
    ws_url: str
    expires_at: dt.datetime


def build_live_config(
    settings: Settings,
    prompt: TutorPrompt,
    resume_handle: str | None = None,
    vocabulary: list[str] | None = None,
    voice: VoiceSettings | None = None,
) -> types.LiveConnectConfig:
    voice = voice or VoiceSettings(silence_ms=settings.vad_silence_ms)
    # No language_code here: native-audio models ignore it ("they automatically choose the
    # language"); Hebrew is enforced by the system instruction's LANGUAGE rule instead.
    speech = types.SpeechConfig()
    if settings.live_voice:
        speech.voice_config = types.VoiceConfig(
            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=settings.live_voice)
        )
    # The language hint DOES apply to transcription (his speech and hers as captions).
    # VERBATIM (default) keeps hesitations and false starts -- useful for later analysis.
    transcription = types.AudioTranscriptionConfig(
        language_codes=[settings.live_language],
        custom_vocabulary=vocabulary or None,  # his names and places (from the private profile)
    )
    return types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO],
        system_instruction=types.Content(parts=[types.Part(text=prompt.text)]),
        speech_config=speech,
        input_audio_transcription=transcription,
        output_audio_transcription=transcription,
        realtime_input_config=types.RealtimeInputConfig(
            automatic_activity_detection=(
                # Tap-to-talk (09): the browser marks his turn (activityStart / activityEnd).
                types.AutomaticActivityDetection(disabled=True) if voice.tap_to_talk else
                types.AutomaticActivityDetection(
                    # Catch the start of even quiet speech, but be slow to decide he's done:
                    # low end sensitivity + a long silence window so he isn't cut off mid-thought.
                    # ...unless the noise filter is at its strictest (09): then noise matters more.
                    start_of_speech_sensitivity=(types.StartSensitivity.START_SENSITIVITY_LOW if voice.noise_level >= 3
                                                 else types.StartSensitivity.START_SENSITIVITY_HIGH),
                    end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_LOW,
                    # per account, from the caregiver page; 0 = not set: Gemini's own end-of-turn timing
                    silence_duration_ms=voice.silence_ms or None,
                )
            )
        ),
        # The handle must be baked into the token: the token's locked config overrides
        # anything the browser puts in its setup message.
        session_resumption=types.SessionResumptionConfig(handle=resume_handle),
        context_window_compression=types.ContextWindowCompressionConfig(
            sliding_window=types.SlidingWindow()
        ),
        # The live model only talks -- its single tool is hanging up, so he never has to
        # work out how to end the call. All other tool use lives in the agent calls.
        tools=[types.Tool(function_declarations=[END_SESSION_TOOL])],
    )


def create_live_token(
    settings: Settings,
    prompt: TutorPrompt,
    client: genai.Client,
    now: dt.datetime | None = None,
    resume_handle: str | None = None,
    vocabulary: list[str] | None = None,
    voice: VoiceSettings | None = None,
) -> LiveToken:
    now = now or dt.datetime.now(dt.timezone.utc)
    expires_at = now + dt.timedelta(minutes=settings.token_ttl_minutes)
    token = client.auth_tokens.create(
        config=types.CreateAuthTokenConfig(
            uses=1,
            expire_time=expires_at,
            new_session_expire_time=now + dt.timedelta(minutes=1),
            live_connect_constraints=types.LiveConnectConstraints(
                model=settings.live_model,
                config=build_live_config(settings, prompt, resume_handle, vocabulary, voice),
            ),
        )
    )
    return LiveToken(
        token=token.name, model=settings.live_model, ws_url=LIVE_WS_URL, expires_at=expires_at
    )
