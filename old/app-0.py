import io
import math
import random
import re
import wave
import json
import threading
import asyncio
import numpy as np
import pyttsx3
import websockets
from collections import defaultdict
from flask import Flask, request, send_file, render_template_string, jsonify
import nltk
from nltk.corpus import wordnet as wn, cmudict

# Ensure required NLTK resources are available
nltk.download('cmudict', quiet=True)
nltk.download('wordnet', quiet=True)

app = Flask(__name__)

# --- 1. WEBSOCKET SYNC WITH CHIMES.PY ---
CURRENT_CHORD = []
A4_FREQ = 432.0
WS_URL = "ws://127.0.0.1:65432"

def note_name_to_freq(note_str, a4_ref=432.0):
    note_names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
    flats = {'Db': 'C#', 'Eb': 'D#', 'Gb': 'F#', 'Ab': 'G#', 'Bb': 'A#'}
    name = note_str[:-1]
    octave = int(note_str[-1])
    if name in flats:
        name = flats[name]
    semitones = note_names.index(name) + (octave + 1) * 12
    return a4_ref * (2.0 ** ((semitones - 69) / 12.0))

def get_nearest_chord_tone(target_freq=432.0):
    if not CURRENT_CHORD:
        return target_freq
    freqs = [note_name_to_freq(n, A4_FREQ) for n in CURRENT_CHORD]
    return min(freqs, key=lambda f: abs(f - target_freq))

def listen_to_chimes():
    async def loop():
        global CURRENT_CHORD, A4_FREQ
        while True:
            try:
                async with websockets.connect(WS_URL) as ws:
                    while True:
                        data = json.loads(await ws.recv())
                        CURRENT_CHORD = data.get("chord", [])
                        A4_FREQ = data.get("a4_freq", 432.0)
            except Exception:
                await asyncio.sleep(2.0)
    asyncio.run(loop())

threading.Thread(target=listen_to_chimes, daemon=True).start()

# --- 2. LEXICAL & PHONETIC INDEXING ---
CMU_DICT = cmudict.dict()

def is_valid_word(w):
    return w.lower() in CMU_DICT

# Build clean WordNet vocabulary verified by CMU dict
VOCAB = [w.lower() for w in set(wn.all_lemma_names()) if w.isalpha() and len(w) >= 3 and is_valid_word(w)]

# Track consumed seeds across dynamic generation calls
SEEN_SINGLES = set()
SEEN_PAIRS = set()

def get_word_phonetics(word):
    """Returns (stress_string, tail_rhyme, initial_consonant_phoneme) for a given word."""
    word = word.lower()
    if word not in CMU_DICT:
        return "", "", ""

    phones = CMU_DICT[word][0]
    stresses = "".join([char[-1] for char in phones if char[-1].isdigit()])
    
    # Extract tail rhyme (from last stressed vowel onward)
    rhyme_idx = 0
    for idx, phone in enumerate(phones):
        if any(char.isdigit() for char in phone):
            rhyme_idx = idx
    tail_rhyme = "-".join(phones[rhyme_idx:])
    
    # Extract onset phoneme for alliteration matching
    initial_phoneme = phones[0]
    return stresses, tail_rhyme, initial_phoneme

def analyze_phrase(phrase):
    """Analyzes prosody and phonetics across multi-word phrases."""
    words = phrase.split()
    phrase_stress = ""
    tail_rhyme = ""
    first_onset = ""

    for idx, w in enumerate(words):
        stresses, rhyme, onset = get_word_phonetics(w)
        phrase_stress += stresses
        if idx == 0:
            first_onset = onset
        tail_rhyme = rhyme

    return phrase_stress, tail_rhyme, first_onset

# Pre-index candidates for rapid dynamic cadence, rhyme, and alliteration matching
CADENCE_INDEX = defaultdict(list)
for w in VOCAB:
    stress, rhyme, onset = get_word_phonetics(w)
    if stress:
        CADENCE_INDEX[stress].append({'word': w, 'rhyme': rhyme, 'onset': onset})

# --- 3. DYNAMIC PALINDROME & CADENCE MATCHING ENGINE ---
def find_alliterative_or_rhyming_companions(seed_phrase):
    """
    Generates cadence-matching candidate phrases that incorporate 
    alliteration or rhyming with the seed palindrome.
    """
    target_stress, target_rhyme, target_onset = analyze_phrase(seed_phrase)
    if not target_stress:
        return []

    candidates = CADENCE_INDEX.get(target_stress, [])
    scored_matches = []

    for cand in candidates:
        word = cand['word']
        if word in seed_phrase.split():
            continue
        
        score = 1 # Metrical/Stress match
        if cand['onset'] == target_onset:
            score += 2 # Alliteration bonus
        if cand['rhyme'] == target_rhyme:
            score += 3 # Rhyme bonus

        if score > 1:
            scored_matches.append((score, word))

    scored_matches.sort(key=lambda x: x[0], reverse=True)
    return [w for _, w in scored_matches[:5]]

