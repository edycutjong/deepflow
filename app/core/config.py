"""Pydantic Settings with computed async/sync DSN properties."""
from pydantic import computed_field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    POSTGRES_USER: str = "whale"
    POSTGRES_PASSWORD: str = "changeme"
    POSTGRES_DB: str = "silent_whale"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432

    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""

    GITHUB_TOKEN: str = ""  # Optional: raises rate limit from 60→5000/hr

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_url_async(self) -> str:
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_url_sync(self) -> str:
        return (
            f"postgresql+psycopg2://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
