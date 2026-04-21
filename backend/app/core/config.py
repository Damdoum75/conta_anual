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
    
    FRONTEND_URL: str = "https://conta-anual-xygs.vercel.app"
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:3000,https://conta-anual-xygs.vercel.app,https://tecteamlab.eu,https://www.tecteamlab.eu,https://tectemalab.eu,https://www.tectemalab.eu"
    CORS_ORIGIN_REGEX: str = r"https://.*\.vercel\.app"
    TRIAL_DAYS: int = 7
    MONTHLY_ACCESS_PRICE_CENTS: int = 1000
    MONTHLY_ACCESS_DURATION_DAYS: int = 30

    class Config:
        env_file = ".env"


@lru_cache()
def get_settings():
    return Settings()


settings = get_settings()
