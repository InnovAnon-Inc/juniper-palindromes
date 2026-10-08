#!/usr/bin/env python3

import os
import re
import time
import wave
import json
import asyncio
import threading
import websockets
import numpy as np
import pyttsx3
from scipy.io import wavfile
from flask import Flask, render_template_string, jsonify, send_from_directory

# ==========================================
# CONFIGURATION & CONSTANTS
# ==========================================
HTTP_PORT = 5012
WS_URL = "ws://127.0.0.1:65432"
CACHE_DIR = os.path.join(os.path.dirname(__file__), "narration_cache")
os.makedirs(CACHE_DIR, exist_ok=True)

CHORD_INTERVAL_SEC = 60      # 1 minute per chord
SCALE_INTERVAL_SEC = 420     # 7 minutes per scale (7 chords per mode)

# Pre-boundary warning trigger time (in seconds before boundary)
LEAVING_ANNOUNCEMENT_LEAD_TIME = 5

# ==========================================
# MUSICAL NOTATION PHONETIC TRANSLATOR
# ==========================================
def clean_scale_name(scale_text):
    """Strips 'Mode X: ' prefixes from scale strings."""
    if not scale_text:
        return ""
    # Remove pattern like "Mode 1: ", "Mode 4: "
    cleaned = re.sub(r'Mode\s+\d+:\s*', '', scale_text)
    return cleaned

def phoneticize_music_text(text):
    """
    Translates chord/scale notation into spoken English words for TTS.
    Example: 'Ab 7#5' -> 'A flat 7 sharp 5'
             'Cm7b5'  -> 'C minor 7 flat 5'
    """
    if not text:
        return ""

    s = clean_scale_name(text)

    # Standardize flat/sharp symbols or letters before chord qualities
    s = re.sub(r'([A-G])b', r'\1 flat', s)
    s = re.sub(r'([A-G])#', r'\1 sharp', s)

    # Handle remaining accidental symbols
    s = s.replace('#', ' sharp ')
    s = s.replace('♭', ' flat ')

    # Translate chord quality shortcodes
    # Use word boundary lookbehinds/lookaheads to prevent corrupting regular words
    s = re.sub(r'\bMaj7\b', ' Major 7', s)
    s = re.sub(r'\bMaj\b', ' Major', s)
    s = re.sub(r'\bmin7\b', ' minor 7', s)
    s = re.sub(r'\bm7b5\b', ' minor 7 flat 5', s)
    s = re.sub(r'\bm7\b', ' minor 7', s)
    s = re.sub(r'\bm\(Maj7\)', ' minor Major 7', s)
    s = re.sub(r'\bdim7\b', ' diminished 7', s)
    s = re.sub(r'\bdim\b', ' diminished', s)
    s = re.sub(r'\bsus4\b', ' suspended 4', s)
    s = re.sub(r'\bsus2\b', ' suspended 2', s)

    # Standalone 'm' after root/accidental (e.g., 'Am', 'F#m')
    s = re.sub(r'([A-G](?: flat| sharp)?)m(\d|\b)', r'\1 minor \2', s)

    # Clean up accidental shorthands attached to intervals like 'b5' or '#5'
    s = re.sub(r'b(\d)', r' flat \1', s)

    # Normalize multiple whitespace
    return re.sub(r'\s+', ' ', s).strip()

