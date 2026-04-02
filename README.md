# TTScast — Local TTS Broadcast System

Send text-to-speech audio from any device and have it play instantly on one or more receiver pages.

## Architecture

```
[sender.html]  →  POST /speak  →  [server.py]  →  WebSocket  →  [receiver.html]
 any device         FastAPI        Pocket TTS      broadcast     display screen
```

---

## Quick Start

### 1. Install Python dependencies

```bash
pip install -r requirements.txt
```

> **No extra system installs needed.** Pocket TTS is CPU-only and has no espeak-ng dependency.
> `torch` is a large download (~2 GB) — only needed once.

### 2. Start the server

```bash
uvicorn server:app --host 0.0.0.0 --port 8000
```

On first run, Pocket TTS will download the model weights from Hugging Face (~400 MB) and pre-load all 8 built-in voices. This takes 30–60 seconds once, then it's fast.

### 3. Open the receiver

Open `receiver.html` in a browser on your display machine.

- Set the server URL to `ws://YOUR_SERVER_IP:8000`
- The page will auto-connect and auto-reconnect if the server restarts.

### 4. Open the sender

Open `sender.html` on any device (phone, laptop, tablet).

- Set the server URL to `http://YOUR_SERVER_IP:8000`
- Click **Load voices** to fetch available voices
- Type your text, select a voice, press **▶ Speak** (or Ctrl/Cmd+Enter)

---

## Built-in Voices

| Name | Description |
|------|-------------|
| `alba` | Female, warm |
| `marius` | Male, clear |
| `javert` | Male, deep |
| `jean` | Male, calm |
| `fantine` | Female, soft |
| `cosette` | Female, bright |
| `eponine` | Female, expressive |
| `azelma` | Female, neutral |

---

## Custom Voices (Voice Cloning)

Pocket TTS can clone any voice from a short WAV sample.

1. Record or find a clean WAV file of the voice you want (5–30 seconds, mono, 16-bit)
2. Place the `.wav` file in the `custom_voices/` folder next to `server.py`
3. Restart the server — it will auto-load the custom voice
4. The voice appears in the sender UI as `filename (custom)`

**Tips for best results:**
- Use a clean recording with minimal background noise
- 10–20 seconds of speech is ideal
- 22050 Hz or 44100 Hz mono WAV works best

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/voices` | List available voices |
| `POST` | `/speak` | Generate TTS and broadcast to all receivers |
| `GET` | `/status` | Number of connected receivers + TTS status |
| `WS` | `/ws/receiver` | WebSocket endpoint for receiver pages |

### POST /speak body
```json
{
  "text": "Hello world",
  "voice": "alba"
}
```

---

## Using Over the Internet

If you want to access the sender from outside your local network:

1. **Expose the server** using [ngrok](https://ngrok.com):
   ```bash
   ngrok http 8000
   ```
   This gives you a public URL like `https://abc123.ngrok.io`

2. Update the sender's server URL to `https://abc123.ngrok.io`
3. Update the receiver's WebSocket URL to `wss://abc123.ngrok.io`

For production, run behind nginx with SSL.

---

## Performance Notes

- First synthesis may take 1–2 seconds as the model warms up
- Subsequent requests are fast (~200ms generation time)
- All voices are kept in memory — no reload between requests
- No GPU required; runs on CPU only
