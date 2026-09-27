"""Durable async chat jobs — survive panel close and add-on restart cleanly."""

from __future__ import annotations

from services.chat_jobs import manager as manager

__all__ = ["manager"]
