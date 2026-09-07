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
        "postgres://chifaglow:chifaglow@chifaglow_chifaglow:5432/chifaglow?sslmode=disable"
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

    admin_username: str = "manager@chifa.com"
    admin_password: str = "adminpro@"
    admin_password_hash: str = ""
    admin_jwt_secret: str = "204a308d75e24d90b8e47391e1cc9d33b2b08cce2dcd4482a2276542bd346504"
    admin_jwt_hours: int = 12

    vapid_public_key: str = "BLIQF0U5W6Xd-DZjVgIqpNJoBlJo48KDeOn5DvMRQBWZY36qKbQeNYmAubek3DEgqmmC5ot2HuGN_m_jM7gmIbA"
    vapid_private_key: str = "aoeWVCDnWXyAQB7YjEldsJXqdaNk8005Ks2PwckW8TI"
    vapid_subject: str = "mailto:hello@chifaglow.com"

    meta_livraison_base_url: str = "https://api.metalivraison.ma"
    meta_livraison_api_key: str = ""
    meta_livraison_api_secret: str = ""
    meta_livraison_delivery_fee: float = 30.0
    meta_livraison_return_fee: float = 15.0

    @property
    def sqlalchemy_url(self) -> str:
        return _to_sqlalchemy(self.database_url)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
