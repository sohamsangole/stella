from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    github_webhook_secret: str
    github_app_id: str = ""
    github_app_name: str = "coding-agent-stella"
    allowed_author_associations: str = "OWNER,MEMBER,COLLABORATOR"
    github_private_key_path: str = ""
    github_token: str = ""
    redis_url: str = "redis://localhost:6379/0"
    workspace_root: str = ""

    # Generic LLM Configuration
    llm_model: str = ""
    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"

    class Config:
        env_file = ".env"

settings = Settings()