def generate_dynamic_palindrome_stream(max_results=15):
    """
    Generates palindromic phrases enhanced with alliterative/rhyming 
    sandwich embeddings and companion cadence matches.
    """
    results = []
    
    # Class 1: Single-word trivial palindromes
    singles = [w for w in VOCAB if len(w) >= 4 and w == w[::-1]]
    random.shuffle(singles)
    
    # Class 2: Reversible word pairs (e.g. "bird" / "drib")
    rev_map = {}
    for w in VOCAB:
        rev = w[::-1]
        if w != rev and is_valid_word(rev):
            rev_map[w] = rev

    rev_keys = list(rev_map.keys())
    random.shuffle(rev_keys)

    # Build Alliterative/Rhyming Palindromic Sandwiches (e.g., "bird kazak drib")
    for w1 in rev_keys:
        if len(results) >= max_results:
            break
        w2 = rev_map[w1]
        pair_key = tuple(sorted([w1, w2]))
        
        if pair_key in SEEN_PAIRS:
            continue

        # Look for a single-word palindrome middle seed that shares alliteration/rhyme
        st1, rh1, on1 = get_word_phonetics(w1)
        best_seeds = []
        for s in singles:
            st_s, rh_s, on_s = get_word_phonetics(s)
            if on_s == on1 or rh_s == rh1:
                best_seeds.append(s)

        chosen_seed = random.choice(best_seeds) if best_seeds else (random.choice(singles) if singles else "")
        
        if chosen_seed:
            sandwich_phrase = f"{w1} {chosen_seed} {w2}"
            SEEN_PAIRS.add(pair_key)
            
            # Retrieve dynamic cadence-matching companion
            companions = find_alliterative_or_rhyming_companions(sandwich_phrase)
            companion_str = f" (Cadence Echo: '{companions[0]}')" if companions else ""
            
            results.append(f"{sandwich_phrase}{companion_str}")

    return results

# --- 4. MORSE AUDIO SYNTHESIS ---
MORSE_MAP = {
    'A': '.-', 'B': '-...', 'C': '-.-.', 'D': '-..', 'E': '.', 'F': '..-.',
    'G': '--.', 'H': '....', 'I': '..', 'J': '.---', 'K': '-.-', 'L': '.-..',
    'M': '--', 'N': '-.', 'O': '---', 'P': '.--.', 'Q': '--.-', 'R': '.-.',
    'S': '...', 'T': '-', 'U': '..-', 'V': '...-', 'W': '.--', 'X': '-..-',
    'Y': '-.--', 'Z': '--..', '0': '-----', '1': '.----', '2': '..---',
    '3': '...--', '4': '....-', '5': '.....', '6': '-....', '7': '--...',
    '8': '---..', '9': '----.', ' ': '/'
}

SAMPLE_RATE = 44100

def generate_tone(duration_sec, freq):
    t = np.linspace(0, duration_sec, int(SAMPLE_RATE * duration_sec), False)
    tone = 0.5 * np.sin(2 * np.pi * freq * t)
    fade_len = int(SAMPLE_RATE * 0.005)
    if len(tone) > 2 * fade_len:
        tone[:fade_len] *= np.linspace(0, 1, fade_len)
        tone[-fade_len:] *= np.linspace(1, 0, fade_len)
    return tone

def generate_silence(duration_sec):
    return np.zeros(int(SAMPLE_RATE * duration_sec))

def text_to_morse_audio(text, unit_duration=0.08):
    # Strip cadence echo notation prior to generating Morse code
    clean_text = re.sub(r'\(.*?\)', '', text).strip().upper()
    target_freq = get_nearest_chord_tone(432.0)
    audio_chunks = []
    words = clean_text.split(' ')
    
    for w_idx, word in enumerate(words):
        for c_idx, char in enumerate(word):
            if char in MORSE_MAP:
                symbol = MORSE_MAP[char]
                for s_idx, elem in enumerate(symbol):
                    dur = unit_duration * (3 if elem == '-' else 1)
                    audio_chunks.append(generate_tone(dur, target_freq))
                    if s_idx < len(symbol) - 1:
                        audio_chunks.append(generate_silence(unit_duration))
                if c_idx < len(word) - 1:
                    audio_chunks.append(generate_silence(unit_duration * 3))
        
        if w_idx < len(words) - 1:
            curr_time = sum(len(c) for c in audio_chunks) / SAMPLE_RATE
            next_tick = math.ceil(curr_time) or 1.0
            gap = next_tick - curr_time
            jitter = random.uniform(-0.05, 0.05)
            audio_chunks.append(generate_silence(max(0.2, gap + jitter)))

    full_audio = np.concatenate(audio_chunks) if audio_chunks else generate_silence(0.5)
    pcm_audio = (full_audio * 32767).astype(np.int16)
    
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm_audio.tobytes())
    buffer.seek(0)
    return buffer

