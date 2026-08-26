"""Weekly-report PDF rendering (item 2, ADR-0063).

Pure-Python (reportlab) — no system libraries (Pango/Cairo/wkhtmltopdf)
needed, unlike an HTML-to-PDF renderer, which matters here since the
Docker image already tracks size closely (runtime-base vs
runtime-satellite, see ADR-0056/CI). Only ever renders numbers the caller
already computed (`WeeklyReportOut`) — this module has no database or
network access of its own.
"""

from __future__ import annotations

import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.locations.schemas import WeeklyReportOut

_DATE_FMT = "%d/%m/%Y"
_DATETIME_FMT = "%d/%m/%Y %H:%M"


def render_weekly_report_pdf(report: WeeklyReportOut) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        title=f"Relatório semanal — {report.location_name}",
    )
    styles = getSampleStyleSheet()
    muted = ParagraphStyle("muted", parent=styles["Normal"], textColor=colors.grey)

    story = [
        Paragraph("StormPulse — Relatório semanal", styles["Title"]),
        Paragraph(
            f"{report.location_name}" + (f" · cultura: {report.crop}" if report.crop else ""),
            styles["Heading2"],
        ),
        Paragraph(
            f"Período: {report.period_start.strftime(_DATE_FMT)} a "
            f"{report.period_end.strftime(_DATE_FMT)}",
            styles["Normal"],
        ),
        Spacer(1, 0.5 * cm),
    ]

    stats_table = Table(
        [
            ["Chuva acumulada", "Dias secos"],
            [f"{report.rainfall_total_mm:.1f} mm", f"{report.dry_days_count}/7"],
        ],
        colWidths=[8 * cm, 8 * cm],
    )
    stats_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 1), (-1, 1), 14),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d1d5db")),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.append(stats_table)
    story.append(Spacer(1, 0.8 * cm))

    story.append(Paragraph("Alertas no período", styles["Heading3"]))
    if not report.alerts:
        story.append(Paragraph("Nenhum alerta de geada ou seca no período.", muted))
    else:
        for alert in report.alerts:
            story.append(
                Paragraph(
                    f"<b>{alert.created_at.strftime(_DATE_FMT)}</b> — {alert.title}: "
                    f"{alert.message}",
                    styles["Normal"],
                )
            )
    story.append(Spacer(1, 0.6 * cm))

    story.append(Paragraph("NDVI no período", styles["Heading3"]))
    if not report.ndvi_readings:
        story.append(Paragraph("Nenhuma leitura de NDVI no período.", muted))
    else:
        for reading in report.ndvi_readings:
            suffix = " (simulado)" if reading.is_mock else ""
            story.append(
                Paragraph(
                    f"<b>{reading.observed_at.strftime(_DATE_FMT)}</b> — "
                    f"NDVI {reading.ndvi_mean:.2f}{suffix}",
                    styles["Normal"],
                )
            )
    story.append(Spacer(1, 1 * cm))

    story.append(Paragraph(f"Gerado em {report.generated_at.strftime(_DATETIME_FMT)}", muted))

    doc.build(story)
    return buffer.getvalue()
