"""LiveKit voice agent. Business facts come from the database via agent.booking."""
import asyncio
import json
import logging
import os
import time

import httpx
from dotenv import load_dotenv
from livekit.agents import (Agent, AgentSession, JobContext, JobProcess, RunContext,
                            WorkerOptions, cli, function_tool, llm, tokenize)
from livekit.agents import tts as lk_tts
from livekit.plugins import openai, silero

from agent.booking import Booker
from agent.prompt import PROMPT

load_dotenv()

GROQ_URL = "https://api.groq.com/openai/v1"
LLM_MODEL = os.getenv("LLM_MODEL", "openai/gpt-oss-120b")
LLM_FALLBACK_MODEL = os.getenv("LLM_FALLBACK_MODEL", "openai/gpt-oss-20b")   # used on rate limits / timeouts
LLM_REASONING_EFFORT = os.getenv("LLM_REASONING_EFFORT", "low")             # "" to omit
STT_MODEL = os.getenv("STT_MODEL", "whisper-large-v3-turbo")
# "vad" = interruptions decided locally by Silero VAD. "adaptive" = LiveKit Cloud's hosted model.
INTERRUPTION_MODE = os.getenv("INTERRUPTION_MODE", "vad")
# "vad" = end of turn decided locally from silence (fast, no cloud call). "model" = LiveKit's turn-detector model,
# which LiveKit Cloud serves by default (smarter about mid-sentence pauses, but an extra network hop per turn).
TURN_DETECTION = os.getenv("TURN_DETECTION", "vad")
LOG_DIR = os.getenv("LOG_DIR", "logs")
AWAY_SECONDS = float(os.getenv("USER_AWAY_SECONDS", "8"))

# ---- latency tuning (all overridable from .env) ----
KOKORO_URL = os.getenv("KOKORO_URL", "http://localhost:8880/v1")
TTS_VOICE = os.getenv("TTS_VOICE", "af_heart")                      # e.g. am_michael for a male voice
VAD_MIN_SILENCE = float(os.getenv("VAD_MIN_SILENCE", "0.3"))        # Silero default is 0.55 s of silence before "stopped"
ENDPOINT_MIN_DELAY = float(os.getenv("ENDPOINT_MIN_DELAY", "0.3"))
PREEMPTIVE_TTS = os.getenv("PREEMPTIVE_TTS", "1") == "1"            # start speaking before the turn is fully confirmed
LLM_ATTEMPT_TIMEOUT = float(os.getenv("LLM_ATTEMPT_TIMEOUT", "3"))  # then fall back to the smaller model
INFO_REFRESH_SECONDS = float(os.getenv("INFO_REFRESH_SECONDS", "5"))  # pick up admin edits made during a call

log = logging.getLogger("receptionist")


def build_instructions(booker: Booker, info: dict) -> str:
    """System prompt with the current business facts (from the database) and current time filled in."""
    return PROMPT.format(name=booker.biz["name"], now=booker.now_text(),
                         info=json.dumps(info, ensure_ascii=False, separators=(",", ":")))


class Receptionist(Agent):
    """Business facts are injected into the prompt (see build_instructions) instead of being fetched by a tool.
    A tool call costs a whole extra LLM round trip per question, which was the biggest source of delay."""

    def __init__(self, booker: Booker, instructions: str):
        super().__init__(instructions=instructions)
        self.b = booker

    @function_tool
    async def check_availability(self, context: RunContext, service: str, date: str):
        """Free slots for a service on a date (YYYY-MM-DD). Also suggests the next available days."""
        return await self.b.check_availability(service, date)

    @function_tool
    async def book_appointment(self, context: RunContext, service: str, start_iso: str,
                               name: str, phone: str):
        """Book a slot. start_iso like 2026-11-24T10:30:00 in the business timezone."""
        return await self.b.book_appointment(service, start_iso, name, phone)

    @function_tool
    async def reschedule_appointment(self, context: RunContext, code: str, phone: str,
                                     new_start_iso: str):
        """Move an existing booking. Needs the booking code and the phone number used to book."""
        return await self.b.reschedule_appointment(code, phone, new_start_iso)

    @function_tool
    async def cancel_appointment(self, context: RunContext, code: str, phone: str,
                                 confirm: bool = False):
        """Cancel a booking. If the result says needs_confirmation, ask the caller, then call again with confirm=true."""
        return await self.b.cancel_appointment(code, phone, confirm)

    @function_tool
    async def handoff_to_staff(self, context: RunContext, question: str, phone: str = ""):
        """Save a question the agent cannot answer so staff can follow up."""
        return await self.b.handoff_to_staff(question, phone)


def build_llm():
    """Primary model, with an automatic fallback to a smaller one if Groq rate-limits or times out."""
    kwargs = {"reasoning_effort": LLM_REASONING_EFFORT} if LLM_REASONING_EFFORT else {}
    names = list(dict.fromkeys(m for m in (LLM_MODEL, LLM_FALLBACK_MODEL) if m))
    models = [openai.LLM(base_url=GROQ_URL, api_key=os.environ["GROQ_API_KEY"], model=m, **kwargs)
              for m in names]
    return models[0] if len(models) == 1 else llm.FallbackAdapter(models, attempt_timeout=LLM_ATTEMPT_TIMEOUT)


