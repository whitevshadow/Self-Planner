from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Single project env at the repo root, resolved from this file's location so
# settings load identically regardless of the process working directory.
# config.py -> app -> backend -> repo root.
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    # Always load gateway creds from the backend env deterministically.
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+psycopg2://planner:planner@localhost:5432/self_planner"
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "meetings-audio"
    minio_secure: bool = False
    # Transcription runs on the OpenAI-compatible gateway's
    # /v1/audio/transcriptions (reuses LLM creds). There is no local ASR.
    asr_model: str = "whisper-large-v3"
    # Voice reply (text-to-speech) via the gateway's /v1/audio/speech. All choices
    # are settings-driven so the model/voice can be swapped without code changes;
    # tts_model must be one of the gateway's live audio models (see the dashboard).
    tts_provider: str = "gateway"  # "gateway" = /v1/audio/speech; "off" disables voice replies
    tts_model: str = "tts-1"       # gateway audio model id, e.g. an OpenAI-compatible TTS route
    tts_voice: str = "alloy"       # voice name accepted by the chosen model
    tts_format: str = "mp3"        # mp3|opus|aac|flac|wav — mp3 plays everywhere
    max_upload_mb: int = 200
    # Gateway/OpenAI-compatible LLM config
    llm_base_url: str = ""
    llm_api_key: str = ""

    # Back-compat aliases for older root env variable names.
    # If the preferred LLM_* vars are not set, fall back to:
    # - base_URL
    # - OPENAI_API_KEY
    @property
    def llm_base_url_resolved(self) -> str:
        # Support both llm_base_url (LLM_BASE_URL) and legacy base_URL.
        return self.llm_base_url or getattr(self, "base_URL", "")

    @property
    def llm_api_key_resolved(self) -> str:
        # Support both llm_api_key (LLM_API_KEY) and legacy OPENAI_API_KEY.
        return self.llm_api_key or getattr(self, "OPENAI_API_KEY", "")
    llm_model_summary: str = ""
    llm_model_extract: str = ""
    llm_timeout_sec: int = 120
    llm_reasoning_effort: str = "none"  # "none" or "" = never send the param (gateway hangs on invalid values); low/medium/high to enable
    llm_model_classify: str = ""
    hf_token: str = ""
    diarization_model: str = "pyannote/speaker-diarization-3.1"
    llm_model_plan: str = ""  # estimation job; falls back to llm_model_extract
    llm_model_chat: str = ""  # chatbot agent; falls back to llm_model_extract
    # Triage job (priority + duration + start/due date). Reasoning-heavy: date
    # arithmetic and effort sizing, so it gets the bigger model by default.
    llm_model_triage: str = "gpt-oss-120b"
    llm_model_vision: str = "meta/llama-3.2-90b-vision-instruct"  # timetable images
    morning_plan_time: str = "08:00"
    timezone: str = "Asia/Kolkata"
    # Pacing rules (phase4.md): 25–90 min blocks, 10-min buffers, 4h deep work/day
    plan_min_block_min: int = 25
    plan_max_block_min: int = 90
    plan_buffer_min: int = 10
    plan_deep_work_min_per_day: int = 240
    plan_horizon_days: int = 14


settings = Settings()
