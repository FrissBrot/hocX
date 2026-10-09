"""Kartendruck-PDF (Auftrag Abschnitt 15): Tourübersicht, Marschzeittabelle, Höhenprofil und
die eigentlichen Kartenblätter (map_print_service.py) in einem PDF. Baut das LaTeX-Dokument
per Hand zusammen (Python-Stringbau, kein Jinja2 - dieselbe Konvention wie export_service.py,
siehe dessen `_render_*`-Methoden) statt die bestehende, Protokoll-spezifische
`ExportService`-Pipeline (Themes, Blöcke, Word-Import-Profile) zu verbiegen: eine Tour-PDF hat
keine dieser Konzepte, nur eine feste Titelseite + Marschzeittabelle + Höhenprofil + N
Kartenblätter.

Der pdflatex-Kompilierlauf unten dupliziert bewusst (statt zu importieren)
`ExportService._compile_pdf_async`s Sicherheits-Härtung (Speicher-/CPU-Limits,
`-no-shell-escape`, `-cnf-line=openin_any=p`) - beide Pfade kompilieren letztlich Fremd-/
Nutzer-beeinflussten Text (dort Tenant-Themes, hier Tournamen/Beschreibungen), brauchen also
dieselben Schutzmassnahmen. Eine gemeinsame Extraktion in ein Utility-Modul wäre sauberer,
hätte hier aber `export_service.py` (2400+ Zeilen, zentrale Protokoll-Export-Funktion)
anfassen müssen für ein nur lose verwandtes Feature - das Duplizieren dieser rund 30 Zeilen
ist das kleinere Risiko."""

from __future__ import annotations

import asyncio
import io
import os
import resource
import shutil
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from geoalchemy2.shape import to_shape
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.march_time import MarchTimeTable
from app.core.print_layout import MARGIN_BOTTOM_MM, MARGIN_SIDE_MM, MARGIN_TOP_MM, PageGeometry, RoutePoint2D, compute_page_geometry, plan_sheets
from app.core.swiss_coords import wgs84_to_lv95
from app.models import HikingTour
from app.services.map_print_service import MapPrintService, OverlayWaypoint, SheetOverlay
from app.services.march_time_service import MarchTimeService

_COMPILE_MEMORY_LIMIT_BYTES = 2 * 1024 * 1024 * 1024
_COMPILE_CPU_LIMIT_SECONDS = 90
_COMPILE_TIMEOUT_SECONDS = 120
_compile_semaphore = asyncio.Semaphore(2)

_LATEX_ESCAPE_MAP = {
    "\\": "\\textbackslash{}",
    "&": "\\&",
    "%": "\\%",
    "$": "\\$",
    "#": "\\#",
    "_": "\\_",
    "{": "\\{",
    "}": "\\}",
    "~": "\\textasciitilde{}",
    "^": "\\textasciicircum{}",
}


def _escape_latex(value) -> str:
    return "".join(_LATEX_ESCAPE_MAP.get(c, c) for c in str(value))


def _limit_compile_resources() -> None:
    resource.setrlimit(resource.RLIMIT_AS, (_COMPILE_MEMORY_LIMIT_BYTES, _COMPILE_MEMORY_LIMIT_BYTES))
    resource.setrlimit(resource.RLIMIT_CPU, (_COMPILE_CPU_LIMIT_SECONDS, _COMPILE_CPU_LIMIT_SECONDS))


async def _compile_pdf(main_tex_path: Path) -> None:
    command = [
        "pdflatex",
        "-interaction=nonstopmode",
        "-halt-on-error",
        "-no-shell-escape",
        "-cnf-line=openin_any=p",
        "-cnf-line=openout_any=p",
        f"-output-directory={main_tex_path.parent.as_posix()}",
        main_tex_path.as_posix(),
    ]
    compile_env = {**os.environ, "TEXMFOUTPUT": main_tex_path.parent.as_posix()}
    async with _compile_semaphore:
        proc = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=main_tex_path.parent,
            env=compile_env,
            preexec_fn=_limit_compile_resources,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=_COMPILE_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            raise RuntimeError("PDF-Kompilierung nach 120s abgebrochen")
    if proc.returncode != 0:
        raise RuntimeError(f"pdflatex fehlgeschlagen: {stderr.decode(errors='replace') or stdout.decode(errors='replace')}")


