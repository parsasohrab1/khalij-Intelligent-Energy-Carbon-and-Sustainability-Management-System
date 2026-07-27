"""E12 — Real-Time Optimization (RTO): continuous advisory (FR-RTO-01).

Advisory-only: RTO never writes setpoints on its own. It recomputes benchmark
advice from live plant state on a short cycle and periodically queues fresh
recommendations into the existing accept -> approve -> apply operator
workflow (`app.optimization`), so an operator always makes the final call.
"""
