from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    github_webhook_secret: str
    redis_url: str = "redis://localhost:6379/0"

    class Config:
        env_file = ".env"

settings = Settings()