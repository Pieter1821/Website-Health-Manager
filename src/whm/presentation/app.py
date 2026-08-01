"""Main Tkinter UI — designed for non-technical users."""

from __future__ import annotations

import logging
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Optional

from whm.application.scheduler import SchedulerService
from whm.application.services import HealthScanService, SettingsService, WebsiteService
from whm.domain.models import Finding, HealthCheckResult, HealthStatus, Website
from whm.infrastructure.reports import default_export_paths, export_csv, export_html, export_json
from whm.presentation.copy import (
    category_plain,
    finding_plain,
    overall_summary,
    risk_plain,
    status_plain,
)
from whm.presentation.education import blurb_for
from whm.presentation.styles import STATUS_COLORS, apply_theme, status_text

logger = logging.getLogger(__name__)

INTERVAL_LABELS = {
    "manual": "Only when I click Check",
    "hourly": "Every hour",
    "every_6_hours": "Every 6 hours",
    "daily": "Once a day",
    "weekly": "Once a week",
}


class WebsiteHealthApp(ttk.Frame):
    """Friendly dashboard: quick check, simple list, plain-language details."""

    def __init__(
        self,
        master: tk.Tk,
        website_service: WebsiteService,
        scan_service: HealthScanService,
        settings_service: SettingsService,
        scheduler: Optional[SchedulerService] = None,
    ) -> None:
        super().__init__(master, padding=16)
        self.master = master
        self.websites = website_service
        self.scans = scan_service
        self.settings = settings_service
        self.scheduler = scheduler
        self._scan_thread: Optional[threading.Thread] = None
        self._selected_id: Optional[int] = None

        apply_theme(master, self.settings.get("theme", "clam"))
        master.title("Website Health Manager")
        master.geometry("1240x780")
        master.minsize(980, 640)

        self.pack(fill=tk.BOTH, expand=True)
        self._build_header()
        self._build_quick_check()
        self._build_body()
        self._build_statusbar()
        self.refresh_list()

        if not self.websites.list_websites():
            self.status_var.set("Tip: type a website above and click Check now.")

    # ----- layout -----

    def _build_header(self) -> None:
        bar = ttk.Frame(self)
        bar.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(bar, text="Website Health Manager", style="Header.TLabel").pack(
            side=tk.LEFT
        )
        ttk.Button(bar, text="Settings", command=self.open_settings).pack(side=tk.RIGHT, padx=2)
        ttk.Button(bar, text="Help", command=self.show_help).pack(side=tk.RIGHT, padx=2)
        ttk.Label(
            self,
            text="Find out why a website or email is not working — in plain English.",
            style="Subheader.TLabel",
        ).pack(anchor=tk.W, pady=(0, 10))

    def _build_quick_check(self) -> None:
        box = ttk.LabelFrame(self, text="Quick check", padding=12)
        box.pack(fill=tk.X, pady=(0, 12))

        ttk.Label(
            box,
            text="Enter a website (example: mybusiness.co.za)",
            style="Hint.TLabel",
        ).pack(anchor=tk.W)

        row = ttk.Frame(box)
        row.pack(fill=tk.X, pady=(6, 0))
        self.quick_url = tk.StringVar()
        entry = ttk.Entry(row, textvariable=self.quick_url, font=("Segoe UI", 12))
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        entry.bind("<Return>", lambda _e: self.quick_check())
        ttk.Button(row, text="Check now", style="Accent.TButton", command=self.quick_check).pack(
            side=tk.LEFT
        )

        row2 = ttk.Frame(box)
        row2.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(row2, text="Customer name (optional)").pack(side=tk.LEFT)
        self.quick_customer = tk.StringVar()
        ttk.Entry(row2, textvariable=self.quick_customer, width=28).pack(side=tk.LEFT, padx=8)

    def _build_body(self) -> None:
        actions = ttk.Frame(self)
        actions.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(actions, text="Your websites", style="Subheader.TLabel").pack(side=tk.LEFT)
        self.search_var = tk.StringVar()
        search = ttk.Entry(actions, textvariable=self.search_var, width=28)
        search.pack(side=tk.LEFT, padx=8)
        search.bind("<Return>", lambda _e: self.refresh_list())
        ttk.Button(actions, text="Find", command=self.refresh_list).pack(side=tk.LEFT)
        ttk.Button(actions, text="Check selected", command=self.scan_selected).pack(
            side=tk.RIGHT, padx=2
        )
        ttk.Button(actions, text="Import Excel/CSV", command=self.import_list_dialog).pack(
            side=tk.RIGHT, padx=2
        )
        ttk.Button(actions, text="Save report", command=self.export_selected).pack(
            side=tk.RIGHT, padx=2
        )
        ttk.Button(actions, text="Remove", command=self.delete_selected).pack(
            side=tk.RIGHT, padx=2
        )

        body = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        body.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(body)
        right = ttk.Frame(body)
        body.add(left, weight=3)
        body.add(right, weight=2)

        columns = ("name", "overall", "website", "ssl", "domain", "dns", "email", "checked")
        self.tree = ttk.Treeview(left, columns=columns, show="headings", selectmode="browse")
        headings = {
            "name": "Website",
            "overall": "Overall",
            "website": "Website",
            "ssl": "Certificate",
            "domain": "Domain",
            "dns": "Address settings",
            "email": "Email",
            "checked": "Last checked",
        }
        widths = {
            "name": 160,
            "overall": 120,
            "website": 110,
            "ssl": 110,
            "domain": 110,
            "dns": 120,
            "email": 110,
            "checked": 130,
        }
        for col in columns:
            self.tree.heading(col, text=headings[col])
            self.tree.column(col, width=widths[col], anchor=tk.W)
        scroll = ttk.Scrollbar(left, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.bind("<<TreeviewSelect>>", self.on_select)

        ttk.Label(right, text="What we found", style="Header.TLabel").pack(anchor=tk.W)
        self.detail_summary = ttk.Label(
            right,
            text="Select a website, or use Quick check above.",
            style="Subheader.TLabel",
            wraplength=420,
            justify=tk.LEFT,
        )
        self.detail_summary.pack(anchor=tk.W, pady=(4, 8), fill=tk.X)

        notebook = ttk.Notebook(right)
        notebook.pack(fill=tk.BOTH, expand=True)
        findings_frame = ttk.Frame(notebook)
        history_frame = ttk.Frame(notebook)
        changes_frame = ttk.Frame(notebook)
        notebook.add(findings_frame, text="Results")
        notebook.add(history_frame, text="History")
        notebook.add(changes_frame, text="Changes")

        self.findings_text = tk.Text(
            findings_frame, wrap=tk.WORD, height=20, font=("Segoe UI", 10), relief=tk.FLAT
        )
        self.findings_text.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        self.findings_text.configure(state=tk.DISABLED)

        self.history_tree = ttk.Treeview(
            history_frame,
            columns=("when", "overall", "ms"),
            show="headings",
            height=12,
        )
        for col, title, width in (
            ("when", "When", 160),
            ("overall", "Result", 140),
            ("ms", "How long (ms)", 100),
        ):
            self.history_tree.heading(col, text=title)
            self.history_tree.column(col, width=width)
        self.history_tree.pack(fill=tk.BOTH, expand=True)

        self.dns_text = tk.Text(
            changes_frame, wrap=tk.WORD, height=20, font=("Segoe UI", 10), relief=tk.FLAT
        )
        self.dns_text.pack(fill=tk.BOTH, expand=True)
        self.dns_text.configure(state=tk.DISABLED)

    def _build_statusbar(self) -> None:
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(self, textvariable=self.status_var, style="Hint.TLabel").pack(
            fill=tk.X, pady=(10, 0)
        )

    # ----- data -----

    def refresh_list(self) -> None:
        items = self.websites.search(self.search_var.get())
        for row in self.tree.get_children():
            self.tree.delete(row)
        for site in items:
            latest = self.scans.latest(site.id) if site.id else None
            self.tree.insert("", tk.END, iid=str(site.id), values=self._row_values(site, latest))
        self.status_var.set(f"{len(items)} website(s) saved")

    def _row_values(self, site: Website, latest: Optional[HealthCheckResult]) -> tuple:
        if latest is None:
            return (site.display_name, "Not checked yet", "—", "—", "—", "—", "—", "Never")
        checked = latest.checked_at.strftime("%Y-%m-%d %H:%M") if latest.checked_at else "—"
        return (
            site.display_name,
            status_text(latest.overall_status),
            status_text(latest.website_status),
            status_text(latest.ssl_status),
            status_text(latest.domain_status),
            status_text(latest.dns_status),
            status_text(latest.email_status),
            checked,
        )

    def on_select(self, _event=None) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        self._selected_id = int(selection[0])
        self.show_details(self._selected_id)

    def show_details(self, website_id: int) -> None:
        site = self.websites.get_website(website_id)
        latest = self.scans.latest(website_id)
        if site is None:
            return
        if latest is None:
            self.detail_summary.configure(
                text=f"{site.display_name}\nNot checked yet — click Check selected.",
                foreground="#475467",
            )
            self._set_text(self.findings_text, "")
            self._set_text(self.dns_text, "")
            for row in self.history_tree.get_children():
                self.history_tree.delete(row)
            return

        color = STATUS_COLORS.get(latest.overall_status, "#475467")
        self.detail_summary.configure(
            text=(
                f"{site.display_name}  ·  {site.domain}\n"
                f"{overall_summary(latest.overall_status, site.display_name)}\n"
                f"Risk: {risk_plain(latest.risk_level)}"
            ),
            foreground=color,
        )
        self._set_text(self.findings_text, self._format_findings(latest.findings, latest))
        self._load_history(website_id)
        self._load_dns_changes(website_id)

    def _format_findings(
        self, findings: list[Finding], result: HealthCheckResult
    ) -> str:
        if not findings:
            return "No details yet."
        lines = [
            f"Overall: {status_plain(result.overall_status)}",
            "",
            "Below is each check, with what it means and what to do next.",
            "",
        ]
        current = None
        for finding in findings:
            if finding.category != current:
                current = finding.category
                lines.append(f"—— {category_plain(current)} ——")
                blurb = blurb_for(current)
                if blurb:
                    lines.append(blurb)
                    lines.append("")
            lines.append(f"[{finding_plain(finding.status)}] {finding.title}")
            lines.append(f"  {finding.message}")
            if finding.recommendation:
                label = (
                    "Note"
                    if finding.status.value == "inconclusive" or finding.details.get("probe_failed")
                    else "What to do"
                )
                lines.append(f"  {label}: {finding.recommendation}")
            lines.append("")
        return "\n".join(lines).strip() + "\n"

    def _load_history(self, website_id: int) -> None:
        for row in self.history_tree.get_children():
            self.history_tree.delete(row)
        for item in self.scans.history(website_id, limit=30):
            when = item.checked_at.strftime("%Y-%m-%d %H:%M:%S")
            ms = f"{item.response_time_ms:.0f}" if item.response_time_ms is not None else "—"
            self.history_tree.insert(
                "", tk.END, values=(when, status_text(item.overall_status), ms)
            )

    def _load_dns_changes(self, website_id: int) -> None:
        changes = self.scans.dns_diff(website_id)
        if not changes:
            self._set_text(
                self.dns_text,
                "No address-setting changes between the last two successful checks.",
            )
            return
        lines = ["These DNS settings changed:", ""]
        for change in changes:
            if change["change"] == "added":
                lines.append(f"+ Added {change['rtype']}: {change['new_value']}")
            else:
                lines.append(f"- Removed {change['rtype']}: {change['old_value']}")
        self._set_text(self.dns_text, "\n".join(lines))

    @staticmethod
    def _set_text(widget: tk.Text, value: str) -> None:
        widget.configure(state=tk.NORMAL)
        widget.delete("1.0", tk.END)
        widget.insert(tk.END, value)
        widget.configure(state=tk.DISABLED)

    # ----- actions -----

    def quick_check(self) -> None:
        url = self.quick_url.get().strip()
        if not url:
            messagebox.showinfo(
                "Website needed",
                "Type a website first.\nExample: mybusiness.co.za",
            )
            return
        customer_id = None
        customer_name = self.quick_customer.get().strip()
        if customer_name:
            customer_id = self.websites.add_customer(customer_name).id
        try:
            site = self.websites.add_website(url=url, customer_id=customer_id)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Could not add website", str(exc))
            return
        self.quick_url.set("")
        self.refresh_list()
        if site.id is not None:
            self.tree.selection_set(str(site.id))
            self._selected_id = site.id
            self.scan_selected()

    def import_list_dialog(self) -> None:
        path = filedialog.askopenfilename(
            title="Import website list",
            filetypes=[
                ("Excel or CSV", "*.xlsx *.csv *.txt"),
                ("Excel", "*.xlsx"),
                ("CSV", "*.csv *.txt"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return
        try:
            data = Path(path).read_bytes()
            result = self.websites.import_list(Path(path).name, data)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Import failed", str(exc))
            return
        self.refresh_list()
        details = result.summary
        if result.errors:
            details += "\n\nSome rows had problems:\n" + "\n".join(result.errors[:8])
        messagebox.showinfo("Import finished", details)
        self.status_var.set(result.summary)

    def delete_selected(self) -> None:
        if self._selected_id is None:
            messagebox.showinfo("Select a website", "Click a website in the list first.")
            return
        site = self.websites.get_website(self._selected_id)
        if site is None:
            return
        if not messagebox.askyesno(
            "Remove website",
            f"Remove {site.display_name} from this list?\nPast check history will also be removed.",
        ):
            return
        self.websites.delete_website(self._selected_id)
        self._selected_id = None
        self.refresh_list()
        self._set_text(self.findings_text, "")
        self.detail_summary.configure(text="Select a website, or use Quick check above.")

    def scan_selected(self) -> None:
        if self._selected_id is None:
            messagebox.showinfo("Select a website", "Click a website in the list first.")
            return
        if self._scan_thread and self._scan_thread.is_alive():
            messagebox.showinfo("Please wait", "A check is already running.")
            return

        website_id = self._selected_id
        self.status_var.set("Checking… this can take a minute.")

        def worker() -> None:
            try:
                def progress(msg: str) -> None:
                    self.master.after(0, lambda m=msg: self.status_var.set(m))

                result = self.scans.scan_website(website_id, progress=progress)
                self.master.after(0, lambda: self._on_scan_done(website_id, result, None))
            except Exception as exc:  # noqa: BLE001
                logger.exception("Scan failed")
                self.master.after(0, lambda: self._on_scan_done(website_id, None, str(exc)))

        self._scan_thread = threading.Thread(target=worker, daemon=True)
        self._scan_thread.start()

    def _on_scan_done(
        self,
        website_id: int,
        result: Optional[HealthCheckResult],
        error: Optional[str],
    ) -> None:
        if error:
            self.status_var.set("Check failed")
            messagebox.showerror(
                "Check failed",
                "Something went wrong while checking.\n\n"
                f"{error}\n\n"
                "If your internet is unstable, try again on a better connection.",
            )
            return
        assert result is not None
        self.status_var.set(f"Finished — {status_plain(result.overall_status)}")
        self.refresh_list()
        if str(website_id) in self.tree.get_children(""):
            self.tree.selection_set(str(website_id))
        self.show_details(website_id)
        if result.overall_status == HealthStatus.CRITICAL:
            messagebox.showwarning(
                "Problems found",
                overall_summary(
                    result.overall_status,
                    self.websites.get_website(website_id).display_name  # type: ignore[union-attr]
                    if self.websites.get_website(website_id)
                    else "This website",
                )
                + "\n\nOpen the Results tab for step-by-step fixes.",
            )

    def export_selected(self) -> None:
        if self._selected_id is None:
            messagebox.showinfo("Select a website", "Click a website in the list first.")
            return
        latest = self.scans.latest(self._selected_id)
        site = self.websites.get_website(self._selected_id)
        if latest is None or site is None:
            messagebox.showinfo("Nothing to save", "Check the website first, then save a report.")
            return

        export_dir = Path(self.settings.get("export_folder", "exports"))
        if not export_dir.is_absolute():
            export_dir = Path.cwd() / export_dir
        paths = default_export_paths(export_dir, site)
        folder = filedialog.askdirectory(
            initialdir=str(export_dir),
            title="Choose folder for the report files",
        )
        if not folder:
            return
        out = Path(folder)
        written = [
            export_json(out / paths["json"].name, site, latest),
            export_csv(out / paths["csv"].name, site, latest),
            export_html(out / paths["html"].name, site, latest),
        ]
        self.status_var.set(f"Saved {len(written)} report files")
        if messagebox.askyesno(
            "Report saved",
            "Saved JSON, CSV, and HTML reports.\n\n"
            "Open the HTML report now? (You can print it to PDF from your browser.)",
        ):
            webbrowser.open(written[2].as_uri())

    def open_settings(self) -> None:
        dialog = tk.Toplevel(self.master)
        dialog.title("Settings")
        dialog.transient(self.master)
        dialog.grab_set()
        dialog.geometry("520x620")
        frm = ttk.Frame(dialog, padding=16)
        frm.pack(fill=tk.BOTH, expand=True)

        current = self.settings.get_all()
        fields: dict[str, tk.StringVar] = {
            "timeout_seconds": tk.StringVar(value=current.get("timeout_seconds", "10")),
            "dns_server": tk.StringVar(value=current.get("dns_server", "")),
            "check_interval": tk.StringVar(value=current.get("check_interval", "manual")),
            "notify_on": tk.StringVar(value=current.get("notify_on", "critical")),
            "notify_desktop": tk.StringVar(value=current.get("notify_desktop", "1")),
            "export_folder": tk.StringVar(value=current.get("export_folder", "exports")),
            "slack_webhook": tk.StringVar(value=current.get("slack_webhook", "")),
            "discord_webhook": tk.StringVar(value=current.get("discord_webhook", "")),
            "teams_webhook": tk.StringVar(value=current.get("teams_webhook", "")),
            "generic_webhook": tk.StringVar(value=current.get("generic_webhook", "")),
            "smtp_host": tk.StringVar(value=current.get("smtp_host", "")),
            "smtp_port": tk.StringVar(value=current.get("smtp_port", "587")),
            "smtp_username": tk.StringVar(value=current.get("smtp_username", "")),
            "smtp_password": tk.StringVar(value=current.get("smtp_password", "")),
            "mail_from": tk.StringVar(value=current.get("mail_from", "")),
            "mail_to": tk.StringVar(value=current.get("mail_to", "")),
        }

        canvas = tk.Canvas(frm, highlightthickness=0)
        scroll = ttk.Scrollbar(frm, orient=tk.VERTICAL, command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        def add_section(title: str) -> None:
            ttk.Label(inner, text=title, style="Header.TLabel").pack(anchor=tk.W, pady=(12, 4))

        def add_field(label: str, key: str, hint: str = "") -> None:
            ttk.Label(inner, text=label).pack(anchor=tk.W, pady=(6, 0))
            ttk.Entry(inner, textvariable=fields[key], width=64).pack(fill=tk.X)
            if hint:
                ttk.Label(inner, text=hint, style="Hint.TLabel").pack(anchor=tk.W)

        add_section("General")
        add_field("Wait time (seconds)", "timeout_seconds", "Increase if your internet is slow.")
        add_field("DNS server (optional)", "dns_server", "Leave blank to use your computer's DNS.")
        add_field(
            "Automatic checks for all sites",
            "check_interval",
            "manual | hourly | every_6_hours | daily | weekly",
        )
        add_field("Report folder", "export_folder")

        add_section("Alerts")
        add_field(
            "When to alert",
            "notify_on",
            "critical = only serious problems · warning · always · never",
        )
        add_field("Windows desktop alerts (1=yes, 0=no)", "notify_desktop")
        add_field("Slack webhook URL", "slack_webhook")
        add_field("Discord webhook URL", "discord_webhook")
        add_field("Microsoft Teams webhook URL", "teams_webhook")
        add_field("Generic webhook URL", "generic_webhook")

        add_section("Email alerts (optional)")
        add_field("SMTP host", "smtp_host")
        add_field("SMTP port", "smtp_port")
        add_field("SMTP username", "smtp_username")
        add_field("SMTP password", "smtp_password")
        add_field("From address", "mail_from")
        add_field("To address", "mail_to")

        def save() -> None:
            for key, var in fields.items():
                self.settings.set(key, var.get().strip())
            dialog.destroy()
            self.status_var.set("Settings saved")

        ttk.Button(inner, text="Save settings", style="Accent.TButton", command=save).pack(
            pady=16
        )

    def show_help(self) -> None:
        messagebox.showinfo(
            "How to use Website Health Manager",
            "1) Type a website in Quick check and click Check now.\n"
            "2) Wait for the results on the right.\n"
            "3) Read the Results tab — green/OK is fine, Missing/Needs fixing should be corrected.\n"
            "4) Use Save report to create files you can send to a customer or developer.\n\n"
            "If many items say Couldn't check, your Wi‑Fi may be unstable — try again later.\n\n"
            "Automatic checks and Slack/Teams/Discord alerts are in Settings.",
        )
