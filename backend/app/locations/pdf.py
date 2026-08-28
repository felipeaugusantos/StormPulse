"""Weekly-report PDF rendering (item 2, ADR-0063).

Pure-Python (reportlab) — no system libraries (Pango/Cairo/wkhtmltopdf)
needed, unlike an HTML-to-PDF renderer, which matters here since the
Docker image already tracks size closely (runtime-base vs
runtime-satellite, see ADR-0056/CI). Only ever renders numbers (and,
since item "imagem do talhão", already-fetched image bytes) the caller
already has — this module has no database or network access of its own.

Embedding the NDVI image (`Image`/`ImageReader` from `reportlab.platypus`)
does need Pillow — confirmed by reading reportlab's own source
(`ImageReader._read_image` calls `PIL.Image.open` directly, no
pure-Python fallback exists). Unlike GDAL/numpy/TATHU (the `satellite`
extra, deliberately kept out of the base image for size — see the
Dockerfile), Pillow is a plain wheel with no system libs of its own, and
this PDF endpoint is always on (not an optional satellite feature), so
it's a base dependency (see pyproject.toml), not a satellite-only one.
"""

from __future__ import annotations

import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.locations.schemas import WeeklyReportOut

_DATE_FMT = "%d/%m/%Y"
_DATETIME_FMT = "%d/%m/%Y %H:%M"
_NDVI_IMAGE_MAX_SIZE_CM = 8.0


def render_weekly_report_pdf(
    report: WeeklyReportOut, *, ndvi_image_png: bytes | None = None
) -> bytes:
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
            f"{report.location_name}"
            + (f" · cultura: {report.crop}" if report.crop else "")
            + (f" · área: {report.area_ha:.2f} ha" if report.area_ha is not None else ""),
            styles["Heading2"],
        ),
        Paragraph(
            f"Período: {report.period_start.strftime(_DATE_FMT)} a "
            f"{report.period_end.strftime(_DATE_FMT)}",
            styles["Normal"],
        ),
        Spacer(1, 0.5 * cm),
    ]

    if report.ai_summary:
        story.append(Paragraph(report.ai_summary, styles["Normal"]))
        story.append(Spacer(1, 0.5 * cm))

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
    story.append(
        Paragraph(
            "NDVI (Índice de Vegetação por Diferença Normalizada) mede o vigor da vegetação "
            "por satélite (Sentinel-2), de -1 a 1 — quanto mais alto, mais vegetação viva e "
            "saudável; valores baixos indicam solo exposto, vegetação esparsa ou estresse "
            "da planta.",
            muted,
        )
    )
    if ndvi_image_png:
        story.append(Spacer(1, 0.3 * cm))
        story.append(
            Image(
                io.BytesIO(ndvi_image_png),
                width=_NDVI_IMAGE_MAX_SIZE_CM * cm,
                height=_NDVI_IMAGE_MAX_SIZE_CM * cm,
            )
        )
        story.append(
            Paragraph(
                "Verde = vegetação mais vigorosa · vermelho/marrom = solo exposto ou "
                "vegetação em estresse. Áreas transparentes indicam nuvem ou dado indisponível.",
                muted,
            )
        )
        story.append(Spacer(1, 0.3 * cm))
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

    story.append(Paragraph("Desmatamento (DETER/PRODES, INPE)", styles["Heading3"]))
    if report.deforestation is None or not report.deforestation.checked_sources:
        story.append(
            Paragraph(
                "Checagem de desmatamento ainda não disponível para este talhão.",
                muted,
            )
        )
    else:
        deforestation = report.deforestation
        checked_label = " e ".join(deforestation.checked_sources)
        story.append(
            Paragraph(
                f"Consultado em {checked_label} (registros oficiais do INPE — cobre só os "
                "biomas Amazônia e Cerrado; fora dessas regiões, nenhum alerta encontrado "
                "não significa ausência de desmatamento, apenas que essas camadas não "
                "cobrem a área).",
                muted,
            )
        )
        if deforestation.last_checked_at is not None:
            story.append(
                Paragraph(
                    f"Última checagem: {deforestation.last_checked_at.strftime(_DATE_FMT)}",
                    muted,
                )
            )
        if not deforestation.alerts:
            story.append(Paragraph("Nenhum alerta de desmatamento encontrado.", styles["Normal"]))
        else:
            for dalert in deforestation.alerts:
                when = (
                    dalert.detected_at.strftime(_DATE_FMT)
                    if dalert.detected_at
                    else "data desconhecida"
                )
                area = f" · {dalert.area_ha:.2f} ha" if dalert.area_ha is not None else ""
                if dalert.municipio:
                    place = f" ({dalert.municipio}/{dalert.uf})"
                elif dalert.uf:
                    place = f" ({dalert.uf})"
                else:
                    place = ""
                story.append(
                    Paragraph(
                        f"<b>{when}</b> — {dalert.classname}{area}{place} [{dalert.source}]",
                        styles["Normal"],
                    )
                )
    story.append(Spacer(1, 1 * cm))

    if report.soil_moisture:
        moisture = report.soil_moisture
        story.append(Paragraph("Umidade do solo regional (NASA POWER)", styles["Heading3"]))
        story.append(
            Paragraph(
                "Estimativa por modelo (NASA), resolução regional (~50 km) — contexto além "
                "da chuva medida, nunca uma medição do talhão em si.",
                muted,
            )
        )
        story.append(
            Paragraph(
                f"<b>{moisture.observed_at.strftime(_DATE_FMT)}</b> — superfície "
                f"{moisture.surface_wetness_percent:.0f}% · raiz "
                f"{moisture.root_zone_wetness_percent:.0f}% · perfil "
                f"{moisture.profile_wetness_percent:.0f}%"
                + (" (simulado)" if moisture.is_mock else ""),
                styles["Normal"],
            )
        )
        story.append(Spacer(1, 1 * cm))

    story.append(Paragraph(f"Gerado em {report.generated_at.strftime(_DATETIME_FMT)}", muted))

    doc.build(story)
    return buffer.getvalue()
