"""Shared helpers for the VIN report bot."""

from vinpro.browser_manager import (
    BrowserManager,
    is_closed_error,
    manager,
    render_with_retry,
)

__all__ = ["BrowserManager", "is_closed_error", "manager", "render_with_retry"]
