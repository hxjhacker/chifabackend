from pydantic_settings import BaseSettings, SettingsConfigDict


def _to_sqlalchemy(url: str) -> str:
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql://") and "+psycopg2" not in url:
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "production"
    app_name: str = "Chifaglow API"
    site_url: str = "https://chifaglow.com"
    cors_origins: str = "https://chifaglow.com,https://www.chifaglow.com"
    database_url: str = (
        "postgres://chifaglow:chifaglow@chifaglow_database:5432/chifaglow?sslmode=disable"
    )

    google_sheets_webhook_url: str = ""

    meta_pixel_id: str = ""
    meta_capi_access_token: str = ""
    meta_test_event_code: str = ""

    tiktok_pixel_id: str = ""
    tiktok_access_token: str = ""

    snapchat_pixel_id: str = ""
    snapchat_capi_token: str = ""

    maxmind_account_id: str = ""
    maxmind_license_key: str = ""
    enable_ip_fraud_check: bool = True

    @property
    def sqlalchemy_url(self) -> str:
        return _to_sqlalchemy(self.database_url)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
