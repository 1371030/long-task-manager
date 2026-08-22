from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/longtasks"
    app_name: str = "Long Task Manager"
    api_key: str | None = None
    api_url: str | None = None
    api_model: str | None = None
    planner_openai_timeout_seconds: float = 30.0
    planner_openai_max_steps: int = 5
    planner_openai_temperature: float = 0.2
    planner_plan_system_prompt: str | None = None
    step_executor_openai_timeout_seconds: float = 60.0
    step_executor_openai_temperature: float = 0.2
    codex_enabled: bool = False
    codex_command: str = "codex"
    codex_working_directory: str | None = None
    codex_tmux_session_prefix: str = "longagent"
    codex_callback_base_url: str = "http://127.0.0.1:8000"
    codex_callback_secret: str | None = None
    codex_timeout_seconds: int = 1200
    codex_max_attempts: int = 2
    codex_keepalive_interval_seconds: int = 30
    codex_sandbox: str = "danger-full-access"
    codex_approval_policy: str = "never"


settings = Settings()
