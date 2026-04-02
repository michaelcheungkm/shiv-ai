"""
TTS Broadcast Server
FastAPI + Pocket TTS (Kyutai) + WebSocket broadcast
"""

import asyncio
import io
import json
import logging
import numpy as np
import scipy.io.wavfile
from pathlib import Path
from typing import List, Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

# ── Pocket TTS setup ──────────────────────────────────────────────────────────
BUILTIN_VOICES = {
    "alba":    "Alba (Female, warm)",
    "marius":  "Marius (Male, clear)",
    "javert":  "Javert (Male, deep)",
    "jean":    "Jean (Male, calm)",
    "fantine": "Fantine (Female, soft)",
    "cosette": "Cosette (Female, bright)",
    "eponine": "Eponine (Female, expressive)",
    "azelma":  "Azelma (Female, neutral)",
}

CUSTOM_VOICES_DIR = Path("custom_voices")
CUSTOM_VOICES_DIR.mkdir(exist_ok=True)

try:
    from pocket_tts import TTSModel
    tts_model = TTSModel.load_model()

    print("⏳ Loading built-in voices into memory...")
    voice_states = {}
    for name in BUILTIN_VOICES:
        try:
            voice_states[name] = tts_model.get_state_for_audio_prompt(name)
            print(f"  ✅ {name}")
        except Exception as e:
            print(f"  ⚠️  {name}: {e}")

    for wav_file in CUSTOM_VOICES_DIR.glob("*.wav"):
        voice_name = f"custom:{wav_file.stem}"
        try:
            voice_states[voice_name] = tts_model.get_state_for_audio_prompt(str(wav_file))
            print(f"  ✅ custom voice: {wav_file.stem}")
        except Exception as e:
            print(f"  ⚠️  custom voice {wav_file.stem}: {e}")

    TTS_AVAILABLE = True
    print(f"✅ Pocket TTS ready — {len(voice_states)} voices loaded")

except ImportError:
    TTS_AVAILABLE = False
    tts_model = None
    voice_states = {}
    print("⚠️  pocket-tts not installed. Run: pip install pocket-tts scipy")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="TTS Broadcast")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Connection manager ────────────────────────────────────────────────────────
class ConnectionManager:
    def __init__(self):
        self.receivers: Set[WebSocket] = set()

    async def connect_receiver(self, ws: WebSocket):
        await ws.accept()
        self.receivers.add(ws)
        logger.info(f"Receiver connected. Total: {len(self.receivers)}")

    def disconnect_receiver(self, ws: WebSocket):
        self.receivers.discard(ws)
        logger.info(f"Receiver disconnected. Total: {len(self.receivers)}")

    async def broadcast(self, data: bytes, meta: dict):
        dead = set()
        for ws in self.receivers:
            try:
                await ws.send_text(json.dumps(meta))
                await ws.send_bytes(data)
            except Exception:
                dead.add(ws)
        for ws in dead:
            self.receivers.discard(ws)

manager = ConnectionManager()

# ── TTS synthesis ─────────────────────────────────────────────────────────────
def all_voices() -> dict:
    voices = {}
    for name, label in BUILTIN_VOICES.items():
        if name in voice_states:
            voices[name] = label
    for key in voice_states:
        if key.startswith("custom:"):
            stem = key[len("custom:"):]
            voices[key] = f"{stem} (custom)"
    return voices

def synthesize(text: str, voice: str) -> bytes:
    if not TTS_AVAILABLE or tts_model is None:
        buf = io.BytesIO()
        silence = np.zeros(4410, dtype=np.float32)
        scipy.io.wavfile.write(buf, 24000, silence)
        return buf.getvalue()

    state = voice_states.get(voice)
    if state is None:
        raise ValueError(f"Voice '{voice}' not loaded")

    audio_tensor = tts_model.generate_audio(state, text)
    audio_np = audio_tensor.numpy()
    audio_int16 = (audio_np * 32767).clip(-32768, 32767).astype(np.int16)

    buf = io.BytesIO()
    scipy.io.wavfile.write(buf, tts_model.sample_rate, audio_int16)
    return buf.getvalue()

# ── HTTP endpoints ─────────────────────────────────────────────────────────────
class SpeakRequest(BaseModel):
    text: str
    voice: str = "alba"

class SpeakBatchItem(BaseModel):
    text: str
    voice: str = "alba"

class SpeakBatchRequest(BaseModel):
    messages: List[SpeakBatchItem]

@app.get("/")
def sender(): return FileResponse("sender.html")

@app.get("/receiver")
def receiver(): return FileResponse("receiver.html")

@app.get("/voices")
def get_voices():
    return all_voices()

@app.post("/speak")
async def speak(req: SpeakRequest):
    if not req.text.strip():
        raise HTTPException(400, "text is empty")
    available = all_voices()
    if req.voice not in available:
        raise HTTPException(400, f"unknown voice '{req.voice}'")

    loop = asyncio.get_event_loop()
    try:
        wav_bytes = await loop.run_in_executor(None, synthesize, req.text, req.voice)
    except Exception as e:
        raise HTTPException(500, str(e))

    meta = {
        "voice": req.voice,
        "voice_label": available[req.voice],
        "text": req.text,
        "receivers": len(manager.receivers),
    }
    await manager.broadcast(wav_bytes, meta)
    return {"status": "ok", "bytes": len(wav_bytes), "receivers": len(manager.receivers)}

@app.post("/speak_batch")
async def speak_batch(req: SpeakBatchRequest):
    """Synthesize and broadcast multiple messages in sequence."""
    if not req.messages:
        raise HTTPException(400, "messages list is empty")
    available = all_voices()

    results = []
    loop = asyncio.get_event_loop()

    for i, item in enumerate(req.messages):
        if not item.text.strip():
            results.append({"index": i, "status": "skipped", "reason": "empty text"})
            continue
        if item.voice not in available:
            results.append({"index": i, "status": "error", "reason": f"unknown voice '{item.voice}'"})
            continue
        try:
            wav_bytes = await loop.run_in_executor(None, synthesize, item.text, item.voice)
            meta = {
                "voice": item.voice,
                "voice_label": available[item.voice],
                "text": item.text,
                "receivers": len(manager.receivers),
                "batch_index": i,
                "batch_total": len(req.messages),
            }
            await manager.broadcast(wav_bytes, meta)
            results.append({"index": i, "status": "ok", "bytes": len(wav_bytes)})
        except Exception as e:
            results.append({"index": i, "status": "error", "reason": str(e)})

    sent = sum(1 for r in results if r["status"] == "ok")
    return {
        "status": "ok",
        "sent": sent,
        "total": len(req.messages),
        "receivers": len(manager.receivers),
        "results": results,
    }

@app.get("/status")
def status():
    return {
        "receivers": len(manager.receivers),
        "tts": TTS_AVAILABLE,
        "voices_loaded": len(voice_states),
    }

# ── WebSocket endpoint ────────────────────────────────────────────────────────
@app.websocket("/ws/receiver")
async def receiver_ws(ws: WebSocket):
    await manager.connect_receiver(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect_receiver(ws)
