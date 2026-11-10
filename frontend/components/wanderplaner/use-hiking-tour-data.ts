"use client";

import { useEffect, useState } from "react";

import { browserApiFetch } from "@/lib/api/client";
import { ElevationProfile, HikingTour, MarchTimeTable, TerrainDanger } from "@/types/api";

/** Abgeleitete Tourdaten (Höhenprofil, Gefahreneinschätzung, Marschtabelle), gemeinsam für
 * Desktop- (hiking-tour-detail.tsx) und Mobile-Ansicht (hiking-tour-mobile.tsx). Ein Fehler beim
 * Laden lässt den jeweiligen Teil leer - die Seite bleibt bedienbar. */
export function useHikingTourData(tour: HikingTour, marchTableRevision = 0) {
  const [elevationProfile, setElevationProfile] = useState<ElevationProfile | null>(null);
  const [terrainDanger, setTerrainDanger] = useState<TerrainDanger | null>(null);
  const [marchTable, setMarchTable] = useState<MarchTimeTable | null>(null);

  useEffect(() => {
    if (tour.route_legs.length === 0) {
      setMarchTable(null);
      return;
    }
    let cancelled = false;
    browserApiFetch<MarchTimeTable>(`/api/hiking-tours/${tour.id}/march-table`)
      .then((table) => {
        if (!cancelled) setMarchTable(table);
      })
      .catch(() => {
        if (!cancelled) setMarchTable(null);
      });
    return () => {
      cancelled = true;
    };
  }, [tour.id, tour.route_computed_at, tour.route_legs.length, marchTableRevision]);

  useEffect(() => {
    if (!tour.elevation_profile_fetched_at) {
      setElevationProfile(null);
      return;
    }
    let cancelled = false;
    browserApiFetch<ElevationProfile>(`/api/hiking-tours/${tour.id}/elevation-profile`)
      .then((profile) => {
        if (!cancelled) setElevationProfile(profile);
      })
      .catch(() => {
        if (!cancelled) setElevationProfile(null);
      });
    return () => {
      cancelled = true;
    };
  }, [tour.id, tour.elevation_profile_fetched_at]);

  useEffect(() => {
    if (!tour.terrain_danger_computed_at) {
      setTerrainDanger(null);
      return;
    }
    let cancelled = false;
    browserApiFetch<TerrainDanger>(`/api/hiking-tours/${tour.id}/terrain-danger`)
      .then((danger) => {
        if (!cancelled) setTerrainDanger(danger);
      })
      .catch(() => {
        if (!cancelled) setTerrainDanger(null);
      });
    return () => {
      cancelled = true;
    };
  }, [tour.id, tour.terrain_danger_computed_at]);

  return { elevationProfile, terrainDanger, marchTable };
}
