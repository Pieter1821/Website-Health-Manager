"""Tkinter theme helpers — friendly, readable defaults."""

from __future__ import annotations

from tkinter import ttk

from whm.domain.models import HealthStatus
from whm.presentation.copy import status_plain


STATUS_COLORS = {
    HealthStatus.HEALTHY: "#067647",
    HealthStatus.WARNING: "#B54708",
    HealthStatus.CRITICAL: "#B42318",
    HealthStatus.UNKNOWN: "#475467",
}


def apply_theme(root, theme_name: str = "clam") -> None:
    style = ttk.Style(root)
    try:
        style.theme_use(theme_name if theme_name in style.theme_names() else "clam")
    except Exception:  # noqa: BLE001
        style.theme_use("clam")

    root.configure(background="#F8FAFC")
    style.configure(".", background="#F8FAFC", foreground="#101828")
    style.configure("TFrame", background="#F8FAFC")
    style.configure("TLabel", background="#F8FAFC", font=("Segoe UI", 10))
    style.configure("TButton", padding=(12, 8), font=("Segoe UI", 10))
    style.configure("Accent.TButton", padding=(14, 10), font=("Segoe UI Semibold", 11))
    style.configure("Treeview", rowheight=30, font=("Segoe UI", 10), fieldbackground="#FFFFFF")
    style.configure("Treeview.Heading", font=("Segoe UI Semibold", 10))
    style.configure("Header.TLabel", font=("Segoe UI Semibold", 18), foreground="#0B4F6C")
    style.configure("Subheader.TLabel", font=("Segoe UI", 10), foreground="#475467")
    style.configure("Hint.TLabel", font=("Segoe UI", 9), foreground="#667085")
    style.configure("Status.TLabel", font=("Segoe UI Semibold", 12))
    style.configure("Card.TLabelframe", background="#FFFFFF", relief="solid")
    style.configure("Card.TLabelframe.Label", font=("Segoe UI Semibold", 11), background="#FFFFFF")


def status_text(status: HealthStatus) -> str:
    return status_plain(status)
