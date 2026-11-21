---
title: Sunrise Salon Receptionist
emoji: 💇
colorFrom: yellow
colorTo: red
sdk: docker
app_port: 7860
pinned: false
---


# Voice Receptionist

A browser-based AI voice receptionist for Sunrise Salon, built with LiveKit Agents, Groq, Kokoro TTS, FastAPI, and PostgreSQL.

Callers open the web page, click **Call**, and can ask about services and business hours, check stylist availability, and book, reschedule, or cancel appointments.

## Features

- Real-time browser voice calls with LiveKit
- Open-source Kokoro text-to-speech
- Groq speech-to-text and language model APIs
- PostgreSQL-backed business information and appointments
- Service, stylist, FAQ, availability, and booking tools
- Double-booking prevention at the database level
- Docker Compose deployment

## Architecture

```text
Browser (WebRTC)
    |
    v
LiveKit Cloud
    |
    v
LiveKit Agents Worker (Python)
    |-- Speech-to-text: Whisper Large v3 Turbo (Groq)
    |-- Language model: openai/gpt-oss-120b (Groq)
    |-- Text-to-speech: Kokoro
    +-- Database: PostgreSQL
```

## Services

| Service | Purpose |
| --- | --- |
| LiveKit | Real-time WebRTC voice connection |
| Groq | Whisper transcription and language-model responses |
| Kokoro | Self-hosted text-to-speech |
| FastAPI | LiveKit access tokens and static web application |
| PostgreSQL | Businesses, stylists, services, FAQs, and bookings |

## Prerequisites

- Docker and Docker Compose
- A LiveKit project and API credentials
- A Groq API key
- A PostgreSQL-compatible environment if running outside Docker

## Quick Start

1. Copy the example environment file:

   ```bash
   cp .env.example .env
   ```

2. Configure the following values in `.env`:

   ```dotenv
   GROQ_API_KEY=your_groq_api_key
   LIVEKIT_URL=wss://your-livekit-project.livekit.cloud
   LIVEKIT_API_KEY=your_livekit_api_key
   LIVEKIT_API_SECRET=your_livekit_api_secret
   ```

3. Start the project:

   ```bash
   docker compose up -d --build
   ```

4. Open `http://localhost:8000`, allow microphone access, and click **Call**.

5. Stop the project when finished:

   ```bash
   docker compose down
   ```

## Running Tests

Run the test suite from the project root:

```bash
python -m pytest tests -v
```

The tests verify booking behavior, including prevention of conflicting confirmed bookings.

## Double-Booking Prevention

The database uses a partial unique index on confirmed stylist appointments:

```sql
CREATE UNIQUE INDEX one_booking_per_slot
ON bookings (stylist_id, start_at)
WHERE status = 'confirmed';
```

This makes simultaneous bookings for the same stylist and start time impossible.

## Database Files

- `db/schema.sql` - Database tables and constraints
- `db/seed.sql` - Initial salon data

## Project Structure

```text
agent/
  agent.py       LiveKit agent, tools, and AI instructions
  booking.py     Booking validation and database operations
api/
  main.py        FastAPI application and token endpoint
  static/        Browser voice interface
db/
  schema.sql     PostgreSQL schema
  seed.sql       Example salon data
tests/
  test_double_booking.py
docker-compose.yml
Dockerfile
requirements.txt
```

## Rate Limits and Limitations

- Groq free-tier accounts may have requests-per-minute and tokens-per-minute limits.
- HTTP `429` responses can occur during rapid or concurrent calls.
- CPU-hosted Kokoro avoids GPU hosting costs but may have higher text-to-speech latency.
- End-of-utterance, language-model, and text-to-speech latency depend on network and provider response times.

## License

This project is available under the terms specified by the repository owner.