class HikingTourPrintService:
    def __init__(self, map_print_service: MapPrintService | None = None, march_time_service: MarchTimeService | None = None) -> None:
        self.map_print_service = map_print_service or MapPrintService()
        self.march_time_service = march_time_service or MarchTimeService()

    def _route_points_latlon(self, tour: HikingTour) -> list[tuple[float, float, float]]:
        """[(distance_m, lat, lon), ...] entlang der konkatenierten Routen-Geometrie."""
        points: list[tuple[float, float, float]] = []
        cumulative = 0.0
        for leg in tour.route_legs:
            line = to_shape(leg.geom)
            for lon, lat in line.coords:
                if points and points[-1][1] == lat and points[-1][2] == lon:
                    continue
                points.append((cumulative, lat, lon))
            cumulative += leg.distance_m
        return points

    def _march_table_or_none(self, tour: HikingTour) -> MarchTimeTable | None:
        try:
            return self.march_time_service.build_table(tour)
        except ValueError:
            # Marschzeittabelle ist eine sinnvolle Ergaenzung, aber kein Blocker fuers
            # Drucken selbst (z.B. wenn die Route seit der letzten Berechnung minimal
            # veraltet ist) - siehe Auftrag Abschnitt 15: "zusaetzlich eine PDF-
            # Marschzeittabelle", nicht "nur mit Marschzeittabelle".
            return None

    def _render_elevation_chart(self, tour: HikingTour, export_dir: Path) -> Path | None:
        if not tour.elevation_profile_json:
            return None
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        distances_km = [p["distance_m"] / 1000 for p in tour.elevation_profile_json]
        elevations = [p["elevation_m"] for p in tour.elevation_profile_json]
        fig, ax = plt.subplots(figsize=(7.0, 2.4))
        ax.fill_between(distances_km, elevations, min(elevations), color="#5a3ca0", alpha=0.25)
        ax.plot(distances_km, elevations, color="#5a3ca0", linewidth=1.5)
        ax.set_xlabel("Distanz (km)")
        ax.set_ylabel("Höhe (m ü. M.)")
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        path = export_dir / "elevation.png"
        fig.savefig(path, dpi=150)
        plt.close(fig)
        return path

    def _march_table_latex(self, table: MarchTimeTable) -> str:
        rows = [
            r"\begin{longtable}{r p{5cm} r r r r}",
            r"\toprule",
            r"\# & Punkt & Distanz & Marschzeit & Ankunft & Pause \\",
            r"\midrule",
        ]
        for entry in table.entries:
            arrival = entry.planned_arrival.strftime("%H:%M") if entry.planned_arrival else "–"
            break_text = f"{entry.break_minutes} min" if entry.break_minutes else "–"
            rows.append(
                f"{entry.sequence} & {_escape_latex(entry.label or entry.kind)} & "
                f"{entry.cumulative_distance_m / 1000:.1f} km & {int(round(entry.cumulative_duration_minutes))} min & "
                f"{arrival} & {break_text} \\\\"
            )
        rows.append(r"\bottomrule")
        rows.append(r"\end{longtable}")
        return "\n".join(rows)

    def _build_main_tex(
        self,
        *,
        tour: HikingTour,
        geometry: PageGeometry,
        sheets,
        sheet_image_names: list[str],
        elevation_chart_name: str | None,
        march_table: MarchTimeTable | None,
    ) -> str:
        lines = [
            r"\documentclass[10pt]{article}",
            f"\\usepackage[paperwidth={geometry.width_mm}mm,paperheight={geometry.height_mm}mm,"
            f"top={MARGIN_TOP_MM}mm,bottom={MARGIN_BOTTOM_MM}mm,left={MARGIN_SIDE_MM}mm,right={MARGIN_SIDE_MM}mm]{{geometry}}",
            r"\usepackage[utf8]{inputenc}",
            r"\usepackage{graphicx}",
            r"\usepackage{booktabs}",
            r"\usepackage{longtable}",
            r"\pagestyle{empty}",
            r"\begin{document}",
            r"\begin{center}",
            f"{{\\LARGE {_escape_latex(tour.title)}}}\\\\[4mm]",
        ]
        if tour.description:
            lines.append(f"{_escape_latex(tour.description)}\\\\[4mm]")
        distance_km = round((tour.route_distance_m or 0) / 1000, 1)
        lines.append(
            f"Distanz: {distance_km} km \\quad Aufstieg: {round(tour.route_ascent_m or 0)} m \\quad "
            f"Abstieg: {round(tour.route_descent_m or 0)} m\\\\"
        )
        lines.append(f"Massstab 1:{geometry.scale} \\quad {geometry.paper} {geometry.orientation} \\quad {len(sheets)} Kartenblätter\\\\")
        lines.append(r"\end{center}")
        lines.append(r"\newpage")

        if march_table is not None:
            lines.append(self._march_table_latex(march_table))
            lines.append(r"\newpage")

        if elevation_chart_name is not None:
            lines.append(r"\begin{center}")
            lines.append(f"\\includegraphics[width=\\linewidth]{{{elevation_chart_name}}}")
            lines.append(r"\end{center}")
            lines.append(r"\newpage")

        for index, (sheet, image_name) in enumerate(zip(sheets, sheet_image_names)):
            lines.append(r"\noindent")
            lines.append(f"\\includegraphics[width={geometry.printable_width_mm}mm,height={geometry.printable_height_mm}mm]{{{image_name}}}")
            if index < len(sheets) - 1:
                lines.append(r"\newpage")

        lines.append(r"\end{document}")
        return "\n".join(lines)

    async def export_pdf(
        self,
        db: Session,
        tour: HikingTour,
        *,
        paper: str,
        orientation: str,
        scale: int,
    ) -> tuple[bytes, int]:
        """PDF-Inhalt plus Anzahl Kartenblaetter. Ablage als StoredFile (Mandanten-Speicher,
        Dateiuebersicht) macht das hocX-Backend - dieser Service hat keinen Zugriff darauf."""
        if not tour.route_legs:
            raise ValueError("Route muss zuerst berechnet werden, bevor gedruckt werden kann")

        geometry = compute_page_geometry(paper=paper, orientation=orientation, scale=scale)
        route_points = self._route_points_latlon(tour)
        if len(route_points) < 2:
            raise ValueError("Route ist zu kurz zum Drucken")

        points_2d = [RoutePoint2D(distance_m=d, x=(xy := wgs84_to_lv95(lat, lon))[0], y=xy[1]) for d, lat, lon in route_points]
        sheets = plan_sheets(points_2d, ground_width_m=geometry.ground_width_m, ground_height_m=geometry.ground_height_m, scale=scale)
        if not sheets:
            raise ValueError("Keine Route zum Drucken vorhanden")

        export_dir = Path(settings.work_root) / "wanderplaner-print" / uuid4().hex
        export_dir.mkdir(parents=True, exist_ok=True)

        overlay_waypoints = []
        for waypoint in tour.waypoints:
            point = to_shape(waypoint.point)
            overlay_waypoints.append(OverlayWaypoint(lat=point.y, lon=point.x, kind=waypoint.kind, label=waypoint.label))
        route_latlon = [(lat, lon) for _, lat, lon in route_points]

        sheet_image_names: list[str] = []
        for sheet in sheets:
            overlay = SheetOverlay(route_points=route_latlon, waypoints=overlay_waypoints, sheet_number=sheet.sequence, total_sheets=len(sheets))
            image = self.map_print_service.render_sheet_image(sheet, geometry, overlay)
            image_name = f"sheet_{sheet.sequence}.jpg"
            image.save(export_dir / image_name, quality=88)
            sheet_image_names.append(image_name)

        elevation_chart_path = self._render_elevation_chart(tour, export_dir)
        march_table = self._march_table_or_none(tour)

        main_tex = self._build_main_tex(
            tour=tour,
            geometry=geometry,
            sheets=sheets,
            sheet_image_names=sheet_image_names,
            elevation_chart_name=elevation_chart_path.name if elevation_chart_path else None,
            march_table=march_table,
        )
        main_tex_path = export_dir / "main.tex"
        main_tex_path.write_text(main_tex, encoding="utf-8")

        # Ein pdflatex-Fehler hier ist NICHT kuratiert (kein Nutzer-Validierungsfehler wie
        # "Route fehlt") - eine kaputte Vorlage/fehlendes Paket ist ein echter Bug und soll
        # ueber die zentrale Fehlererfassung in system_error_log landen (CLAUDE.md), deshalb
        # bewusst kein except hier - der RuntimeError laeuft unveraendert zur Route hoch, die
        # ihn mit `from exc` in eine HTTPException uebersetzt.
        try:
            await _compile_pdf(main_tex_path)
            pdf_bytes = (export_dir / "main.pdf").read_bytes()
        finally:
            shutil.rmtree(export_dir, ignore_errors=True)
        return pdf_bytes, len(sheets)
