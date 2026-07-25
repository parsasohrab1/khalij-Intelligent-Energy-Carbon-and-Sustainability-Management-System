"""API routers for iEMS modules."""

from app.api.routes import (
    alerts,
    auth,
    carbon,
    dashboard,
    health,
    ingestion,
    optimization,
    prediction,
    settings,
)

__all__ = [
    "alerts",
    "auth",
    "carbon",
    "dashboard",
    "health",
    "ingestion",
    "optimization",
    "prediction",
    "settings",
]
