# Concrete Maturity Dashboard — Nurse–Saul

A Flask server-side web application that reads concrete temperature data from ThingSpeak and calculates the Nurse–Saul maturity index.

## 1. What this application does

- Fetches ThingSpeak feed data through the ThingSpeak REST API.
- Keeps the ThingSpeak channel ID and API key in environment variables.
- Uses the Nurse–Saul equation:

  `M = Σ (T − T₀) × Δt`

- Lets the user configure the datum temperature `T₀` from the dashboard.
- Uses each reading's actual timestamp, so irregular sampling intervals are handled correctly.
- Ignores readings with missing/invalid timestamps or temperature values.
- Sorts readings chronologically and removes duplicate timestamps.
- Shows:
  - latest temperature
  - cumulative maturity index
  - last reading time
  - valid sample count
  - temperature history chart
  - maturity history chart
- Automatically refreshes at a configurable interval.
- Provides a manual refresh button.
- Includes a `/health` endpoint for Render health checks.

## 2. Units and calculation convention

Temperature is in **°C**.

Time intervals are calculated from ThingSpeak timestamps and converted to **hours**.

Therefore:

`(°C − °C) × hours = °C·hours`

The maturity index displayed by the dashboard is therefore **°C·hours**.

For each interval from reading `i-1` to reading `i`, this implementation uses the previous measured temperature as the representative temperature:

`M_i = M_(i-1) + (T_(i-1) − T₀) × Δt_hours`

This is the direct rectangular interpretation of the Nurse–Saul summation requested in the specification. If your experimental protocol requires trapezoidal integration instead, change `calculate_maturity()` in `app.py` to use the average of the two endpoint temperatures.

### Temperatures below the datum

The formula is signed. If `T < T₀`, that interval contributes negative maturity. This is intentional and follows the equation as written.

### Missing readings

A feed with a missing/invalid temperature or timestamp is skipped. The next valid reading is then paired with the previous valid reading, and the actual elapsed time between their timestamps is used. The server never assumes that every reading is exactly 30 seconds apart.

## 3. ThingSpeak setup

Create/configure a ThingSpeak channel with a temperature field.

For example:

- Field 1: `Concrete Temperature`
- Units: `°C`

Create or obtain a **read API key** for the channel.

Do not put the API key in frontend JavaScript or commit it to Git.

## 4. Local setup

### Requirements

Python 3.10+ is recommended.

Create a virtual environment:

```bash
python -m venv .venv
```

Activate it on macOS/Linux:

```bash
source .venv/bin/activate
```

On Windows:

```powershell
.venv\Scripts\activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and edit it:

```text
THINGSPEAK_CHANNEL_ID=123456
THINGSPEAK_API_KEY=YOUR_READ_API_KEY
THINGSPEAK_FIELD=1
DATUM_TEMPERATURE_C=0
THINGSPEAK_RESULTS=500
REFRESH_INTERVAL_SECONDS=30
```

Run:

```bash
python app.py
```

Open:

`http://localhost:5000`

The `.env` file is ignored by Git.

## 5. Render deployment

This repository contains `render.yaml`.

### Option A — Blueprint deployment

Push the project to GitHub/GitLab and create a Render Blueprint from the repository.

Render will use:

- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn app:app`
- Health check: `/health`

Set the secret values in Render's environment settings:

- `THINGSPEAK_CHANNEL_ID`
- `THINGSPEAK_API_KEY`

You can keep these non-secret configuration values:

- `THINGSPEAK_FIELD=1`
- `THINGSPEAK_RESULTS=500`
- `THINGSPEAK_TIMEOUT_SECONDS=10`
- `DATUM_TEMPERATURE_C=0`
- `REFRESH_INTERVAL_SECONDS=30`

### Option B — Manual Render Web Service

Create a new Web Service and use:

```text
Build Command:
pip install -r requirements.txt

Start Command:
gunicorn app:app
```

Then add the environment variables listed above.

Do not hard-code the ThingSpeak API key in the source code.

## 6. Important architecture note

The browser does **not** call ThingSpeak directly.

Instead:

```text
ESP32 / sensors
      |
      v
ThingSpeak
      |
      | HTTPS + API key
      v
Flask server on Render
      |
      | JSON
      v
Responsive dashboard
      |
      +--> Temperature chart
      +--> Maturity chart
      +--> Latest temperature
      +--> Maturity index
```

This keeps the ThingSpeak read API key on the server.

## 7. API endpoint

The dashboard uses:

```text
GET /api/data?datum=0
```

Example response shape:

```json
{
  "ok": true,
  "datum_temperature_c": 0,
  "maturity_index_c_hours": 123.45,
  "latest_temperature_c": 28.4,
  "last_update_utc": "2026-10-02T14:30:00+00:00",
  "sample_count": 100,
  "history": [
    {
      "timestamp": "2026-10-02T12:00:00+00:00",
      "temperature": 27.1,
      "maturity": 0
    }
  ]
}
```

## 8. Changing the ThingSpeak field

If your ESP32 sends concrete temperature to Field 2 instead of Field 1:

```text
THINGSPEAK_FIELD=2
```

No application-code change is required.

## 9. Production considerations

For a larger concrete-monitoring system, the next useful upgrades would be:

1. Store processed readings/maturity in PostgreSQL instead of recalculating the whole ThingSpeak result set on every request.
2. Support multiple temperature sensors and multiple concrete batches.
3. Add concrete mix/batch IDs.
4. Add maturity-to-strength calibration so maturity can be converted to estimated compressive strength.
5. Add authentication if the dashboard is not intended to be public.
6. Add alert thresholds for temperature and estimated strength.
