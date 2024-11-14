import os
import json
import base64
from typing import Optional
from dotenv import load_dotenv
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import HTMLResponse
from fastapi.websockets import WebSocketDisconnect
from twilio.twiml.voice_response import Connect, VoiceResponse
import requests
from io import BytesIO

load_dotenv()

# Configuration
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
PORT = int(os.getenv("PORT", 5050))
VOICE_ID = "21m00Tcm4TlvDq8ikWAM"  # Default voice ID
MODEL_ID = "eleven_turbo_v2_5"
SAMPLE_RATE = 8000

app = FastAPI()

if not ELEVENLABS_API_KEY:
    raise ValueError("Missing the ElevenLabs API key. Please set it in the .env file.")


class ElevenLabsClient:
    def __init__(self):
        self.api_key = ELEVENLABS_API_KEY
        self.base_url = "https://api.elevenlabs.io/v1"

    async def text_to_speech(self, text: str, voice_id: str = VOICE_ID) -> bytes:
        """Convert text to speech using ElevenLabs API"""
        url = f"{self.base_url}/text-to-speech/{voice_id}"

        headers = {
            "Accept": "audio/basic",  # For u-law
            "xi-api-key": self.api_key,
            "Content-Type": "application/json",
        }

        data = {
            "text": text,
            "model_id": MODEL_ID,
            "output_format": "ulaw",
            "sample_rate": SAMPLE_RATE,
        }

        response = requests.post(url, json=data, headers=headers)
        response.raise_for_status()
        return response.content


elevenlabs_client = ElevenLabsClient()


@app.get("/", response_class=HTMLResponse)
async def index_page():
    return "ElevenLabs-Twilio Media Stream Server is running!"


@app.api_route("/incoming-call", methods=["GET", "POST"])
async def handle_incoming_call(request: Request):
    """Handle incoming call and return TwiML response to connect to Media Stream."""
    response = VoiceResponse()

    # Add initial greeting
    response.say("Please wait while we connect your call.")
    response.pause(length=1)

    # Connect to websocket stream
    connect = Connect()
    host = request.url.hostname
    connect.stream(url=f"wss://{host}/call/connection")
    response.append(connect)

    return HTMLResponse(content=str(response), media_type="application/xml")


@app.websocket("/call/connection")
async def handle_media_stream(websocket: WebSocket):
    """Handle WebSocket connection for ElevenLabs audio streaming"""
    print("Client connected")
    await websocket.accept()

    stream_sid: Optional[str] = None

    try:
        async for message in websocket.iter_text():
            data = json.loads(message)

            if data["event"] == "start":
                stream_sid = data["start"]["streamSid"]
                print(f"Stream started: {stream_sid}")

                # Get audio from ElevenLabs
                text = "This is a test message from ElevenLabs. You can now hang up. Thank you."
                try:
                    audio_content = await elevenlabs_client.text_to_speech(text)

                    # Send audio to Twilio
                    audio_message = {
                        "streamSid": stream_sid,
                        "event": "media",
                        "media": {
                            "payload": base64.b64encode(audio_content).decode("utf-8")
                        },
                    }
                    await websocket.send_json(audio_message)

                except Exception as e:
                    print(f"Error getting audio from ElevenLabs: {e}")

    except WebSocketDisconnect:
        print("Client disconnected")
    except Exception as e:
        print(f"Error in websocket handler: {e}")
    finally:
        print("WebSocket connection closed")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PORT)
