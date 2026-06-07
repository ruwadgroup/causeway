"""Dramatiq broker target for Causeway apps.

Used by the adapter CLI as ``causeway.contrib.dramatiq.worker:broker``.
"""

from __future__ import annotations

from causeway.contrib.dramatiq.runtime import bootstrap

broker = bootstrap()

__all__ = ["broker"]
