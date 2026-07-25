"""Service package exports."""

# Keep imports lazy-friendly to avoid circular deps with app.ml
__all__ = [
    "CarbonBreakdown",
    "UnitSnapshot",
    "build_recommendations",
    "classify_units",
    "compute_scopes",
    "enrich_reading",
    "generate_virtual_samples",
    "predict_energy",
    "simulate_what_if",
]


def __getattr__(name: str):
    if name in {"CarbonBreakdown", "compute_scopes"}:
        from app.services.carbon import CarbonBreakdown, compute_scopes

        return {"CarbonBreakdown": CarbonBreakdown, "compute_scopes": compute_scopes}[name]
    if name in {"UnitSnapshot", "build_recommendations", "classify_units"}:
        from app.services.optimization import (
            UnitSnapshot,
            build_recommendations,
            classify_units,
        )

        return {
            "UnitSnapshot": UnitSnapshot,
            "build_recommendations": build_recommendations,
            "classify_units": classify_units,
        }[name]
    if name == "enrich_reading":
        from app.services.physics import enrich_reading

        return enrich_reading
    if name == "generate_virtual_samples":
        from app.services.vsg import generate_virtual_samples

        return generate_virtual_samples
    if name in {"predict_energy", "simulate_what_if"}:
        from app.services.prediction import predict_energy, simulate_what_if

        return {"predict_energy": predict_energy, "simulate_what_if": simulate_what_if}[name]
    raise AttributeError(name)
