"""Dramatiq broker target for Causeway apps.

Used by the adapter CLI as ``causeway_tasks_dramatiq.worker:broker``.
"""

from __future__ import annotations

from causeway_tasks_dramatiq.runtime import bootstrap

broker = bootstrap()

__all__ = ["broker"]
