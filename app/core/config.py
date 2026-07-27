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

    # E11 — Enterprise Ops / IdP (OIDC)
    oidc_enabled: bool = False
    oidc_issuer: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_redirect_uri: str = "http://localhost:8000/api/v1/auth/oidc/callback"
    oidc_scopes: str = "openid profile email"
    oidc_role_claim: str = "roles"
    oidc_admin_roles: str = "iems-admin,admin"
    oidc_operator_roles: str = "iems-operator,operator"
    oidc_viewer_roles: str = "iems-viewer,viewer"
    oidc_dev_bypass: bool = False  # POST /auth/oidc/dev-login when APP_DEBUG

    # E11 — multi-site
    site_code: str = "khalij"
    site_name: str = "Khalij Complex"

    # Demo / sales mode (Kafka-less live stream)
    demo_feeder: bool = False
    demo_memory_only: bool = False
    demo_prefer_memory: bool = False

    # E6 — Plant Connect (OPC-UA primary; disables demo memory fallback)
    plant_connect: bool = False
    opc_ua_username: str = ""
    opc_ua_password: str = ""
    opc_ua_use_subscription: bool = True
    opc_ua_allow_uncertain: bool = True

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
    carbon_scope3_path: str = "infra/carbon/scope3_factors.yaml"
    carbon_reports_export_dir: str = "data/reports/carbon"
    carbon_esg_pack_dir: str = "data/reports/esg_packs"
    carbon_market_staging_dir: str = "data/reports/carbon_market"
    carbon_market_registry_name: str = "khalij-carbon-registry"
    carbon_market_api_url: str = ""
    carbon_market_api_token: str = ""
    carbon_market_require_locked: bool = True
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

    # E8 — Trusted Models
    ml_trusted_mode: bool = False
    ml_allow_synthetic: bool = True
    ml_allow_physics_fallback: bool = True
    ml_allow_vsg_in_trusted: bool = False
    ml_holdout_ratio: float = 0.2
    ml_drift_psi_threshold: float = 0.2
    ml_physics_scale_path: str = "infra/ml/physics_calibration.yaml"
    ml_prefer_torch_lstm: bool = False

    # E9 — Advisory → Action (setpoint apply)
    opc_write_enabled: bool = False
    opc_write_dry_run_default: bool = True
    opt_require_sim_before_apply: bool = True
    opt_impact_window_minutes: int = 15
    opt_writable_fields: str = "reactor_temp_c,feed_flow_tonh"

    @property
    def writable_field_list(self) -> list[str]:
        return [c.strip() for c in self.opt_writable_fields.split(",") if c.strip()]

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

    @property
    def plant_connect_active(self) -> bool:
        """True when plant path must not fall back to demo memory/simulator soft-fail."""
        return bool(self.plant_connect)

    @property
    def trusted_mode_active(self) -> bool:
        """E8 — plant connect or explicit ML trusted mode."""
        return bool(self.plant_connect or self.ml_trusted_mode)

    def allow_demo_memory(self) -> bool:
        if self.plant_connect:
            return False
        # Development defaults to live demo memory so Control/Reporting stay populated
        if self.app_debug or self.app_env == "development":
            return True
        return bool(self.demo_prefer_memory or self.demo_memory_only or self.demo_feeder)

    def should_run_demo_feeder(self) -> bool:
        """Inline 1 Hz feeder for live UI when not in Plant Connect mode."""
        if self.plant_connect:
            return False
        if self.demo_feeder:
            return True
        return bool(self.app_debug or self.app_env == "development")

    def allow_ml_synthetic(self) -> bool:
        if self.trusted_mode_active:
            return False
        return bool(self.ml_allow_synthetic)

    def allow_ml_physics_fallback(self) -> bool:
        if self.trusted_mode_active:
            return False
        return bool(self.ml_allow_physics_fallback)


@lru_cache
def get_settings() -> Settings:
    return Settings()
