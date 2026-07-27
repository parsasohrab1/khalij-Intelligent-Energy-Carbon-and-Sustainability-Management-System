"""Demo helpers for Kafka-less / sales demos."""

from app.demo.feeder import DemoFeeder
from app.demo.memory_store import memory_store

__all__ = ["DemoFeeder", "memory_store"]