# --- 5. FLASK INTERFACE ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Dynamic Palindrome Morse Stream</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body { font-family: sans-serif; margin: 0; padding: 20px; background: #0f0f11; color: #e0e0e0; text-align: center; }
        .container { max-width: 550px; margin: 0 auto; padding-top: 40px; }
        .start-btn { 
            background: #2e7d32; color: white; border: none; padding: 20px 40px; 
            font-size: 1.5rem; border-radius: 50px; cursor: pointer; width: 100%;
            box-shadow: 0 4px 15px rgba(0,0,0,0.5); margin-bottom: 30px;
        }
        .start-btn:active { background: #1b5e20; }
        .status { font-size: 1.1rem; color: #888; margin-bottom: 20px; min-height: 1.5em; }
        .active-text { font-size: 1.6rem; font-weight: bold; color: #81c784; margin: 20px 0; min-height: 2em; }
        ul { list-style: none; padding: 0; text-align: left; opacity: 0.7; max-height: 250px; overflow-y: auto; }
        li { background: #1e1e24; margin: 6px 0; padding: 10px 15px; border-radius: 6px; font-size: 0.95rem; }
    </style>
</head>
<body>
    <div class="container">
        <h2>Cadence-Matched Palindrome Stream</h2>
        <p class="status" id="status-text">Stream Ready. Tap to listen.</p>
        
        <button class="start-btn" id="main-btn" onclick="startPlaylist()">▶ Play Dynamic Stream</button>
        
        <div class="active-text" id="now-playing"></div>

        <h3>Upcoming Queue:</h3>
        <ul id="queue-list">
        {% for p in palindromes %}
            <li>{{ p }}</li>
        {% endfor %}
        </ul>
    </div>

    <script>
        let playlist = {{ palindromes | tojson }};
        let currentIndex = 0;
        let isFetching = false;

        function updateUIQueue() {
            const list = document.getElementById('queue-list');
            list.innerHTML = '';
            playlist.slice(currentIndex).forEach(item => {
                const li = document.createElement('li');
                li.innerText = item;
                list.appendChild(li);
            });
        }

        async function fetchNextBatch() {
            if (isFetching) return;
            isFetching = true;
            document.getElementById('status-text').innerText = 'Generating cadence matches...';
            try {
                const res = await fetch('/generate');
                const data = await res.json();
                playlist = playlist.concat(data.palindromes);
                document.getElementById('status-text').innerText = `Streaming (${playlist.length - currentIndex} queued)`;
            } catch (err) {
                console.error("Fetch error:", err);
            } finally {
                isFetching = false;
            }
        }

        function startPlaylist() {
            document.getElementById('main-btn').style.display = 'none';
            playNext();
        }

        async function playAudio(url) {
            return new Promise((resolve) => {
                const audio = new Audio(url);
                audio.onended = resolve;
                audio.onerror = resolve;
                audio.play();
            });
        }

        async function playSequence(phrase) {
            const cleanPhrase = phrase.replace(/\(.*?\)/g, '').trim();
            const ttsUrl = `/tts?text=${encodeURIComponent(cleanPhrase)}`;
            const morseUrl = `/morse?text=${encodeURIComponent(cleanPhrase)}`;

            // 1. Initial Narration
            await playAudio(ttsUrl);
            await new Promise(r => setTimeout(r, 400));

            // 2. Morse Rhythm
            await playAudio(morseUrl);
            await new Promise(r => setTimeout(r, 400));

            // 3. Reinforcing Narration
            await playAudio(ttsUrl);
        }

        async function playNext() {
            if (playlist.length - currentIndex <= 3) {
                fetchNextBatch();
            }

            if (currentIndex >= playlist.length) {
                document.getElementById('status-text').innerText = 'Buffering stream...';
                setTimeout(playNext, 1000);
                return;
            }

            const phrase = playlist[currentIndex];
            document.getElementById('status-text').innerText = `Playing phrase ${currentIndex + 1}`;
            document.getElementById('now-playing').innerText = phrase;
            updateUIQueue();

            await playSequence(phrase);

            currentIndex++;
            setTimeout(playNext, 1200);
        }
    </script>
</body>
</html>
"""

@app.route("/")
def index():
    initial_results = generate_dynamic_palindrome_stream(max_results=15)
    return render_template_string(HTML_TEMPLATE, palindromes=initial_results)

@app.route("/generate")
def generate():
    results = generate_dynamic_palindrome_stream(max_results=15)
    return jsonify({"palindromes": results})

@app.route("/tts")
def tts_route():
    text = request.args.get("text", "radar")
    engine = pyttsx3.init()
    engine.setProperty('rate', 120)
    filename = "tts_output.wav"
    engine.save_to_file(text, filename)
    engine.runAndWait()
    return send_file(filename, mimetype="audio/wav")

@app.route("/morse")
def morse_route():
    text = request.args.get("text", "radar")
    audio_buffer = text_to_morse_audio(text)
    return send_file(audio_buffer, mimetype="audio/wav", download_name="morse.wav")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5010, debug=False)
