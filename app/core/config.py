"""Application settings loaded from environment / .env."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "iEMS"
    app_env: str = "development"
    app_debug: bool = True
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    secret_key: str = "change-me-in-production"

    # Phase 5 — security / production
    auth_enforce: bool = False
    auth_login_require_2fa: bool = False
    auth_token_ttl_seconds: int = 3600
    cors_origins: str = "*"

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "iems"
    postgres_password: str = "iems_secret"
    postgres_db: str = "iems"

    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: str = ""

    kafka_bootstrap_servers: str = "localhost:9092"
    kafka_sensor_topic: str = "sensor.readings"
    kafka_consumer_group: str = "iems-ingestion"

    mlflow_tracking_uri: str = "http://localhost:5000"
    mlflow_experiment_name: str = "energy-prediction"
    mlflow_enabled: bool = False  # enable when MLflow server is reachable

    ingestion_rate_hz: float = 1.0
    opc_ua_endpoint: str = ""
    opc_ua_tag_map_path: str = "infra/opcua/tags.yaml"
    unit_codes: str = "olefin,pta"
    producer_plant_codes: str = "olefin"
    ingestion_source: str = "simulator"  # simulator | opcua
    stale_data_seconds: float = 5.0
    stream_alert_cooldown_seconds: float = 30.0

    ef_natural_gas_kgco2_per_m3: float = 2.0
    ef_steam_kgco2_per_ton: float = 0.3
    ef_electricity_kgco2_per_kwh: float = 0.5

    # Phase 2 — carbon & sustainability
    carbon_factors_path: str = "infra/carbon/emission_factors.yaml"
    carbon_reports_export_dir: str = "data/reports/carbon"
    carbon_market_staging_dir: str = "data/reports/carbon_market"
    carbon_market_registry_name: str = "khalij-carbon-registry"
    carbon_market_api_url: str = ""
    carbon_market_api_token: str = ""
    carbon_report_interval_seconds: int = 300
    carbon_report_completed_only: bool = False  # False = demo-friendly current period

    # Phase 3 — ML prediction
    ml_model_dir: str = "data/models"
    ml_seed: int = 42
    ml_synthetic_samples: int = 1500
    ml_min_real_samples: int = 50
    ml_train_sample_limit: int = 5000
    ml_lookback_hours: int = 48
    ml_test_ratio: float = 0.2
    ml_vsg_method: str = "mc"
    ml_vsg_samples: int = 300
    ml_elm_hidden: int = 64
    ml_lstm_lookback: int = 8
    ml_lstm_hidden: int = 16
    ml_lstm_epochs: int = 20
    ml_lstm_lr: float = 0.01
    ml_mape_target: float = 5.0
    ml_max_latency_ms: float = 3000.0
    ml_retrain_interval_seconds: int = 3600

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def database_url_sync(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        if self.redis_password:
            return f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}/0"
        return f"redis://{self.redis_host}:{self.redis_port}/0"

    @property
    def unit_code_list(self) -> list[str]:
        return [c.strip() for c in self.unit_codes.split(",") if c.strip()]

    @property
    def producer_plant_code_list(self) -> list[str]:
        return [c.strip() for c in self.producer_plant_codes.split(",") if c.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
