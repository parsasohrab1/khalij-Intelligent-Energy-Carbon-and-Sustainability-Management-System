"""Pydantic schemas for API request/response contracts."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    app: str
    env: str
    checks: dict[str, str]


class SensorReadingIn(BaseModel):
    time: datetime | None = None
    plant_code: str = Field(..., examples=["olefin", "pta"])
    electricity_power_mw: float | None = None
    fuel_gas_flow_km3h: float | None = None
    steam_flow_tonh: float | None = None
    feed_flow_tonh: float | None = None
    reactor_temp_c: float | None = None
    pressure_bar: float | None = None


class SensorReadingOut(SensorReadingIn):
    energy_intensity_kgoe_ton: float | None = None
    carbon_emission_kgco2_ton: float | None = None
    energy_efficiency_percent: float | None = None
    source: str | None = None
    quality: str | None = None


class EnergyDashboardOut(BaseModel):
    """R-GEN-03 — live energy, intensity, and carbon footprint."""

    plant_code: str
    as_of: datetime
    electricity_power_mw: float | None = None
    fuel_gas_flow_km3h: float | None = None
    steam_flow_tonh: float | None = None
    feed_flow_tonh: float | None = None
    reactor_temp_c: float | None = None
    pressure_bar: float | None = None
    energy_intensity_kgoe_ton: float | None = None
    carbon_emission_kgco2_ton: float | None = None
    carbon_intensity_kgco2_ton: float | None = Field(
        default=None, description="FR-CAR-03 KPI"
    )
    energy_efficiency_percent: float | None = None
    stream_status: Literal["ok", "stale", "missing", "bad_quality"] | None = None
    data_age_seconds: float | None = None
    factors_version: str | None = None
    scope1_kgco2: float | None = None
    scope2_kgco2: float | None = None
    source: str | None = None
    quality: str | None = None


class EnergyHistoryPoint(BaseModel):
    time: datetime
    electricity_power_mw: float | None = None
    fuel_gas_flow_km3h: float | None = None
    steam_flow_tonh: float | None = None
    feed_flow_tonh: float | None = None
    reactor_temp_c: float | None = None
    pressure_bar: float | None = None
    energy_intensity_kgoe_ton: float | None = None
    carbon_emission_kgco2_ton: float | None = None
    carbon_intensity_kgco2_ton: float | None = None
    energy_efficiency_percent: float | None = None
    scope1_kgco2: float | None = None
    scope2_kgco2: float | None = None


class EnergyHistoryOut(BaseModel):
    plant_code: str
    minutes: int
    count: int
    points: list[EnergyHistoryPoint]
    generated_at: datetime


class StreamAlertOut(BaseModel):
    id: int
    plant_code: str
    alert_type: str
    message: str
    age_seconds: float | None = None
    created_at: datetime
    resolved_at: datetime | None = None
    severity: Literal["info", "warning", "critical"] = "warning"


class MeResponse(BaseModel):
    username: str
    role: str
    actions: dict[str, bool]


class PredictionRequest(BaseModel):
    plant_code: str = Field(default="olefin", examples=["olefin"])
    horizon_minutes: int = Field(default=60, ge=1, le=180)
    model: Literal["elm", "lstm"] = "elm"


class PredictionResponse(BaseModel):
    plant_code: str
    horizon_minutes: int
    model: str
    predicted_energy_kwh: float
    predicted_carbon_kgco2: float
    latency_ms: float
    mape_estimate: float | None = None
    model_version: str | None = None
    source: str | None = None
    note: str = "ELM/LSTM via local registry / MLflow"
    trusted: bool = False


class WhatIfRequest(BaseModel):
    """FR-ML-03 — what-if operational parameter simulation."""

    plant_code: str = "olefin"
    reactor_temp_c: float = Field(..., ge=350, le=450)
    feed_flow_tonh: float = Field(..., ge=50, le=150)
    fuel_gas_flow_km3h: float = Field(..., ge=30, le=200)
    steam_flow_tonh: float = Field(default=30.0, ge=5, le=60)
    electricity_power_mw: float = Field(default=15.0, ge=1, le=40)
    model: Literal["elm", "lstm"] = "elm"


class WhatIfResponse(BaseModel):
    plant_code: str
    estimated_energy_intensity_kgoe_ton: float
    estimated_carbon_emission_kgco2_ton: float
    estimated_efficiency_percent: float
    model: str | None = None
    model_version: str | None = None
    source: str | None = None


class VSGRequest(BaseModel):
    """FR-ML-01 — Virtual Sample Generation (MC / PSO)."""

    method: Literal["mc", "pso"] = "mc"
    n_samples: int = Field(default=100, ge=10, le=5000)
    seed: int = 42
    plant_code: str = "olefin"


class VSGResponse(BaseModel):
    method: str
    n_samples: int
    samples: list[dict[str, float]]
    source: str | None = None


class TrainRequest(BaseModel):
    plant_code: str = Field(default="olefin", examples=["olefin"])
    model: Literal["elm", "lstm"] = "elm"


class TrainResponse(BaseModel):
    plant_code: str
    model: str
    mape: float
    meets_mape_target: bool
    train_size: int
    test_size: int
    vsg_samples: int
    data_source: str
    model_version: str
    mlflow_run_id: str | None = None
    artifact_path: str
    trusted: bool = False
    holdout_temporal: bool = False
    physics_cal_version: str | None = None


class ModelInfoOut(BaseModel):
    plant_code: str
    model: str
    version: str
    mape: float
    artifact_path: str
    registered_at: str
    mlflow_run_id: str | None = None
    data_source: str | None = None
    holdout_temporal: bool = False
    trusted: bool = False
    physics_cal_version: str | None = None


class OptimizationRequest(BaseModel):
    plant_codes: list[str] = Field(default_factory=lambda: ["olefin", "pta"])
    simulate: bool = True
    persist: bool = True
    model: Literal["elm", "lstm"] = "elm"


class UnitEfficiencyOut(BaseModel):
    plant_code: str
    energy_efficiency_percent: float
    energy_intensity_kgoe_ton: float
    tier: Literal["high", "low"]
    gap_pp_vs_best: float | None = None
    benchmark_plant: str | None = None


class SetpointAdviceOut(BaseModel):
    id: int | None = None
    plant_code: str
    priority: Literal["high", "medium", "low"]
    title: str
    rationale: str
    current: dict[str, float]
    proposed: dict[str, float]
    deltas: dict[str, float]
    tags: list[str] = Field(default_factory=list)
    benchmark_plant: str | None = None
    estimated_sec_reduction_pct: float
    estimated_energy_saving_kwh_per_h: float
    estimated_efficiency_gain_pp: float
    simulated_intensity_delta: float | None = None
    simulated_efficiency_delta_pp: float | None = None
    status: str | None = "pending"
    apply_mode: str | None = None
    realized_saving_kwh_per_h: float | None = None
    approved_by: str | None = None
    applied_by: str | None = None


class AdviceSimulationOut(BaseModel):
    plant_code: str
    before_intensity: float
    after_intensity: float
    before_efficiency: float
    after_efficiency: float
    intensity_delta: float
    efficiency_delta_pp: float
    carbon_delta: float
    model: str | None = None
    source: str | None = None


class OptimizationResponse(BaseModel):
    """FR-OPT-01 / FR-OPT-02 — savings potential and operator advice."""

    units: list[UnitEfficiencyOut]
    recommendations: list[str]
    advice: list[SetpointAdviceOut] = Field(default_factory=list)
    simulations: list[AdviceSimulationOut] = Field(default_factory=list)
    total_estimated_saving_kwh_per_h: float = 0.0


class FeedbackRequest(BaseModel):
    decision: Literal["accepted", "rejected"]
    operator: str = Field(..., min_length=1, max_length=128)
    comment: str | None = None


class FeedbackOut(BaseModel):
    recommendation_id: int
    decision: str
    operator: str
    comment: str | None = None
    status: str
    created_at: datetime


class ApproveRequest(BaseModel):
    comment: str | None = None


class ApplyRequest(BaseModel):
    dry_run: bool | None = None  # None → OPC_WRITE_DRY_RUN_DEFAULT


class ApplyOut(BaseModel):
    recommendation_id: int
    status: str
    apply_mode: str
    dry_run: bool
    planned: list[dict] = Field(default_factory=list)
    written: list[dict] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)
    detail: str = ""
    baseline_intensity: float | None = None
    baseline_efficiency: float | None = None


class ImpactOut(BaseModel):
    recommendation_id: int
    plant_code: str
    status: str
    baseline_intensity: float | None = None
    current_intensity: float | None = None
    baseline_efficiency: float | None = None
    current_efficiency: float | None = None
    estimated_saving_kwh_per_h: float | None = None
    realized_saving_kwh_per_h: float | None = None
    window_minutes: int
    samples: int
    detail: str = ""


class AuditEventOut(BaseModel):
    id: int
    recommendation_id: int
    event_type: str
    actor: str
    detail: dict = Field(default_factory=dict)
    created_at: datetime


class CarbonScopeOut(BaseModel):
    plant_code: str
    period_type: Literal["instant", "daily", "monthly", "yearly"]
    scope1_kgco2: float
    scope2_kgco2: float
    scope3_kgco2: float | None = None
    total_kgco2: float
    carbon_intensity_kgco2_ton: float | None = None
    product_ton: float | None = None
    factors_version: str | None = None
    report_id: int | None = None
    period_start: datetime | None = None
    period_end: datetime | None = None
    assurance_status: str | None = None


class CarbonFactorOut(BaseModel):
    plant_code: str
    natural_gas_kgco2_per_m3: float
    steam_kgco2_per_ton: float
    electricity_kgco2_per_kwh: float
    version: str
    source: str
    notes: str = ""


class CarbonReportOut(BaseModel):
    id: int
    plant_code: str
    period_type: Literal["daily", "monthly", "yearly"]
    period_start: datetime
    period_end: datetime
    scope1_kgco2: float
    scope2_kgco2: float
    scope3_kgco2: float | None = None
    total_kgco2: float
    carbon_intensity_kgco2_ton: float | None = None
    product_ton: float | None = None
    sample_count: int | None = None
    factors_version: str | None = None
    assurance_status: str | None = "draft"
    submitted_by: str | None = None
    approved_by: str | None = None
    locked_by: str | None = None
    created_at: datetime | None = None


class GenerateReportRequest(BaseModel):
    plant_codes: list[str] = Field(default_factory=lambda: ["olefin", "pta"])
    period_types: list[Literal["daily", "monthly", "yearly"]] = Field(
        default_factory=lambda: ["daily"]
    )
    completed_only: bool = False


class GenerateReportResponse(BaseModel):
    generated: int
    reports: list[CarbonReportOut]
    message: str


class CarbonMarketSyncOut(BaseModel):
    """FR-CAR-02 — carbon market integration result."""

    status: str
    synced_at: datetime
    registry: str
    message: str
    reports_synced: int = 0
    batch_id: str | None = None
    payload_path: str | None = None
    external_ref: str | None = None


class CarbonAssuranceEventOut(BaseModel):
    id: int
    report_id: int
    event_type: str
    actor: str
    detail: dict = Field(default_factory=dict)
    created_at: datetime


class AssuranceActionRequest(BaseModel):
    comment: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    requires_2fa: bool = False


class LoginRequest(BaseModel):
    username: str
    password: str
    totp_code: str | None = Field(default=None, description="2FA code for settings changes")
