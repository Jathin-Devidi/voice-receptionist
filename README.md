# Voice Receptionist

A browser-based voice receptionist for appointment-based businesses. The demo is configured for **Sunrise Salon** in Indiranagar, Bengaluru. Callers can ask about services and business information, check availability, book appointments, and reschedule or cancel existing bookings.

The call page connects to a LiveKit room from the browser. A Python LiveKit Agents worker handles the conversation, uses database-backed business information, and applies booking rules in PostgreSQL.

> **Demo status:** this repository contains the application and local Docker Compose setup. It does not configure a public demo URL or publish benchmark results; run the project locally using the instructions below.

## Features

- Browser-based, real-time voice calls with microphone permission and a responsive call page.
- Speech recognition using Whisper Large v3 Turbo through Groq.
- Conversational responses using Groq-hosted open-weight `gpt-oss` models, with a smaller-model fallback.
- Self-hosted Kokoro text-to-speech over an OpenAI-compatible API.
- Database-driven business details: services, prices, stylists, working hours, FAQs, address, and policies.
- Appointment availability, booking, rescheduling, and cancellation tools.
- PostgreSQL-enforced protection against two confirmed bookings for the same stylist and start time.
- Command-line tools for updating business information without changing application code.
- Docker Compose services for the API, agent, PostgreSQL, and Kokoro.

## Architecture

```text
Browser (LiveKit WebRTC client)
   |  GET /token (FastAPI)
   v
LiveKit Cloud (audio transport)
   v
LiveKit Agents worker (Python)
   |-- Silero VAD (local voice activity and turn detection)
   |-- Whisper Large v3 Turbo via Groq (speech to text)
   |-- gpt-oss-120b via Groq (LLM; gpt-oss-20b fallback)
   |-- Kokoro-82M via Kokoro-FastAPI (text to speech)
   '-- PostgreSQL via asyncpg (business data and bookings)
```

| Component | Role | Execution / hosting |
|---|---|---|
| FastAPI | Serves the call page, health check, and short-lived LiveKit room tokens | `api` container |
| LiveKit Agents | Runs the receptionist and its booking tools | `agent` container |
| Silero VAD | Detects speech, silence, and interruptions | Locally in the agent process |
| Whisper Large v3 Turbo | Transcribes caller audio | Groq API |
| `openai/gpt-oss-120b` | Generates receptionist responses and calls tools | Groq API |
| `openai/gpt-oss-20b` | Fallback LLM for primary model timeouts or rate limits | Groq API |
| Kokoro-82M | Converts agent responses to speech | `kokoro` container; CPU image |
| PostgreSQL 16 | Stores business configuration, schedules, FAQs, bookings, and staff tickets | `db` container |
| LiveKit | WebRTC room and audio transport | LiveKit Cloud project |

Groq hosts the speech-recognition and LLM APIs; LiveKit Cloud carries call audio. The project does not use a closed speech or LLM platform. Turn detection and interruption handling default to local Silero VAD (`TURN_DETECTION=vad` and `INTERRUPTION_MODE=vad`), rather than LiveKit's hosted turn/interruption models.

## Requirements

