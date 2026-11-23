"""Serves the call page and mints a LiveKit access token for each caller."""
import os
import secrets
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from livekit import api

load_dotenv()
app = FastAPI(title="Voice receptionist")
STATIC = Path(__file__).parent / "static"
# Serves the optional receptionist photo (api/static/receptionist.jpg|png|webp) used by the call page.
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/token")
def token():
    room = f"call-{secrets.token_hex(4)}"          # one private room per caller
    t = (api.AccessToken(os.environ["LIVEKIT_API_KEY"], os.environ["LIVEKIT_API_SECRET"])
         .with_identity(f"caller-{secrets.token_hex(3)}")
         .with_grants(api.VideoGrants(room_join=True, room=room)))
    return {"token": t.to_jwt(), "url": os.environ["LIVEKIT_URL"]}