# ==========================================
# NARRATION SERVER ENGINE
# ==========================================
class FlaskChimesNarrator:
    #def __init__(self, ws_url=WS_URL, speech_rate=140):
    def __init__(self, ws_url=WS_URL, speech_rate=120):
        self.ws_url = ws_url
        self.tts_engine = pyttsx3.init()
        self.tts_engine.setProperty('rate', speech_rate)

        self.tts_engine.setProperty('voice', 'en-us-nyc')
        
        self.lock = threading.Lock()
        
        # Internal State
        self.current_ws_state = None
        
        # Boundary flags to prevent re-triggering within the same cycle
        self.last_leaving_announced_bucket = -1
        self.last_entering_announced_bucket = -1
        
        # Display/script cache
        self.current_polychord = ""
        self.current_polyscale = ""
        
        # App state served via Flask API
        self.app_state = {
            "current_action": "Initializing...",
            "last_narration": "Waiting for clock sync...",
            "audio_file": None,
            "audio_id": 0,
            "polychord": "",
            "polyscale": ""
        }

    def _pad_wav_with_silence(self, filepath, silence_duration_sec=0.3):
        """Appends trailing silence to prevent TTS truncation."""
        try:
            sr, data = wavfile.read(filepath)
            silence_samples = int(sr * silence_duration_sec)
            
            if data.ndim == 1:
                silence = np.zeros(silence_samples, dtype=data.dtype)
            else:
                silence = np.zeros((silence_samples, data.shape[1]), dtype=data.dtype)

            padded_data = np.concatenate((data, silence))
            wavfile.write(filepath, sr, padded_data)
        except Exception as e:
            print(f"Error padding audio: {e}")

    def generate_tts_wav(self, text, filename="narration.wav"):
        """Generates a TTS WAV file from text."""
        filepath = os.path.join(CACHE_DIR, filename)
        self.tts_engine.save_to_file(text, filepath)
        self.tts_engine.runAndWait()
        self._pad_wav_with_silence(filepath, silence_duration_sec=0.3)
        return filename

    def get_wav_duration(self, filepath):
        """Calculates exact duration of a WAV file."""
        try:
            with wave.open(filepath, 'r') as f:
                frames = f.getnframes()
                rate = f.getframerate()
                return frames / float(rate)
        except Exception as e:
            print(f"Error reading WAV duration: {e}")
            return 2.0

    def speak_phrase(self, text, filename_prefix):
        """Generates TTS WAV and broadcasts to web players."""
        print(f"[NARRATION] {text}")
        filename = f"{filename_prefix}.wav"
        filepath = os.path.join(CACHE_DIR, filename)
        
        self.generate_tts_wav(text, filename)
        duration = self.get_wav_duration(filepath)

        with self.lock:
            self.app_state["current_action"] = "Narrating"
            self.app_state["last_narration"] = text
            self.app_state["audio_file"] = filename
            self.app_state["audio_id"] += 1

        time.sleep(duration)

        with self.lock:
            self.app_state["current_action"] = "Listening for clock boundary"

    def start_ws_listener(self):
        """Runs an async WebSocket client to receive chimes.py clock states."""
        async def listen():
            while True:
                try:
                    async with websockets.connect(self.ws_url) as ws:
                        print(f"[WS] Connected to chimes.py at {self.ws_url}")
                        while True:
                            msg = await ws.recv()
                            data = json.loads(msg)
                            with self.lock:
                                self.current_ws_state = data
                except Exception as e:
                    print(f"[WS ERROR] Connection lost ({e}). Retrying in 2 seconds...")
                    await asyncio.sleep(2.0)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(listen())

    def start_narration_loop(self):
        """Monitors clock updates and handles two-stage boundary narration."""
        while True:
            with self.lock:
                state = self.current_ws_state

            if not state:
                time.sleep(0.2)
                continue

            current_tick = state.get("tick", 0)
            second_of_minute = current_tick % CHORD_INTERVAL_SEC
            chord_bucket = current_tick // CHORD_INTERVAL_SEC
            scale_bucket = current_tick // SCALE_INTERVAL_SEC

            # Format raw strings
            cur_chord = state.get("chord_name", "Unknown Chord")
            cur_outer_chord = state.get("outer_chord_name", "")
            raw_polychord = f"{cur_chord} over {cur_outer_chord}" if cur_outer_chord else cur_chord

            raw_mode = clean_scale_name(state.get("mode", "Unknown Scale"))
            raw_outer_mode = clean_scale_name(state.get("outer_mode", ""))
            raw_polyscale = f"{raw_mode} against {raw_outer_mode}" if raw_outer_mode else raw_mode

            # Update public UI state with clean text
            with self.lock:
                self.app_state["polychord"] = raw_polychord
                self.app_state["polyscale"] = raw_polyscale

            # Initialize buckets on startup
            if self.last_entering_announced_bucket == -1:
                self.last_leaving_announced_bucket = chord_bucket
                self.last_entering_announced_bucket = chord_bucket
                self.current_polychord = raw_polychord
                self.current_polyscale = raw_polyscale

            # -------------------------------------------------------------
            # STAGE 1: BEFORE CUSP (~5s before chord/scale transition)
            # -------------------------------------------------------------
            if second_of_minute >= (CHORD_INTERVAL_SEC - LEAVING_ANNOUNCEMENT_LEAD_TIME):
                if self.last_leaving_announced_bucket < chord_bucket + 1:
                    is_upcoming_scale_change = ((current_tick + LEAVING_ANNOUNCEMENT_LEAD_TIME) // SCALE_INTERVAL_SEC) > scale_bucket
                    
                    spoken_chord = phoneticize_music_text(self.current_polychord)
                    spoken_scale = phoneticize_music_text(self.current_polyscale)

                    if is_upcoming_scale_change:
                        script = f"Changing from scale {spoken_scale}. Leaving chord {spoken_chord}."
                    else:
                        script = f"Leaving chord {spoken_chord}."

                    self.speak_phrase(script, "leaving_announcement")
                    self.last_leaving_announced_bucket = chord_bucket + 1

            # -------------------------------------------------------------
            # STAGE 2: ON CUSP (Immediately after chord/scale transition)
            # -------------------------------------------------------------
            if chord_bucket > self.last_entering_announced_bucket:
                is_scale_change = scale_bucket > (self.last_entering_announced_bucket // 7)

                spoken_chord = phoneticize_music_text(raw_polychord)
                spoken_scale = phoneticize_music_text(raw_polyscale)

                if is_scale_change:
                    script = f"Entering chord {spoken_chord}. Changing to scale {spoken_scale}."
                else:
                    script = f"Scale: {spoken_scale}. Entering chord {spoken_chord}."

                self.speak_phrase(script, "entering_announcement")

                # Cache newly entered chord/scale for the next "leaving" announcement
                self.current_polychord = raw_polychord
                self.current_polyscale = raw_polyscale
                self.last_entering_announced_bucket = chord_bucket

            time.sleep(0.1)

# ==========================================
# FLASK APPLICATION SETUP
# ==========================================
app = Flask(__name__)
narrator = FlaskChimesNarrator(ws_url=WS_URL, speech_rate=140)

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Chimes Narration Player</title>
    <style>
        body { font-family: monospace; background: #121212; color: #00ffcc; text-align: center; padding: 40px; }
        .card { border: 2px solid #00ffcc; padding: 20px; border-radius: 8px; max-width: 600px; margin: 0 auto; background: #1a1a1a; }
        h1 { font-size: 1.8em; }
        p { font-size: 1.1em; color: #ffffff; }
        .highlight { color: #ff00ff; }
        audio { margin-top: 20px; width: 100%; }
    </style>
</head>
<body>
    <div class="card">
        <h1>Chimes TTS Narrator</h1>
        <p><strong>Status:</strong> <span id="status" class="highlight">Connecting...</span></p>
        <p><strong>Current Polyscale:</strong> <span id="scale">-</span></p>
        <p><strong>Current Polychord:</strong> <span id="chord">-</span></p>
        <p><strong>Last Script:</strong> <i id="script">-</i></p>
        
        <audio id="audioPlayer" controls></audio>
    </div>

    <script>
        let lastAudioId = -1;
        const player = document.getElementById('audioPlayer');

        async function pollState() {
            try {
                const response = await fetch('/api/state');
                const data = await response.json();

                document.getElementById('status').innerText = data.current_action;
                document.getElementById('scale').innerText = data.polyscale;
                document.getElementById('chord').innerText = data.polychord;
                document.getElementById('script').innerText = data.last_narration;

                if (data.audio_file && data.audio_id !== lastAudioId) {
                    lastAudioId = data.audio_id;
                    player.src = '/audio/' + data.audio_file;
                    player.play().catch(e => console.log('Autoplay deferred:', e));
                }
            } catch (err) {
                document.getElementById('status').innerText = "Disconnected from Flask API";
            }
        }

        setInterval(pollState, 1000);
    </script>
</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route("/audio/<filename>")
def serve_audio(filename):
    return send_from_directory(CACHE_DIR, filename)

@app.route("/api/state")
def get_state():
    with narrator.lock:
        return jsonify(narrator.app_state)

if __name__ == "__main__":
    threading.Thread(target=narrator.start_ws_listener, daemon=True).start()
    threading.Thread(target=narrator.start_narration_loop, daemon=True).start()
    
    print(f"[FLASK SERVER] Hosting Narration Audio Server on http://0.0.0.0:{HTTP_PORT}")
    app.run(host="0.0.0.0", port=HTTP_PORT, debug=False)
