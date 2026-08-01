"""Export health reports (Phase 5): JSON, CSV, HTML (print-to-PDF), ZIP download."""

from __future__ import annotations

import csv
import io
import json
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from whm.domain.models import HealthCheckResult, Website
from whm.presentation.copy import category_plain, finding_plain, status_plain


def _safe_name(domain: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-._" else "_" for ch in domain)


def _report_base_name(website: Website) -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{_safe_name(website.domain)}-{stamp}"


_IGNORED_REPORT_CATEGORIES = frozenset({"security", "performance"})


def _report_findings(result: HealthCheckResult):
    return [f for f in result.findings if f.category not in _IGNORED_REPORT_CATEGORIES]


def render_json(website: Website, result: HealthCheckResult) -> str:
    payload: dict[str, Any] = {
        "website": {
            "name": website.display_name,
            "domain": website.domain,
            "url": website.url,
        },
        "checked_at": result.checked_at.isoformat(),
        "overall": result.overall_status.value,
        "risk": result.risk_level.value,
        "findings": [
            {
                "area": f.category,
                "title": f.title,
                "status": f.status.value,
                "message": f.message,
                "recommendation": f.recommendation,
            }
            for f in _report_findings(result)
        ],
    }
    return json.dumps(payload, indent=2)


def render_csv(website: Website, result: HealthCheckResult) -> str:
    handle = io.StringIO()
    writer = csv.writer(handle)
    writer.writerow(
        [
            "Website",
            "Domain",
            "Checked at",
            "Overall",
            "Area",
            "Title",
            "Status",
            "Message",
            "What to do",
        ]
    )
    for finding in _report_findings(result):
        writer.writerow(
            [
                website.display_name,
                website.domain,
                result.checked_at.isoformat(),
                status_plain(result.overall_status),
                category_plain(finding.category),
                finding.title,
                finding_plain(finding.status),
                finding.message,
                finding.recommendation,
            ]
        )
    return handle.getvalue()


def render_html(website: Website, result: HealthCheckResult) -> str:
    """Editorial HTML report — open in a browser and Print → Save as PDF."""
    rows = []
    for finding in _report_findings(result):
        rows.append(
            "<tr>"
            f"<td>{_e(category_plain(finding.category))}</td>"
            f"<td><span class='pill {finding.status.value}'>{_e(finding_plain(finding.status))}</span></td>"
            f"<td><strong>{_e(finding.title)}</strong><br><span class='dim'>{_e(finding.message)}</span></td>"
            f"<td>{_e(finding.recommendation)}</td>"
            "</tr>"
        )
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>WHM report — {_e(website.display_name)}</title>
<style>
:root {{
  --ink:#0b0f14; --paper:#f3ebe2; --dim:#9a9086; --line:rgba(11,15,20,.12);
  --signal:#1f9d6d; --warn:#b7791f; --crit:#c53030;
}}
* {{ box-sizing:border-box; }}
body {{
  margin:0; font-family:"Segoe UI", Bahnschrift, sans-serif;
  color:var(--ink); background:
    radial-gradient(1200px 600px at 10% -10%, #d9f5e8, transparent 55%),
    radial-gradient(900px 500px at 100% 0%, #f7e6c8, transparent 50%),
    var(--paper);
}}
.wrap {{ max-width:980px; margin:0 auto; padding:3rem 1.5rem 4rem; }}
.brand {{ font-family:Cambria, Georgia, serif; font-size:3.5rem; margin:0; letter-spacing:-.03em; }}
.tag {{ color:var(--dim); margin:.4rem 0 1.6rem; }}
h1 {{ font-family:Cambria, Georgia, serif; font-weight:500; font-size:2rem; margin:0 0 .4rem; }}
.meta {{ color:var(--dim); margin-bottom:1.8rem; line-height:1.5; }}
table {{ width:100%; border-collapse:collapse; background:rgba(255,255,255,.55); backdrop-filter:blur(8px); border-radius:18px; overflow:hidden; box-shadow:0 20px 50px rgba(11,15,20,.08); }}
th, td {{ border-bottom:1px solid var(--line); padding:.85rem .9rem; text-align:left; vertical-align:top; }}
th {{ font-size:.78rem; letter-spacing:.12em; text-transform:uppercase; color:var(--dim); background:rgba(255,255,255,.5); }}
.dim {{ color:#5c564f; }}
.pill {{ display:inline-block; padding:.2rem .55rem; border-radius:999px; font-size:.75rem; }}
.pill.correct,.pill.info {{ background:#def7ec; color:var(--signal); }}
.pill.incorrect {{ background:#fef3c7; color:var(--warn); }}
.pill.missing {{ background:#ffe4e1; color:var(--crit); }}
.pill.inconclusive {{ background:#e8edf3; color:#4a5568; }}
.foot {{ margin-top:1.4rem; color:var(--dim); font-size:.9rem; }}
@media print {{ body {{ background:#fff; }} table {{ box-shadow:none; }} }}
</style></head><body><div class="wrap">
<p class="brand">WHM</p>
<p class="tag">Know why it broke.</p>
<h1>{_e(website.display_name)}</h1>
<p class="meta">
{_e(website.domain)} · Checked {result.checked_at.strftime("%Y-%m-%d %H:%M")} UTC<br>
Overall: <strong>{_e(status_plain(result.overall_status))}</strong>
</p>
<table>
<thead><tr><th>Area</th><th>Result</th><th>Details</th><th>What to do</th></tr></thead>
<tbody>
{"".join(rows)}
</tbody></table>
<p class="foot">Tip: Print → Save as PDF for a polished client-ready report.</p>
</div></body></html>
"""


def export_json(path: Path, website: Website, result: HealthCheckResult) -> Path:
    path.write_text(render_json(website, result), encoding="utf-8")
    return path


def export_csv(path: Path, website: Website, result: HealthCheckResult) -> Path:
    path.write_text(render_csv(website, result), encoding="utf-8")
    return path


def export_html(path: Path, website: Website, result: HealthCheckResult) -> Path:
    path.write_text(render_html(website, result), encoding="utf-8")
    return path


def build_report_bundle(website: Website, result: HealthCheckResult) -> tuple[str, bytes]:
    """Build a ZIP (HTML + CSV + JSON) for browser download to the user's PC."""
    base = _report_base_name(website)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"{base}.html", render_html(website, result))
        archive.writestr(f"{base}.csv", render_csv(website, result))
        archive.writestr(f"{base}.json", render_json(website, result))
    return f"{base}-report.zip", buffer.getvalue()


def _e(value: str) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def default_export_paths(folder: Path, website: Website) -> dict[str, Path]:
    folder.mkdir(parents=True, exist_ok=True)
    base = _report_base_name(website)
    return {
        "json": folder / f"{base}.json",
        "csv": folder / f"{base}.csv",
        "html": folder / f"{base}.html",
    }
