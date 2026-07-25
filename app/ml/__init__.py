"""Phase 3 ML package — VSG, ELM/LSTM, registry, serving."""

__all__ = [
    "PredictionResult",
    "TrainResult",
    "mape",
    "multi_output_mape",
    "predict_with_model",
    "simulate_what_if_ml",
    "train_model",
]


def __getattr__(name: str):
    if name in {"mape", "multi_output_mape"}:
        from app.ml.metrics import mape, multi_output_mape

        return {"mape": mape, "multi_output_mape": multi_output_mape}[name]
    if name in {"PredictionResult", "predict_with_model", "simulate_what_if_ml"}:
        from app.ml.serve import PredictionResult, predict_with_model, simulate_what_if_ml

        return {
            "PredictionResult": PredictionResult,
            "predict_with_model": predict_with_model,
            "simulate_what_if_ml": simulate_what_if_ml,
        }[name]
    if name in {"TrainResult", "train_model"}:
        from app.ml.train import TrainResult, train_model

        return {"TrainResult": TrainResult, "train_model": train_model}[name]
    raise AttributeError(name)