def turn_handling() -> dict:
    cfg = {
        "endpointing": {"min_delay": ENDPOINT_MIN_DELAY, "max_delay": 1.5},   # cap the wait on unsure turn ends
        "interruption": {"enabled": True, "mode": INTERRUPTION_MODE},
        "preemptive_generation": {"enabled": True, "preemptive_tts": PREEMPTIVE_TTS},
    }
    if TURN_DETECTION == "vad":
        cfg["turn_detection"] = "vad"
    return cfg


def build_tts():
    """Kokoro over its OpenAI-compatible API.
    - response_format="pcm": raw 24 kHz audio, no MP3 encode/decode step (Kokoro's native rate, so no resampling).
    - StreamAdapter with a small min_sentence_len: the first short sentence goes to TTS straight away instead of
      waiting to be merged with the next one."""
    base = openai.TTS(base_url=KOKORO_URL, api_key="not-needed", model="kokoro", voice=TTS_VOICE,
                      response_format="pcm", sample_rate=24000)
    return lk_tts.StreamAdapter(
        tts=base,
        sentence_tokenizer=tokenize.blingfire.SentenceTokenizer(min_sentence_len=8, retain_format=True))


def warm_up_tts():
    """First request to Kokoro after start-up is slow (lazy init). Pay that cost here, not on the caller's first words."""
    try:
        httpx.post(f"{KOKORO_URL}/audio/speech", timeout=30,
                   json={"model": "kokoro", "voice": TTS_VOICE, "input": "Hello.", "response_format": "pcm"})
    except Exception as e:  # not fatal: the first call will just be a bit slower
        log.warning("Kokoro warm-up skipped: %s", e)


def prewarm(proc: JobProcess):
    # Load the VAD model once per process so the first call is not delayed.
    # min_silence_duration is how long the caller must be quiet before VAD says "stopped"; it is a direct
    # part of every reply's latency, and the default (0.55 s) is more than a phone-style conversation needs.
    proc.userdata["vad"] = silero.VAD.load(min_silence_duration=VAD_MIN_SILENCE)
    warm_up_tts()


async def entrypoint(ctx: JobContext):
    booker, _ = await asyncio.gather(Booker.create(), ctx.connect())   # DB pool and room join in parallel

    session = AgentSession(
        vad=ctx.proc.userdata["vad"],
        stt=openai.STT(base_url=GROQ_URL, api_key=os.environ["GROQ_API_KEY"],
                       model=STT_MODEL, language="en"),
        llm=build_llm(),
        tts=build_tts(),
        turn_handling=turn_handling(),
        user_away_timeout=AWAY_SECONDS,
    )

    # ---- latency: from "VAD says the caller stopped speaking" to "first reply audio is playing" ----
    os.makedirs(LOG_DIR, exist_ok=True)
    latency_file = os.path.join(LOG_DIR, "latency.csv")
    if not os.path.exists(latency_file):
        with open(latency_file, "w") as f:
            f.write("timestamp,latency_ms\n")
    caller_stopped_at: float | None = None

    @session.on("agent_state_changed")
    def _agent_state(ev):
        nonlocal caller_stopped_at
        if ev.new_state == "speaking" and caller_stopped_at is not None:
            ms = (ev.created_at - caller_stopped_at) * 1000
            caller_stopped_at = None
            if 0 < ms < 30_000:
                with open(latency_file, "a") as f:
                    f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')},{ms:.0f}\n")

    # ---- silence: ask once, wait, then say goodbye and hang up ----
    inactivity_task: asyncio.Task | None = None

    async def _inactivity_flow():
        await session.generate_reply(instructions="Politely ask if the caller is still there.")
        await asyncio.sleep(10)
        await session.say("I'll end the call now. Please call again any time. Goodbye!")
        await ctx.delete_room()

    @session.on("user_state_changed")
    def _user_state(ev):
        nonlocal caller_stopped_at, inactivity_task
        if ev.new_state == "away":
            caller_stopped_at = None
            inactivity_task = asyncio.create_task(_inactivity_flow())
            return
        if inactivity_task is not None:          # caller is back
            inactivity_task.cancel()
            inactivity_task = None
        if ev.old_state == "speaking" and ev.new_state == "listening":
            caller_stopped_at = ev.created_at

    # ---- business facts: loaded now, re-read every few seconds so admin edits show up mid-call ----
    current = build_instructions(booker, await booker.get_business_info())
    agent = Receptionist(booker, current)

    async def _keep_instructions_fresh():
        nonlocal current
        while True:
            await asyncio.sleep(INFO_REFRESH_SECONDS)
            try:
                latest = build_instructions(booker, await booker.get_business_info())
                if latest != current:
                    await agent.update_instructions(latest)
                    current = latest
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("could not refresh business info")

    refresh_task = asyncio.create_task(_keep_instructions_fresh())

    async def _stop_refresh():
        refresh_task.cancel()

    ctx.add_shutdown_callback(_stop_refresh)

    await session.start(room=ctx.room, agent=agent)
    # Fixed greeting spoken directly: no LLM call, so the caller hears it as soon as TTS can produce audio.
    session.say(f"Hello, thanks for calling {booker.biz['name']}. How can I help you today?")


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))
