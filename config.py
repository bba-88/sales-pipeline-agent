from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    anthropic_api_key: str
    database_url: str = "sqlite+aiosqlite:///./sales_agent.db"
    redis_url: str = "redis://localhost:6379/0"

    # Sender identity (for mock email sending)
    sender_name: str = "Alex"
    sender_company: str = "Your Company"
    sender_email: str = "alex@yourcompany.com"
    calendly_link: str = "https://calendly.com/yourname/30min"

    # Optional real integrations (leave blank = mock/demo mode)
    sendgrid_api_key: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    calendly_api_key: str = ""
    hubspot_api_key: str = ""
    salesforce_client_id: str = ""
    salesforce_client_secret: str = ""
    hunter_api_key: str = ""
    crunchbase_api_key: str = ""
    news_api_key: str = ""

    class Config:
        env_file = ".env"


settings = Settings()
