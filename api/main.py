import os, secrets
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse
from livekit import api

load_dotenv()
app = FastAPI()
STATIC = Path(__file__).parent / "static"


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/token")
def token():
    room = f"call-{secrets.token_hex(4)}"
    t = (api.AccessToken(os.environ["LIVEKIT_API_KEY"], os.environ["LIVEKIT_API_SECRET"])
         .with_identity(f"caller-{secrets.token_hex(3)}")
         .with_grants(api.VideoGrants(room_join=True, room=room)))
    return {"token": t.to_jwt(), "url": os.environ["LIVEKIT_URL"]}