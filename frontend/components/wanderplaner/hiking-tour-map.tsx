"use client";

import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useEffect, useRef, useState } from "react";

import { ElevationProfilePoint, HikingTourWaypointKind, TerrainDangerLevel, TerrainDangerSegment } from "@/types/api";

// Offizieller swisstopo-Vector-Tile-Style (Auftrag Abschnitt 1/2 - dieselbe Basiskarte wie
// map.geo.admin.ch, kostenlos, kein API-Key). Attribution ist Pflicht (siehe
// swisstopo-Nutzungsbedingungen, Wiki-Seite "Wanderplaner") - MapLibres AttributionControl
// zeigt sie automatisch aus dem Style an, hier nur kompakt statt ausgeklappt.
const SWISSTOPO_STYLE_URL = "https://vectortiles.geo.admin.ch/styles/ch.swisstopo.basemap.vt/style.json";
const SWITZERLAND_CENTER: [number, number] = [8.2275, 46.8182];

// Gefahreneinschätzung (Auftrag "Gefahreneinschätzung des Weges"): "alpine" (amtlicher Status
// Alpinwanderweg) hat Vorrang vor "steep_exposed" (Geländeanalyse auf normalen Wanderwegen),
// siehe app/core/route_danger.py::merge_with_official_status. Gleiches Token-Muster wie
// KIND_COLOR_TOKEN unten - "normal" bleibt die bisherige Routenfarbe.
const DANGER_COLOR_TOKEN: Record<TerrainDangerLevel, string> = {
  normal: "--accent-strong",
  steep_exposed: "--warning",
  alpine: "--info",
};

const KIND_COLOR_TOKEN: Record<HikingTourWaypointKind, string> = {
  START: "--success",
  END: "--danger",
  USER_DEFINED: "--accent",
  NAVIGATION: "--info",
  BREAK: "--warning",
  SUMMIT: "--accent-strong",
  PASS: "--accent-strong",
  HUT: "--info",
  WATER: "--info",
  DECISION: "--warning",
  EMERGENCY_EXIT: "--danger",
};

export type MapWaypoint = {
  id: string;
  kind: HikingTourWaypointKind;
  lat: number;
  lon: number;
  label?: string | null;
  description?: string | null;
  elevation_m?: number | null;
  break_minutes?: number | null;
};

const KIND_LABEL: Record<HikingTourWaypointKind, string> = {
  START: "Start", END: "Ziel", NAVIGATION: "Fixpunkt", BREAK: "Pausenplatz",
  SUMMIT: "Gipfel", PASS: "Pass", HUT: "Hütte", WATER: "Wasser",
  DECISION: "Fixpunkt", EMERGENCY_EXIT: "Notausstieg", USER_DEFINED: "Fixpunkt",
};

type Props = {
  waypoints: MapWaypoint[];
  /** [lat, lon]-Paare (Konvention dieser API, siehe RouteLegRead) */
  routeCoordinates?: [number, number][];
  /** Zusammen mit dangerSegments: faerbt die Route abschnittsweise ein (Gefahreneinschätzung,
   * siehe GET .../terrain-danger). Ohne eins von beiden bleibt die Route einfarbig
   * (routeCoordinates), wie bisher. */
  elevationProfile?: ElevationProfilePoint[];
  dangerSegments?: TerrainDangerSegment[];
  onMapClick?: (lat: number, lon: number) => void;
  onMarkerDragEnd?: (waypointId: string, lat: number, lon: number) => void;
  /** Hover-Synchronisation Höhenprofil -> Karte (Auftrag Abschnitt 6): temporaerer Marker,
   * unabhaengig von waypoints (loest kein fitBounds aus). */
  highlightPoint?: { lat: number; lon: number } | null;
  /** Startansicht an die Kartengrösse anpassen, mit der Schweiz im Zentrum. */
  fitSwitzerland?: boolean;
  className?: string;
};