- Docker Desktop or Docker Engine with Docker Compose.
- A [Groq API key](https://console.groq.com/keys).
- A LiveKit Cloud project with its WebSocket URL, API key, and API secret.
- A working microphone and a browser that supports WebRTC. Headphones are recommended to reduce echo.

Groq and LiveKit quotas and free-tier terms can change; consult their dashboards for current limits.

## Run with Docker Compose

1. Copy the example environment file and set the Groq and LiveKit credentials:

   ```bash
   cp .env.example .env
   ```

   On Windows PowerShell:

   ```powershell
   Copy-Item .env.example .env
   ```

   Set `GROQ_API_KEY`, `LIVEKIT_URL`, `LIVEKIT_API_KEY`, and `LIVEKIT_API_SECRET` in `.env`. Do not commit `.env`.

2. Build and start all services:

   ```bash
   docker compose up -d --build
   ```

   The first build downloads Python dependencies and the Kokoro CPU image; it may take several minutes.

3. Open [http://localhost:8000](http://localhost:8000), allow microphone access, and select **Call**.

4. View service logs or stop the application:

   ```bash
   docker compose logs -f agent
   docker compose logs -f api
   docker compose down
   ```

   To also remove the PostgreSQL data volume, use `docker compose down -v`. This permanently deletes the local database contents.

The API health endpoint is [http://localhost:8000/healthz](http://localhost:8000/healthz). PostgreSQL is published on host port `5433`; Kokoro is published on port `8880`.

### Environment variables

`.env.example` documents the variables and their defaults. The main settings are:

| Variable | Purpose |
|---|---|
| `GROQ_API_KEY` | Groq API credential used for transcription and LLM requests |
| `LIVEKIT_URL` | LiveKit project WebSocket URL |
| `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` | Credentials used by the API to issue room tokens |
| `BUSINESS_NAME` | Business row to serve; defaults to `Sunrise Salon` |
| `LLM_MODEL`, `LLM_FALLBACK_MODEL` | Primary and fallback Groq model names |
| `STT_MODEL` | Groq transcription model name |
| `TTS_VOICE` | Kokoro voice, default `af_heart` |
| `TURN_DETECTION`, `INTERRUPTION_MODE` | Turn and interruption strategy; default `vad` |
| `VAD_MIN_SILENCE`, `ENDPOINT_MIN_DELAY` | Speech endpoint timing in seconds |
| `PREEMPTIVE_TTS` | Whether speech synthesis may start before turn confirmation |
| `LLM_ATTEMPT_TIMEOUT` | Seconds before trying the fallback LLM |
| `INFO_REFRESH_SECONDS` | How often the agent refreshes business facts during a call |
| `USER_AWAY_SECONDS` | Silence duration before the agent asks whether the caller is still there |

Docker Compose supplies container-specific `DATABASE_URL` and `KOKORO_URL` values to the agent. The example values are for running the agent and API directly on the host.

## Development without Docker

Python 3.12 is recommended. Run PostgreSQL and Kokoro in containers, then run the API and worker in separate terminals:

```bash
python -m venv .venv
# macOS/Linux:
source .venv/bin/activate
# Windows PowerShell:
# .venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
docker compose up -d db kokoro
python -m agent.agent dev
```

In another terminal, with the virtual environment active:

```bash
uvicorn api.main:app --port 8000
```

The default host development database URL in `.env.example` connects to `localhost:5433`. `docker compose up -d db kokoro` initializes a new PostgreSQL volume using `db/schema.sql` and `db/seed.sql`.

## Business data and database

The application separates business configuration from application logic. `BUSINESS_NAME` selects which business record the worker serves. The seeded example is Sunrise Salon, with a Bengaluru address, `Asia/Kolkata` timezone, three stylists, service prices, weekday schedules, and FAQs.

The schema includes:

- `businesses`, `stylists`, `services`, `working_hours`, and `faqs` for business configuration.
- `bookings` for appointment records and status.
- `tickets` for questions that need staff follow-up.
- `calls` for future call metadata; call transcripts are not currently persisted by the agent.

Fresh databases are initialized from [`db/schema.sql`](db/schema.sql) and [`db/seed.sql`](db/seed.sql). PostgreSQL's Docker initialization scripts run only when the data volume is empty. If you have an older database created before the `services.active` column was introduced, apply [`db/migrations/001_services_active.sql`](db/migrations/001_services_active.sql) once.

## Booking behavior and safeguards

- Availability uses each stylist's weekday schedule, configured slot length, confirmed bookings, the business timezone, and the current time.
- A slot must be in the future, within the stylist's working hours, and aligned to the configured slot boundary.
- The database has a partial unique index on `(stylist_id, start_at)` for confirmed bookings. Concurrent attempts for the same slot cannot both succeed.
- Rescheduling is a single database update protected by the same uniqueness constraint; a failed move leaves the existing booking unchanged.
- Reschedule and cancellation requests require both the booking code and the booking phone number. A mismatch returns the same generic response and does not reveal booking details.
- The cancellation notice window is enforced by application code. A cancellation inside the configured window requires caller confirmation.
- Availability responses contain free times only. The agent should not disclose another customer's appointment or details.
- The model is instructed to answer business questions from database-backed facts and offer staff follow-up when information is unavailable; booking rules are enforced in code and by PostgreSQL.

## Update business information

Use the admin CLI from the project directory with the virtual environment active. In Docker, commands can instead run in the agent image:

```bash
python -m tools.admin show
python -m tools.admin set-price "Hair spa" 1300
python -m tools.admin set-price "Hair colour" 2800 --note "From Rs 2,800, depends on hair length"
python -m tools.admin add-service "Bridal trial" --stylist "Anita Rao" --price 3000
python -m tools.admin remove-service "Bridal trial"
python -m tools.admin set-hours "Anita Rao" mon-sat 10:00 15:00
python -m tools.admin day-off "Anita Rao" sat
python -m tools.admin set-faq parking "Free parking behind the salon."
python -m tools.admin remove-faq parking
python -m tools.admin set-address "New address here"
python -m tools.admin add-stylist "Meera Pillai"
python -m tools.admin not-offered add "threading"
python -m tools.admin not-offered remove "threading"
python -m tools.admin bookings
python -m tools.admin tickets
```

Run `python -m tools.admin --help` for command syntax. The agent refreshes business facts every five seconds by default, so data edits can take effect during a call without rebuilding the image. Existing confirmed bookings are retained if a service is retired. The CLI warns when a schedule change leaves upcoming bookings outside a stylist's hours.

## Tests

The integration tests require PostgreSQL with the seeded schema. Start the database and install development dependencies:

```bash
docker compose up -d db
pip install -r requirements-dev.txt
python -m pytest tests -v
```

The suite covers concurrent attempts to book one slot, working days and hours, past and off-boundary times, service lookup, booking/rescheduling/cancellation, the cancellation notice window, privacy for invalid booking credentials, and live business-data edits through the admin CLI.

For manual voice scenarios, see [`docs/test_questions.md`](docs/test_questions.md). The business handover document is [`docs/Sunrise_Salon_Handover.pdf`](docs/Sunrise_Salon_Handover.pdf).

## Latency measurement

The agent appends one `timestamp,latency_ms` row per measured turn to `logs/latency.csv`. Latency is measured from the agent's detection that the caller has stopped speaking until the agent begins speaking. It includes turn-end waiting, any tool work, LLM time, and time to first TTS audio.

After making calls, run:

```bash
python latency_report.py
```

The report prints the median, p95, min/max, and the number of turns at or below 2,500 ms. At least 20 turns are recommended for the report. This README does not publish benchmark results; collect fresh turns with the deployment you want to measure.

Latency-related defaults are configurable in `.env.example`: local VAD and short silence timing, preemptive generation/TTS, Kokoro raw PCM at its native 24 kHz sample rate, short sentence streaming, a fixed greeting that avoids an initial LLM call, a warm-up request, parallel database connection and room join, and a three-second primary LLM attempt before fallback.

## Privacy, deployment, and limitations

- Do not commit `.env` or put API credentials in source control. `.env` is ignored by Git.
- The API's `/token` endpoint issues a token to any client that can reach it. A public deployment should put appropriate access controls and usage safeguards in front of the endpoint.
- Booking names and phone numbers are stored in PostgreSQL. Phone numbers are normalized for booking verification; this project does not currently implement a data-retention or deletion workflow.
- Call transcripts are not stored by the agent. The `calls` table exists but is not currently used for transcript persistence.
- Groq and LiveKit usage is subject to provider quotas and service availability. Kokoro runs on CPU in the supplied Compose configuration and may be slow on small machines.
- The demo is English-only. It does not include a business dashboard, email confirmations, a phone-number gateway, knowledge-base uploads, or Hindi/Kannada support.
- Browser speakers can cause echo; headphones are recommended. VAD-based turn detection favors lower latency and may treat a long pause mid-sentence as the end of a turn.
- The LLM can misunderstand a request; database constraints and application validation remain the authority for bookings.
- Production hosting, public availability, load capacity, and measured latency are not claimed by this repository.

## Project layout

```text
agent/
  agent.py                 LiveKit worker, voice pipeline, and tool registration
  booking.py               Database access, availability, and booking rules
  prompt.py                Generic receptionist prompt
api/
  main.py                  FastAPI call page and LiveKit token endpoints
  static/index.html        Browser call interface
db/
  schema.sql               PostgreSQL tables and booking constraint
  seed.sql                 Sunrise Salon sample data
  migrations/              Incremental SQL migrations
tools/
  admin.py                 Business-information administration CLI
tests/                     Booking, concurrency, and live-edit integration tests
docs/                      Manual test checklist and salon handover document
Dockerfile                 Python application image
docker-compose.yml         API, agent, database, and Kokoro services
.env.example               Environment-variable template
latency_report.py          Summary report for locally collected latency data
```
