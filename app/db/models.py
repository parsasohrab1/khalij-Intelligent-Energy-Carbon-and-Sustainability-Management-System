"""SQLAlchemy ORM models aligned with TimescaleDB schema."""

from datetime import datetime

from sqlalchemy import DateTime, Double, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class Plant(Base):
    __tablename__ = "plants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    unit_type: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    readings: Mapped[list["SensorReading"]] = relationship(back_populates="plant")


class SensorReading(Base):
    """Raw + derived sensor stream at ≥1 Hz (R-GEN-01, FR-DATA-01/02)."""

    __tablename__ = "sensor_readings"

    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    plant_id: Mapped[int] = mapped_column(ForeignKey("plants.id"), primary_key=True)
    electricity_power_mw: Mapped[float | None] = mapped_column(Double)
    fuel_gas_flow_km3h: Mapped[float | None] = mapped_column(Double)
    steam_flow_tonh: Mapped[float | None] = mapped_column(Double)
    feed_flow_tonh: Mapped[float | None] = mapped_column(Double)
    reactor_temp_c: Mapped[float | None] = mapped_column(Double)
    pressure_bar: Mapped[float | None] = mapped_column(Double)
    energy_intensity_kgoe_ton: Mapped[float | None] = mapped_column(Double)
    carbon_emission_kgco2_ton: Mapped[float | None] = mapped_column(Double)
    energy_efficiency_percent: Mapped[float | None] = mapped_column(Double)

    plant: Mapped[Plant] = relationship(back_populates="readings")


class CarbonReport(Base):
    """Aggregated Scope 1/2 sustainability reports (R-GEN-04, FR-CAR-01)."""

    __tablename__ = "carbon_reports"
    __table_args__ = (UniqueConstraint("plant_id", "period_start", "period_type"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plant_id: Mapped[int] = mapped_column(ForeignKey("plants.id"), nullable=False)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_type: Mapped[str] = mapped_column(String(16), nullable=False)
    scope1_kgco2: Mapped[float] = mapped_column(Double, nullable=False, default=0)
    scope2_kgco2: Mapped[float] = mapped_column(Double, nullable=False, default=0)
    carbon_intensity_kgco2_ton: Mapped[float | None] = mapped_column(Double)
    product_ton: Mapped[float | None] = mapped_column(Double)
    sample_count: Mapped[int | None] = mapped_column(Integer)
    factors_version: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CarbonMarketSync(Base):
    """FR-CAR-02 — carbon market sync audit log."""

    __tablename__ = "carbon_market_syncs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    plant_code: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    registry: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    reports_synced: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    payload_path: Mapped[str | None] = mapped_column(Text)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ModelPrediction(Base):
    """60-minute energy/carbon forecasts (FR-ML-02)."""

    __tablename__ = "model_predictions"

    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    plant_id: Mapped[int] = mapped_column(ForeignKey("plants.id"), primary_key=True)
    horizon_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    predicted_energy_kwh: Mapped[float | None] = mapped_column(Double)
    predicted_carbon_kgco2: Mapped[float | None] = mapped_column(Double)
    model_name: Mapped[str] = mapped_column(Text, nullable=False)
    model_version: Mapped[str | None] = mapped_column(Text)
    mape: Mapped[float | None] = mapped_column(Double)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class StreamAlert(Base):
    """Phase 1 — stream cut / stale-data alerts."""

    __tablename__ = "stream_alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plant_code: Mapped[str] = mapped_column(Text, nullable=False)
    alert_type: Mapped[str] = mapped_column(String(32), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    age_seconds: Mapped[float | None] = mapped_column(Double)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OptimizationRecommendation(Base):
    """Phase 4 — structured setpoint advice for operators (FR-OPT-01/02)."""

    __tablename__ = "optimization_recommendations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plant_code: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    current_json: Mapped[str] = mapped_column(Text, nullable=False)
    proposed_json: Mapped[str] = mapped_column(Text, nullable=False)
    deltas_json: Mapped[str] = mapped_column(Text, nullable=False)
    tags_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    benchmark_plant: Mapped[str | None] = mapped_column(Text)
    estimated_sec_reduction_pct: Mapped[float | None] = mapped_column(Double)
    estimated_energy_saving_kwh_per_h: Mapped[float | None] = mapped_column(Double)
    estimated_efficiency_gain_pp: Mapped[float | None] = mapped_column(Double)
    simulated_intensity_delta: Mapped[float | None] = mapped_column(Double)
    simulated_efficiency_delta_pp: Mapped[float | None] = mapped_column(Double)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RecommendationFeedback(Base):
    """Phase 4 — operator accept/reject loop."""

    __tablename__ = "recommendation_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recommendation_id: Mapped[int] = mapped_column(
        ForeignKey("optimization_recommendations.id"), nullable=False
    )
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    operator: Mapped[str] = mapped_column(Text, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
