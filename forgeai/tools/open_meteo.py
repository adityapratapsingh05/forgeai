"""Keyless Open-Meteo weather tool with graceful offline handling."""

from __future__ import annotations

import json
import httpx


def open_meteo_tool(
    place: str = "",
    lat: float | None = None,
    lon: float | None = None,
) -> str:
    """Fetch current weather from Open-Meteo by coordinates or place name."""
    try:
        with httpx.Client(timeout=8.0) as client:
            resolved_name = place or "coordinates"
            if lat is None or lon is None:
                if not place.strip():
                    return json.dumps({"ok": False, "error": "Provide either place or lat/lon."})
                geo = client.get(
                    "https://geocoding-api.open-meteo.com/v1/search",
                    params={"name": place.strip(), "count": 1},
                )
                geo.raise_for_status()
                results = geo.json().get("results") or []
                if not results:
                    return json.dumps({"ok": False, "error": f"Location not found: {place}"})
                lat = float(results[0]["latitude"])
                lon = float(results[0]["longitude"])
                resolved_name = f"{results[0].get('name')}, {results[0].get('country', '')}".strip(", ")

            wx = client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={"latitude": lat, "longitude": lon, "current_weather": "true"},
            )
            wx.raise_for_status()
            data = wx.json()
            return json.dumps(
                {
                    "ok": True,
                    "location": resolved_name,
                    "latitude": lat,
                    "longitude": lon,
                    "current_weather": data.get("current_weather", {}),
                }
            )
    except Exception as exc:
        return json.dumps(
            {
                "ok": False,
                "error": f"open_meteo unavailable (offline or API error): {exc}",
            }
        )