export function HikingTourMap({ waypoints, routeCoordinates, elevationProfile, dangerSegments, onMapClick, onMarkerDragEnd, highlightPoint, fitSwitzerland = false, className }: Props) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selectedPoint = waypoints.find((waypoint) => waypoint.id === selectedId);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const fittedWaypointsRef = useRef(false);
  const markersRef = useRef<maplibregl.Marker[]>([]);
  const highlightMarkerRef = useRef<maplibregl.Marker | null>(null);
  const onMapClickRef = useRef(onMapClick);
  onMapClickRef.current = onMapClick;

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: SWISSTOPO_STYLE_URL,
      center: SWITZERLAND_CENTER,
      zoom: 7,
      ...(fitSwitzerland ? {
        bounds: [[5.95, 45.82], [10.5, 47.81]] as [[number, number], [number, number]],
        fitBoundsOptions: { padding: 24, duration: 0 },
      } : {}),
      attributionControl: { compact: true },
    });
    map.addControl(new maplibregl.NavigationControl(), "top-right");
    map.on("click", (event) => onMapClickRef.current?.(event.lngLat.lat, event.lngLat.lng));
    mapRef.current = map;
    fittedWaypointsRef.current = false;
    // Das Popup kann nach der Initialisierung seine endgültige Grösse erhalten.
    // Resize aktualisiert auch die Canvas-Fläche, nicht nur die CSS-Abmessungen.
    const observer = new ResizeObserver(() => map.resize());
    observer.observe(containerRef.current);
    return () => {
      observer.disconnect();
      highlightMarkerRef.current?.remove();
      highlightMarkerRef.current = null;
      map.remove();
      mapRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    markersRef.current.forEach((marker) => marker.remove());
    markersRef.current = waypoints.map((waypoint) => {
      const element = document.createElement("div");
      element.className = "wanderplaner-map-marker-anchor";
      const button = document.createElement("button");
      button.type = "button";
      button.className = "wanderplaner-map-marker";
      button.setAttribute("aria-label", waypoint.label || KIND_LABEL[waypoint.kind]);
      element.appendChild(button);
      let dragged = false;
      button.addEventListener("click", (event) => {
        event.stopPropagation();
        if (!dragged) setSelectedId(waypoint.id);
      });
      button.addEventListener("dblclick", (event) => event.stopPropagation());
      button.addEventListener("keydown", (event) => event.stopPropagation());
      element.style.setProperty("--wanderplaner-marker-color", `var(${KIND_COLOR_TOKEN[waypoint.kind] ?? "--accent"})`);
      if (waypoint.label) element.title = waypoint.label;
      const marker = new maplibregl.Marker({ element, draggable: Boolean(onMarkerDragEnd) })
        .setLngLat([waypoint.lon, waypoint.lat])
        .addTo(map);
      if (onMarkerDragEnd) {
        marker.on("dragstart", () => { dragged = true; });
        marker.on("dragend", () => {
          setTimeout(() => { dragged = false; }, 0);
          const pos = marker.getLngLat();
          onMarkerDragEnd(waypoint.id, pos.lat, pos.lng);
        });
      }
      return marker;
    });

    if (waypoints.length > 0 && !fittedWaypointsRef.current) {
      fittedWaypointsRef.current = true;
      const bounds = waypoints.reduce(
        (acc, wp) => acc.extend([wp.lon, wp.lat]),
        new maplibregl.LngLatBounds([waypoints[0].lon, waypoints[0].lat], [waypoints[0].lon, waypoints[0].lat])
      );
      map.fitBounds(bounds, { padding: 64, maxZoom: 15, duration: 300 });
    }

    return () => {
      markersRef.current.forEach((marker) => marker.remove());
    };
  }, [waypoints, onMarkerDragEnd]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    if (!highlightPoint) {
      highlightMarkerRef.current?.remove();
      highlightMarkerRef.current = null;
      return;
    }

    if (!highlightMarkerRef.current) {
      const element = document.createElement("div");
      element.className = "wanderplaner-map-marker-highlight";
      highlightMarkerRef.current = new maplibregl.Marker({ element })
        .setLngLat([highlightPoint.lon, highlightPoint.lat])
        .addTo(map);
    }
    highlightMarkerRef.current.setLngLat([highlightPoint.lon, highlightPoint.lat]);
  }, [highlightPoint]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    // Kein "|| #hex"-Fallback (design-ok: --accent-strong/--warning/--info sind in tokens.css
    // immer definiert, ein Fallback wuerde nur einen Tippfehler verdecken, siehe DESIGN.md
    // Abschnitt 3).
    const style = getComputedStyle(document.documentElement);
    const dangerColor: Record<TerrainDangerLevel, string> = {
      normal: style.getPropertyValue(DANGER_COLOR_TOKEN.normal).trim(),
      steep_exposed: style.getPropertyValue(DANGER_COLOR_TOKEN.steep_exposed).trim(),
      alpine: style.getPropertyValue(DANGER_COLOR_TOKEN.alpine).trim(),
    };

    // Gefahreneinschätzung (siehe DataToolbar-Beschreibung/GET .../terrain-danger): die Route
    // wird abschnittsweise eingefaerbt, sobald sowohl Hoehenprofil als auch Gefahrensegmente
    // vorliegen - sonst bleibt es bei der bisherigen einfarbigen Linie aus routeCoordinates.
    const dangerFeatures: GeoJSON.Feature<GeoJSON.LineString>[] = (elevationProfile && dangerSegments
      ? dangerSegments
      : []
    ).flatMap((segment) => {
      const segmentPoints = elevationProfile!.filter((point) => point.distance_m >= segment.from_m && point.distance_m <= segment.to_m);
      if (segmentPoints.length < 2) return [];
      return [{
        type: "Feature" as const,
        properties: { danger: segment.danger },
        geometry: { type: "LineString" as const, coordinates: segmentPoints.map((point) => [point.lon, point.lat]) },
      }];
    });
    const geojson: GeoJSON.FeatureCollection<GeoJSON.LineString> = {
      type: "FeatureCollection",
      features: dangerFeatures.length > 0 ? dangerFeatures : [{
        type: "Feature",
        properties: { danger: "normal" },
        geometry: { type: "LineString", coordinates: (routeCoordinates ?? []).map(([lat, lon]) => [lon, lat]) },
      }],
    };

    const applySource = () => {
      const source = map.getSource("wanderplaner-route") as maplibregl.GeoJSONSource | undefined;
      if (source) {
        source.setData(geojson);
        return;
      }
      map.addSource("wanderplaner-route", { type: "geojson", data: geojson });
      map.addLayer({
        id: "wanderplaner-route-line",
        type: "line",
        source: "wanderplaner-route",
        layout: { "line-join": "round", "line-cap": "round" },
        paint: {
          "line-color": [
            "match", ["get", "danger"],
            "alpine", dangerColor.alpine,
            "steep_exposed", dangerColor.steep_exposed,
            dangerColor.normal,
          ],
          "line-width": 4,
        },
      });
    };

    if (map.isStyleLoaded()) applySource();
    else map.once("load", applySource);
  }, [routeCoordinates, elevationProfile, dangerSegments]);

  return (
    <div className="wanderplaner-map-frame">
      <div ref={containerRef} className={`wanderplaner-map${className ? ` ${className}` : ""}`} role="application" aria-label="Karte" />
      {selectedPoint && (
        <aside className="wanderplaner-map-info" aria-label="Wegpunkt-Information" onKeyDown={(event) => {
          if (event.key === "Escape") setSelectedId(null);
        }}>
          <div className="wanderplaner-map-info-header">
            <strong>{selectedPoint.label || KIND_LABEL[selectedPoint.kind]}</strong>
            <button type="button" className="button-icon-soft" aria-label="Wegpunkt-Information schliessen" onClick={() => setSelectedId(null)}>✕</button>
          </div>
          <span className="field-help">{KIND_LABEL[selectedPoint.kind]}</span>
          {selectedPoint.elevation_m != null && <div>Höhe: {Math.round(selectedPoint.elevation_m)} m</div>}
          <div className="field-help">{selectedPoint.lat.toFixed(5)}, {selectedPoint.lon.toFixed(5)}</div>
          {selectedPoint.break_minutes != null && selectedPoint.break_minutes > 0 && <div>Pause: {selectedPoint.break_minutes} min</div>}
          {selectedPoint.description && <p>{selectedPoint.description}</p>}
        </aside>
      )}
    </div>
  );
}
