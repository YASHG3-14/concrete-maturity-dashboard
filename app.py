import os
from datetime import datetime, timezone
from typing import Any

import requests
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

THINGSPEAK_CHANNEL_ID = os.getenv("THINGSPEAK_CHANNEL_ID", "")
THINGSPEAK_API_KEY = os.getenv("THINGSPEAK_API_KEY", "")
THINGSPEAK_FIELD = os.getenv("THINGSPEAK_FIELD", "1")
THINGSPEAK_RESULTS = int(os.getenv("THINGSPEAK_RESULTS", "500"))
DEFAULT_DATUM_C = float(os.getenv("DATUM_TEMPERATURE_C", "0"))
DEFAULT_REFRESH_SECONDS = int(os.getenv("REFRESH_INTERVAL_SECONDS", "30"))
REQUEST_TIMEOUT_SECONDS = float(os.getenv("THINGSPEAK_TIMEOUT_SECONDS", "10"))


def parse_timestamp(value: str) -> datetime | None:
    """Parse ThingSpeak ISO-8601 timestamps and normalize to UTC."""
    if not value:
        return None
    try:
        # ThingSpeak commonly returns e.g. 2026-10-02T10:20:30Z.
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def fetch_thingspeak() -> list[dict[str, Any]]:
    if not THINGSPEAK_CHANNEL_ID:
        raise RuntimeError("THINGSPEAK_CHANNEL_ID is not configured.")
    if not THINGSPEAK_API_KEY:
        raise RuntimeError("THINGSPEAK_API_KEY is not configured.")

    url = f"https://api.thingspeak.com/channels/{THINGSPEAK_CHANNEL_ID}/feeds.json"
    params = {
        "api_key": THINGSPEAK_API_KEY,
        "results": max(1, min(THINGSPEAK_RESULTS, 8000)),
    }

    response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    payload = response.json()

    feeds = payload.get("feeds", [])
    readings = []

    for feed in feeds:
        timestamp = parse_timestamp(feed.get("created_at", ""))
        raw_temp = feed.get(f"field{THINGSPEAK_FIELD}")

        if timestamp is None or raw_temp in (None, ""):
            # Missing timestamp/temperature: ignore this sample rather than
            # fabricating a value or time interval.
            continue

        try:
            temperature = float(raw_temp)
        except (TypeError, ValueError):
            continue

        readings.append(
            {
                "timestamp": timestamp,
                "temperature": temperature,
                "entry_id": feed.get("entry_id"),
            }
        )

    # ThingSpeak normally returns chronological feeds, but sort defensively.
    readings.sort(key=lambda x: x["timestamp"])

    # Remove duplicate timestamps so a zero-duration sample does not affect
    # the maturity calculation.
    deduped = []
    seen = set()
    for reading in readings:
        key = reading["timestamp"]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(reading)

    return deduped


def calculate_maturity(readings: list[dict[str, Any]], datum_c: float) -> tuple[list[dict[str, Any]], float]:
    """
    Nurse-Saul maturity using actual elapsed time between valid readings.

    For each interval [t(i-1), t(i)], the previous measured temperature is
    treated as representative of that interval:

        M += (T(i-1) - T0) * delta_t_hours

    This is the direct rectangular form of the requested Nurse-Saul equation.
    """
    maturity = 0.0
    history = []

    if not readings:
        return history, maturity

    first = readings[0]
    history.append(
        {
            "timestamp": first["timestamp"].isoformat(),
            "temperature": first["temperature"],
            "maturity": 0.0,
        }
    )

    previous = first

    for current in readings[1:]:
        delta_seconds = (current["timestamp"] - previous["timestamp"]).total_seconds()

        # Ignore out-of-order/duplicate timestamps after defensive sorting.
        if delta_seconds <= 0:
            continue

        delta_hours = delta_seconds / 3600.0
        maturity += (previous["temperature"] - datum_c) * delta_hours

        history.append(
            {
                "timestamp": current["timestamp"].isoformat(),
                "temperature": current["temperature"],
                "maturity": maturity,
            }
        )
        previous = current

    return history, maturity


@app.get("/")
def dashboard():
    return render_template(
        "index.html",
        default_datum=DEFAULT_DATUM_C,
        default_refresh=DEFAULT_REFRESH_SECONDS,
        channel_id=THINGSPEAK_CHANNEL_ID,
        field=THINGSPEAK_FIELD,
    )


@app.get("/api/data")
def api_data():
    try:
        datum_c = float(request.args.get("datum", DEFAULT_DATUM_C))
        if not -1000 < datum_c < 1000:
            raise ValueError
    except ValueError:
        return jsonify({"error": "Datum temperature must be a valid value in °C."}), 400

    try:
        readings = fetch_thingspeak()
        history, maturity = calculate_maturity(readings, datum_c)

        latest = history[-1] if history else None

        return jsonify(
            {
                "ok": True,
                "datum_temperature_c": datum_c,
                "maturity_index_c_hours": maturity,
                "latest_temperature_c": latest["temperature"] if latest else None,
                "last_update_utc": latest["timestamp"] if latest else None,
                "sample_count": len(history),
                "history": history,
            }
        )
    except requests.RequestException as exc:
        app.logger.exception("ThingSpeak request failed")
        return jsonify(
            {"error": f"ThingSpeak API request failed: {exc.__class__.__name__}"}
        ), 502
    except (ValueError, RuntimeError) as exc:
        return jsonify({"error": str(exc)}), 500
    except Exception:
        app.logger.exception("Unexpected server error")
        return jsonify({"error": "Unexpected server error."}), 500


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
