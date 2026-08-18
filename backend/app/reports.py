"""Local audit representations generated from one deterministic AuditState."""

from __future__ import annotations

import csv
import io
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from reportlab.lib import colors  # type: ignore[import-untyped]
from reportlab.lib.pagesizes import A4  # type: ignore[import-untyped]
from reportlab.lib.styles import getSampleStyleSheet  # type: ignore[import-untyped]
from reportlab.lib.units import mm  # type: ignore[import-untyped]
from reportlab.pdfgen.canvas import Canvas  # type: ignore[import-untyped]
from reportlab.platypus import (  # type: ignore[import-untyped]
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from backend.app import schemas


def format_bytes(value: int | None) -> str:
    if value is None:
        return "Unknown"
    sign = "-" if value < 0 else ""
    absolute = abs(value)
    units = ((1_000_000_000, "GB"), (1_000_000, "MB"), (1_000, "KB"))
    for divisor, label in units:
        if absolute >= divisor:
            amount = (Decimal(absolute) / Decimal(divisor)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            rendered = format(amount, "f").rstrip("0").rstrip(".")
            return f"{sign}{rendered} {label}"
    return f"{value} bytes"


def format_local_timestamp(
    value: datetime, timezone: str, *, include_seconds: bool = False
) -> str:
    pattern = "%d %b %Y · %H:%M:%S" if include_seconds else "%d %b %Y · %H:%M"
    return value.astimezone(ZoneInfo(timezone)).strftime(pattern)


def audit_json(state: schemas.AuditState) -> bytes:
    return state.model_dump_json(indent=2).encode("utf-8")


def audit_csv(state: schemas.AuditState) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(["Dachik audit", state.audit_id])
    writer.writerow(["generated_through_utc", state.as_of_timestamp.isoformat()])
    writer.writerow(["initial_tracking_balance_bytes", state.initial_tracking_balance_bytes])
    writer.writerow(["total_trusted_bytes", state.total_observed_bytes])
    writer.writerow(["accounted_remainder_bytes", state.accounted_remainder_bytes])
    writer.writerow(["measured_duration_seconds", state.measured_duration_seconds])
    writer.writerow(["known_inactive_duration_seconds", state.known_inactive_duration_seconds])
    writer.writerow(["unknown_duration_seconds", state.unknown_duration_seconds])
    writer.writerow([])
    writer.writerow(
        [
            "bucket_start_utc",
            "bucket_end_utc",
            "rx_bytes",
            "tx_bytes",
            "total_bytes",
            "ending_accounted_remainder_bytes",
            "measured_seconds",
            "known_inactive_seconds",
            "unknown_seconds",
            "state",
            "boundary_spanning_bytes",
        ]
    )
    for bucket in state.hourly:
        writer.writerow(
            [
                bucket.start.isoformat(),
                bucket.end.isoformat(),
                bucket.observed_rx_bytes,
                bucket.observed_tx_bytes,
                bucket.total_observed_bytes,
                bucket.ending_accounted_remainder_bytes,
                bucket.measured_duration_seconds,
                bucket.known_inactive_duration_seconds,
                bucket.unknown_duration_seconds,
                bucket.state,
                bucket.boundary_spanning_bytes,
            ]
        )
    return stream.getvalue().encode("utf-8")


def audit_pdf(state: schemas.AuditState) -> bytes:
    stream = io.BytesIO()
    document = SimpleDocTemplate(
        stream,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=f"Dachik audit - {state.provider_name}",
        author="Dachik",
        pageCompression=0,
    )
    styles = getSampleStyleSheet()
    local_timezone = ZoneInfo(state.timezone)
    story: list[object] = [
        Paragraph("DACHIK DATA AUDIT", styles["Title"]),
        Paragraph(f"{state.provider_name} - {state.plan_name}", styles["Heading2"]),
        Paragraph(
            "In progress" if state.audit_status == "in_progress" else "Final",
            styles["Heading3"],
        ),
        Paragraph(
            f"Generated through {format_local_timestamp(state.as_of_timestamp, state.timezone)}",
            styles["BodyText"],
        ),
        Paragraph(f"Times shown in {state.timezone}", styles["BodyText"]),
        Spacer(1, 8 * mm),
    ]
    summary = [
        ["Original plan allowance", format_bytes(state.original_allowance_bytes)],
        ["Starting network balance", format_bytes(state.initial_tracking_balance_bytes)],
        ["Dachik observed", format_bytes(state.total_observed_bytes)],
        ["Dachik-accounted remainder", format_bytes(state.accounted_remainder_bytes)],
        ["Latest network-reported balance", format_bytes(state.latest_provider_balance_bytes)],
        ["Measurement quality", state.evidence_quality.title()],
        ["Measurement boundary", "This Mac"],
    ]
    story.extend([_table(summary), Spacer(1, 6 * mm)])
    story.append(
        Paragraph(
            f"Dachik observed {format_bytes(state.total_observed_bytes)} of traffic on "
            "this Mac after tracking began.",
            styles["BodyText"],
        )
    )
    if state.initial_tracking_balance_bytes is not None:
        story.append(
            Paragraph(
                f"Based on the {format_bytes(state.initial_tracking_balance_bytes)} "
                "network balance reported when tracking started, Dachik accounts for "
                f"{format_bytes(state.accounted_remainder_bytes)} remaining.",
                styles["BodyText"],
            )
        )
    if state.usage_exceeds_starting_balance:
        story.append(
            Paragraph(
                "Dachik observed usage beyond the balance reported when tracking began. "
                "The underlying measured bytes remain preserved.",
                styles["BodyText"],
            )
        )
    if state.comparisons:
        latest = state.comparisons[-1]
        story.extend(
            [
                Paragraph("Latest aligned network comparison", styles["Heading2"]),
                Paragraph(latest.conclusion, styles["BodyText"]),
                _table(
                    [
                        [
                            "Provider-reported deduction",
                            format_bytes(latest.provider_deduction_bytes),
                        ],
                        ["Dachik usage in same window", format_bytes(latest.dachik_usage_bytes)],
                        ["Observed difference", format_bytes(latest.observed_difference_bytes)],
                        ["Evidence quality", latest.evidence_quality.title()],
                    ]
                ),
            ]
        )
    story.extend([PageBreak(), Paragraph("Daily breakdown", styles["Heading1"])])
    story.append(
        _table(
            [["Day", "Observed", "Measured", "Unknown", "Ending balance"]]
            + [
                [
                    item.start.astimezone(local_timezone).strftime("%d %b %Y"),
                    format_bytes(item.total_observed_bytes),
                    _duration(item.measured_duration_seconds),
                    _duration(item.unknown_duration_seconds),
                    format_bytes(item.ending_accounted_remainder_bytes),
                ]
                for item in state.daily
            ]
        )
    )
    story.extend([PageBreak(), Paragraph("Hourly ledger", styles["Heading1"])])
    story.append(
        _table(
            [[f"Period ({state.timezone})", "Observed", "State", "Unknown"]]
            + [
                [
                    f"{item.start.astimezone(local_timezone):%d %b %H:%M}-"
                    f"{item.end.astimezone(local_timezone):%H:%M}",
                    format_bytes(item.total_observed_bytes),
                    item.state.replace("_", " ").title(),
                    _duration(item.unknown_duration_seconds),
                ]
                for item in state.hourly
            ]
        )
    )
    story.extend([PageBreak(), Paragraph("Evidence timeline", styles["Heading1"])])
    for event in state.events:
        story.append(
            Paragraph(
                f"{format_local_timestamp(event.timestamp, state.timezone, include_seconds=True)} "
                f"- {event.description}",
                styles["BodyText"],
            )
        )
        story.append(Spacer(1, 2 * mm))
    if state.isp_checkpoints:
        story.append(Paragraph("Network balance checkpoints", styles["Heading2"]))
        story.append(
            _table(
                [["Timestamp", "Network reported", "Dachik accounted"]]
                + [
                    [
                        format_local_timestamp(
                            item.timestamp, state.timezone, include_seconds=True
                        ),
                        format_bytes(item.normalized_bytes),
                        format_bytes(item.accounted_remainder_bytes),
                    ]
                    for item in state.isp_checkpoints
                ]
            )
        )
    story.extend([PageBreak(), Paragraph("Methodology and limitations", styles["Heading1"])])
    technical = [
        ["Audit ID", state.audit_id],
        ["Methodology", state.methodology_version],
        ["Timezone", state.timezone],
        ["Audit start", format_local_timestamp(state.audit_start, state.timezone)],
        ["As of", format_local_timestamp(state.as_of_timestamp, state.timezone)],
        [
            "Latest trusted observation",
            format_local_timestamp(
                state.latest_trusted_observation, state.timezone, include_seconds=True
            )
            if state.latest_trusted_observation is not None
            else "None",
        ],
        ["Measured duration", _duration(state.measured_duration_seconds)],
        ["Known non-attributable", _duration(state.known_inactive_duration_seconds)],
        ["Unknown duration", _duration(state.unknown_duration_seconds)],
    ]
    story.append(_table(technical))
    for limitation in state.limitations:
        story.append(Paragraph(f"- {limitation}", styles["BodyText"]))
    story.append(
        Paragraph(
            "Privacy: this report contains byte counters and accounting metadata only. "
            "It contains no packet payloads, URLs, DNS history, browsing history, "
            "or Wi-Fi identity.",
            styles["BodyText"],
        )
    )

    def footer(canvas: Canvas, _: object) -> None:
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#59665e"))
        canvas.drawString(18 * mm, 10 * mm, "Dachik - privacy-first local measurement")
        canvas.drawRightString(192 * mm, 10 * mm, f"Page {canvas.getPageNumber()}")
        canvas.restoreState()

    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return stream.getvalue()


def _table(rows: list[list[str]]) -> Table:
    table = Table(rows, repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("FONT", (0, 0), (-1, -1), "Helvetica", 8.5),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8f0e9")),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#c8d4ca")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return table


def _duration(seconds: int) -> str:
    hours, remainder = divmod(seconds, 3600)
    minutes = remainder // 60
    return f"{hours}h {minutes}m"


def safe_report_filename(provider: str, timestamp: datetime, suffix: str) -> str:
    safe = "".join(character.lower() if character.isalnum() else "-" for character in provider)
    safe = "-".join(filter(None, safe.split("-")))[:40] or "data-plan"
    return f"dachik-audit-{safe}-{timestamp:%Y%m%d}.{suffix}"
