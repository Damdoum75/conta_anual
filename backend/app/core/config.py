from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    PROJECT_NAME: str = "RentaFácil España"
    
    DATABASE_URL: str = "postgresql+asyncpg://user:password@localhost:5432/rentafacil"
    
    SECRET_KEY: str = "your-secret-key-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    
    STRIPE_SECRET_KEY: str = "sk_test_your_stripe_key"
    STRIPE_WEBHOOK_SECRET: str = "whsec_your_webhook_secret"
    STRIPE_PRICE_ID: str = "price_your_price_id"
    
    FRONTEND_URL: str = "http://localhost:5173"

    class Config:
        env_file = ".env"


@lru_cache()
def get_settings():
    return Settings()


settings = get_settings()