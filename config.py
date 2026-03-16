from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    anthropic_api_key: str
    database_url: str = "sqlite+aiosqlite:///./sales_agent.db"
    redis_url: str = "redis://localhost:6379/0"

    # Optional integrations
    sendgrid_api_key: str = ""
    calendly_api_key: str = ""
    hubspot_api_key: str = ""
    hunter_api_key: str = ""
    crunchbase_api_key: str = ""
    news_api_key: str = ""

    class Config:
        env_file = ".env"


settings = Settings()
