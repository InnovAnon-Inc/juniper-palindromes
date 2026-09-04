# NOTE this version has better palindromes
#import io
#import math
#import random
#import re
#import wave
#import json
#import threading
#import asyncio
#import numpy as np
#import pyttsx3
#import websockets
#from collections import defaultdict
#from flask import Flask, request, send_file, render_template_string, jsonify
#import nltk
#from nltk.corpus import wordnet as wn, cmudict
#
## Ensure required NLTK resources are available
#nltk.download('cmudict', quiet=True)
#nltk.download('wordnet', quiet=True)
#
#app = Flask(__name__)
#
## --- 1. WEBSOCKET SYNC WITH CHIMES.PY ---
#CURRENT_CHORD = []
#A4_FREQ = 432.0
#WS_URL = "ws://127.0.0.1:65432"
#
#def note_name_to_freq(note_str, a4_ref=432.0):
#    note_names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
#    flats = {'Db': 'C#', 'Eb': 'D#', 'Gb': 'F#', 'Ab': 'G#', 'Bb': 'A#'}
#    name = note_str[:-1]
#    octave = int(note_str[-1])
#    if name in flats:
#        name = flats[name]
#    semitones = note_names.index(name) + (octave + 1) * 12
#    return a4_ref * (2.0 ** ((semitones - 69) / 12.0))
#
#def get_nearest_chord_tone(target_freq=432.0):
#    if not CURRENT_CHORD:
#        return target_freq
#    freqs = [note_name_to_freq(n, A4_FREQ) for n in CURRENT_CHORD]
#    return min(freqs, key=lambda f: abs(f - target_freq))
#
#def listen_to_chimes():
#    async def loop():
#        global CURRENT_CHORD, A4_FREQ
#        while True:
#            try:
#                async with websockets.connect(WS_URL) as ws:
#                    while True:
#                        data = json.loads(await ws.recv())
#                        CURRENT_CHORD = data.get("chord", [])
#                        A4_FREQ = data.get("a4_freq", 432.0)
#            except Exception:
#                await asyncio.sleep(2.0)
#    asyncio.run(loop())
#
#threading.Thread(target=listen_to_chimes, daemon=True).start()
#
## --- 2. LEXICAL & PHONETIC INDEXING ---
#CMU_DICT = cmudict.dict()
#
#def is_valid_word(w):
#    return w.lower() in CMU_DICT
#
#VOCAB = [w.lower() for w in set(wn.all_lemma_names()) if w.isalpha() and len(w) >= 3 and is_valid_word(w)]
#
## Tracks consumed single-word seeds to ensure strictly 1-time usage before reusing
#USED_PALINDROME_SEEDS = set()
#SEEN_PAIRS = set()
#
#def get_word_phonetics(word):
#    """Returns (stress_string, tail_rhyme, initial_consonant_phoneme) for a given word."""
#    word = word.lower()
#    if word not in CMU_DICT:
#        return "", "", ""
#
#    phones = CMU_DICT[word][0]
#    stresses = "".join([char[-1] for char in phones if char[-1].isdigit()])
#    
#    rhyme_idx = 0
#    for idx, phone in enumerate(phones):
#        if any(char.isdigit() for char in phone):
#            rhyme_idx = idx
#    tail_rhyme = "-".join(phones[rhyme_idx:])
#    
#    initial_phoneme = phones[0]
#    return stresses, tail_rhyme, initial_phoneme
#
#def analyze_phrase(phrase):
#    """Analyzes prosody and phonetics across multi-word phrases."""
#    words = phrase.split()
#    phrase_stress = ""
#    tail_rhyme = ""
#    first_onset = ""
#
#    for idx, w in enumerate(words):
#        stresses, rhyme, onset = get_word_phonetics(w)
#        phrase_stress += stresses
#        if idx == 0:
#            first_onset = onset
#        tail_rhyme = rhyme
#
#    return phrase_stress, tail_rhyme, first_onset
#
## Pre-index candidates for rapid cadence/rhyme matching
#CADENCE_INDEX = defaultdict(list)
#for w in VOCAB:
#    stress, rhyme, onset = get_word_phonetics(w)
#    if stress:
#        CADENCE_INDEX[stress].append({'word': w, 'rhyme': rhyme, 'onset': onset})
#
## --- 3. DYNAMIC PALINDROME & CADENCE MATCHING ENGINE ---
#def find_prosodic_companions(seed_phrase, count_range=(3, 7)):
#    """
#    Finds 3-7 words or phrases with identical or closely matched metrical stress
#    patterns and phonetic ties to the seed phrase.
#    """
#    target_stress, target_rhyme, target_onset = analyze_phrase(seed_phrase)
#    if not target_stress:
#        return []
#
#    candidates = CADENCE_INDEX.get(target_stress, [])
#    scored_matches = []
#
#    seed_words = set(seed_phrase.split())
#
#    for cand in candidates:
#        word = cand['word']
#        if word in seed_words:
#            continue
#        
#        score = 1  # Metrical stress match
#        if cand['onset'] == target_onset:
#            score += 2  # Alliteration bonus
#        if cand['rhyme'] == target_rhyme:
#            score += 3  # Rhyme bonus
#
#        scored_matches.append((score, word))
#
#    scored_matches.sort(key=lambda x: x[0], reverse=True)
#
#    # Fallback to general vocabulary if exact stress matches are scarce
#    if not scored_matches:
#        for w in VOCAB:
#            if w not in seed_words:
#                scored_matches.append((1, w))
#                if len(scored_matches) >= 20:
#                    break
#
#    target_count = random.randint(count_range[0], count_range[1])
#    selected = [w for _, w in scored_matches[:target_count]]
#    return selected
#
#def generate_dynamic_palindrome_stream(max_results=5):
#    """
#    Generates palindromes structured with strict 1-time seed rotation 
#    and paired prosodic companion phrase blocks.
#    """
#    global USED_PALINDROME_SEEDS
#    results = []
#    
#    # Class 1: Single-word palindromes
#    all_singles = [w for w in VOCAB if len(w) >= 3 and w == w[::-1]]
#    
#    # Filter out already used seeds to prevent repeated "boob" runs
#    available_singles = [s for s in all_singles if s not in USED_PALINDROME_SEEDS]
#    
#    # Reset pool if all single palindromes have been rotated through
#    if not available_singles:
#        USED_PALINDROME_SEEDS.clear()
#        available_singles = list(all_singles)
#
#    random.shuffle(available_singles)
#    
#    # Class 2: Reversible word pairs (e.g. "bird" / "drib")
#    rev_map = {}
#    for w in VOCAB:
#        rev = w[::-1]
#        if w != rev and is_valid_word(rev):
#            rev_map[w] = rev
#
#    rev_keys = list(rev_map.keys())
#    random.shuffle(rev_keys)
#
#    for w1 in rev_keys:
#        if len(results) >= max_results:
#            break
#            
#        if not available_singles:
#            USED_PALINDROME_SEEDS.clear()
#            available_singles = list(all_singles)
#            random.shuffle(available_singles)
#
#        w2 = rev_map[w1]
#        pair_key = tuple(sorted([w1, w2]))
#        
#        if pair_key in SEEN_PAIRS:
#            continue
#
#        chosen_seed = available_singles.pop()
#        USED_PALINDROME_SEEDS.add(chosen_seed)
#        
#        sandwich_phrase = f"{w1} {chosen_seed} {w2}"
#        SEEN_PAIRS.add(pair_key)
#        
#        # Retrieve 3 to 7 cadence/prosody matched companion phrases
#        companions = find_prosodic_companions(sandwich_phrase, count_range=(3, 7))
#        
#        results.append({
#            "palindrome": sandwich_phrase,
#            "companions": companions
#        })
#
#    return results
#
## --- 4. MORSE AUDIO SYNTHESIS ---
#MORSE_MAP = {
#    'A': '.-', 'B': '-...', 'C': '-.-.', 'D': '-..', 'E': '.', 'F': '..-.',
#    'G': '--.', 'H': '....', 'I': '..', 'J': '.---', 'K': '-.-', 'L': '.-..',
#    'M': '--', 'N': '-.', 'O': '---', 'P': '.--.', 'Q': '--.-', 'R': '.-.',
#    'S': '...', 'T': '-', 'U': '..-', 'V': '...-', 'W': '.--', 'X': '-..-',
#    'Y': '-.--', 'Z': '--..', '0': '-----', '1': '.----', '2': '..---',
#    '3': '...--', '4': '....-', '5': '.....', '6': '-....', '7': '--...',
#    '8': '---..', '9': '----.', ' ': '/'
#}
#
#SAMPLE_RATE = 44100
#
#def generate_tone(duration_sec, freq):
#    t = np.linspace(0, duration_sec, int(SAMPLE_RATE * duration_sec), False)
#    tone = 0.5 * np.sin(2 * np.pi * freq * t)
#    fade_len = int(SAMPLE_RATE * 0.005)
#    if len(tone) > 2 * fade_len:
#        tone[:fade_len] *= np.linspace(0, 1, fade_len)
#        tone[-fade_len:] *= np.linspace(1, 0, fade_len)
#    return tone
#
#def generate_silence(duration_sec):
#    return np.zeros(int(SAMPLE_RATE * duration_sec))
#
#def text_to_morse_audio(text, unit_duration=0.08):
#    clean_text = re.sub(r'\(.*?\)', '', text).strip().upper()
#    target_freq = get_nearest_chord_tone(432.0)
#    audio_chunks = []
#    words = clean_text.split(' ')
#    
#    for w_idx, word in enumerate(words):
#        for c_idx, char in enumerate(word):
#            if char in MORSE_MAP:
#                symbol = MORSE_MAP[char]
#                for s_idx, elem in enumerate(symbol):
#                    dur = unit_duration * (3 if elem == '-' else 1)
#                    audio_chunks.append(generate_tone(dur, target_freq))
#                    if s_idx < len(symbol) - 1:
#                        audio_chunks.append(generate_silence(unit_duration))
#                if c_idx < len(word) - 1:
#                    audio_chunks.append(generate_silence(unit_duration * 3))
#        
#        if w_idx < len(words) - 1:
#            curr_time = sum(len(c) for c in audio_chunks) / SAMPLE_RATE
#            next_tick = math.ceil(curr_time) or 1.0
#            gap = next_tick - curr_time
#            jitter = random.uniform(-0.05, 0.05)
#            audio_chunks.append(generate_silence(max(0.2, gap + jitter)))
#
#    full_audio = np.concatenate(audio_chunks) if audio_chunks else generate_silence(0.5)
#    pcm_audio = (full_audio * 32767).astype(np.int16)
#    
#    buffer = io.BytesIO()
#    with wave.open(buffer, 'wb') as wf:
#        wf.setnchannels(1)
#        wf.setsampwidth(2)
#        wf.setframerate(SAMPLE_RATE)
#        wf.writeframes(pcm_audio.tobytes())
#    buffer.seek(0)
#    return buffer
#
## --- 5. FLASK INTERFACE ---
#HTML_TEMPLATE = """
#<!DOCTYPE html>
#<html>
#<head>
#    <title>Dynamic Cadence-Matched Palindrome Stream</title>
#    <meta name="viewport" content="width=device-width, initial-scale=1.0">
#    <style>
#        body { font-family: sans-serif; margin: 0; padding: 20px; background: #0f0f11; color: #e0e0e0; text-align: center; }
#        .container { max-width: 600px; margin: 0 auto; padding-top: 30px; }
#        .start-btn { 
#            background: #2e7d32; color: white; border: none; padding: 18px 36px; 
#            font-size: 1.4rem; border-radius: 50px; cursor: pointer; width: 100%;
#            box-shadow: 0 4px 15px rgba(0,0,0,0.5); margin-bottom: 25px;
#        }
#        .start-btn:active { background: #1b5e20; }
#        .status { font-size: 1.1rem; color: #888; margin-bottom: 15px; min-height: 1.5em; }
#        .active-text { font-size: 1.7rem; font-weight: bold; color: #81c784; margin: 15px 0; min-height: 2em; }
#        .companion-text { font-size: 1.2rem; color: #ffd54f; margin-bottom: 20px; }
#        ul { list-style: none; padding: 0; text-align: left; opacity: 0.75; max-height: 250px; overflow-y: auto; }
#        li { background: #1e1e24; margin: 6px 0; padding: 10px 15px; border-radius: 6px; font-size: 0.95rem; }
#        .comp-tag { font-size: 0.8rem; color: #80cbc4; margin-left: 8px; }
#    </style>
#</head>
#<body>
#    <div class="container">
#        <h2>Cadence-Matched Palindrome Stream</h2>
#        <p class="status" id="status-text">Stream Ready. Tap to start playlist.</p>
#        
#        <button class="start-btn" id="main-btn" onclick="startPlaylist()">▶ Play Dynamic Sequence</button>
#        
#        <div class="active-text" id="now-playing"></div>
#        <div class="companion-text" id="companion-playing"></div>
#
#        <h3>Upcoming Palindrome Queue:</h3>
#        <ul id="queue-list"></ul>
#    </div>
#
#    <script>
#        let playlist = {{ palindromes | tojson }};
#        let currentIndex = 0;
#        let isFetching = false;
#
#        function updateUIQueue() {
#            const list = document.getElementById('queue-list');
#            list.innerHTML = '';
#            playlist.slice(currentIndex).forEach(item => {
#                const li = document.createElement('li');
#                li.innerHTML = `<strong>${item.palindrome}</strong> <span class="comp-tag">(${item.companions.length} prosodic echoes)</span>`;
#                list.appendChild(li);
#            });
#        }
#
#        async function fetchNextBatch() {
#            if (isFetching) return;
#            isFetching = true;
#            document.getElementById('status-text').innerText = 'Indexing new palindromes...';
#            try {
#                const res = await fetch('/generate');
#                const data = await res.json();
#                playlist = playlist.concat(data.palindromes);
#                document.getElementById('status-text').innerText = `Streaming (${playlist.length - currentIndex} queued)`;
#            } catch (err) {
#                console.error("Fetch error:", err);
#            } finally {
#                isFetching = false;
#            }
#        }
#
#        function startPlaylist() {
#            document.getElementById('main-btn').style.display = 'none';
#            playNextBlock();
#        }
#
#        async function playAudio(url) {
#            return new Promise((resolve) => {
#                const audio = new Audio(url);
#                audio.onended = resolve;
#                audio.onerror = resolve;
#                audio.play();
#            });
#        }
#
#        async function playPhraseSequence(phrase) {
#            const ttsUrl = `/tts?text=${encodeURIComponent(phrase)}`;
#            const morseUrl = `/morse?text=${encodeURIComponent(phrase)}`;
#
#            // 1. Narrate
#            await playAudio(ttsUrl);
#            await new Promise(r => setTimeout(r, 350));
#
#            // 2. Morse
#            await playAudio(morseUrl);
#            await new Promise(r => setTimeout(r, 350));
#
#            // 3. Narrate again
#            await playAudio(ttsUrl);
#            await new Promise(r => setTimeout(r, 500));
#        }
#
#        async function playNextBlock() {
#            if (playlist.length - currentIndex <= 2) {
#                fetchNextBatch();
#            }
#
#            if (currentIndex >= playlist.length) {
#                document.getElementById('status-text').innerText = 'Buffering stream...';
#                setTimeout(playNextBlock, 1000);
#                return;
#            }
#
#            const item = playlist[currentIndex];
#            const pal = item.palindrome;
#            const companions = item.companions;
#
#            document.getElementById('status-text').innerText = `Playing Palindrome Block ${currentIndex + 1}`;
#            document.getElementById('now-playing').innerText = pal;
#            document.getElementById('companion-playing').innerText = '';
#            updateUIQueue();
#
#            // STEP 1: Narrate, Morse, Narrate -> Palindrome
#            await playPhraseSequence(pal);
#
#            // STEP 2: Loop through 3-7 Cadence-Matched Prosodic Companion Phrases
#            for (let i = 0; i < companions.length; i++) {
#                const comp = companions[i];
#                document.getElementById('companion-playing').innerText = `Cadence Match (${i+1}/${companions.length}): "${comp}"`;
#                await playPhraseSequence(comp);
#            }
#
#            // STEP 3: Narrate, Morse, Narrate -> Return to Palindrome Anchor
#            document.getElementById('companion-playing').innerText = 'Returning to Palindrome Anchor...';
#            await playPhraseSequence(pal);
#
#            currentIndex++;
#            setTimeout(playNextBlock, 1000);
#        }
#
#        updateUIQueue();
#    </script>
#</body>
#</html>
#"""
#
#@app.route("/")
#def index():
#    initial_results = generate_dynamic_palindrome_stream(max_results=5)
#    return render_template_string(HTML_TEMPLATE, palindromes=initial_results)
#
#@app.route("/generate")
#def generate():
#    results = generate_dynamic_palindrome_stream(max_results=5)
#    return jsonify({"palindromes": results})
#
#@app.route("/tts")
#def tts_route():
#    text = request.args.get("text", "radar")
#    engine = pyttsx3.init()
#    engine.setProperty('rate', 120)
#    filename = "tts_output.wav"
#    engine.save_to_file(text, filename)
#    engine.runAndWait()
#    return send_file(filename, mimetype="audio/wav")
#
#@app.route("/morse")
#def morse_route():
#    text = request.args.get("text", "radar")
#    audio_buffer = text_to_morse_audio(text)
#    return send_file(audio_buffer, mimetype="audio/wav", download_name="morse.wav")
#
#if __name__ == "__main__":
#    app.run(host="0.0.0.0", port=5010, debug=False)

# NOTE this version has a better prosody feature
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

VOCAB = [w.lower() for w in set(wn.all_lemma_names()) if w.isalpha() and len(w) >= 3 and is_valid_word(w)]

# Track exhausted palindromes globally to ensure every option plays before looping
USED_PALINDROMES = set()

def get_word_phonetics(word):
    word = word.lower()
    if word not in CMU_DICT:
        return "", "", ""

    phones = CMU_DICT[word][0]
    stresses = "".join([char[-1] for char in phones if char[-1].isdigit()])
    
    rhyme_idx = 0
    for idx, phone in enumerate(phones):
        if any(char.isdigit() for char in phone):
            rhyme_idx = idx
    tail_rhyme = "-".join(phones[rhyme_idx:])
    initial_phoneme = phones[0]
    return stresses, tail_rhyme, initial_phoneme

def analyze_phrase(phrase):
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

CADENCE_INDEX = defaultdict(list)
for w in VOCAB:
    stress, rhyme, onset = get_word_phonetics(w)
    if stress:
        CADENCE_INDEX[stress].append({'word': w, 'rhyme': rhyme, 'onset': onset})

# --- 3. PALINDROME & PROSODIC ECHO ENGINE ---
def find_prosodic_companions(seed_phrase, count=5):
    target_stress, target_rhyme, target_onset = analyze_phrase(seed_phrase)
    if not target_stress:
        return []

    candidates = CADENCE_INDEX.get(target_stress, [])
    scored_matches = []

    for cand in candidates:
        word = cand['word']
        if word in seed_phrase.split():
            continue
        
        score = 1
        if cand['onset'] == target_onset:
            score += 2
        if cand['rhyme'] == target_rhyme:
            score += 3

        scored_matches.append((score, word))

    scored_matches.sort(key=lambda x: x[0], reverse=True)
    return [w for _, w in scored_matches[:count]]

def build_unique_palindrome_pool():
    global USED_PALINDROMES
    pool = []

    # Single-word palindromes
    singles = [w for w in VOCAB if len(w) >= 3 and w == w[::-1]]
    pool.extend(singles)

    # Reversible word-pair palindromes (e.g. "live evil")
    for w in VOCAB:
        rev = w[::-1]
        if w != rev and is_valid_word(rev):
            pool.append(f"{w} {rev}")

    return list(set(pool))

ALL_PALINDROMES = build_unique_palindrome_pool()

def get_next_palindrome_block():
    global USED_PALINDROMES, ALL_PALINDROMES
    
    available = [p for p in ALL_PALINDROMES if p not in USED_PALINDROMES]
    if not available:
        USED_PALINDROMES.clear()
        available = list(ALL_PALINDROMES)

    chosen = random.choice(available)
    USED_PALINDROMES.add(chosen)

    prosodic_count = random.randint(3, 7)
    companions = find_prosodic_companions(chosen, count=prosodic_count)

    return {
        "palindrome": chosen,
        "prosodic_matches": companions
    }

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
    clean_text = text.strip().upper()
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

# --- 5. FLASK INTERFACE & STRUCTURAL PLAYBACK ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Prosodic Palindrome Stream</title>
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
        .sub-text { font-size: 1.1rem; color: #ffd54f; margin-bottom: 20px; }
    </style>
</head>
<body>
    <div class="container">
        <h2>Cadence-Matched Palindrome Stream</h2>
        <p class="status" id="status-text">Stream Ready. Tap to listen.</p>
        
        <button class="start-btn" id="main-btn" onclick="startStream()">▶ Play Sequence</button>
        
        <div class="active-text" id="now-playing"></div>
        <div class="sub-text" id="now-playing-type"></div>
    </div>

    <script>
        async function playAudio(url) {
            return new Promise((resolve) => {
                const audio = new Audio(url);
                audio.onended = resolve;
                audio.onerror = resolve;
                audio.play();
            });
        }

        async function executePhraseBlock(phrase, labelText) {
            document.getElementById('now-playing').innerText = phrase;
            document.getElementById('now-playing-type').innerText = labelText;

            const ttsUrl = `/tts?text=${encodeURIComponent(phrase)}`;
            const morseUrl = `/morse?text=${encodeURIComponent(phrase)}`;

            // 1. Narrate Phrase
            await playAudio(ttsUrl);
            await new Promise(r => setTimeout(r, 200));

            // 2. Morse Phrase
            await playAudio(morseUrl);
            await new Promise(r => setTimeout(r, 200));

            // 3. Narrate Phrase Again
            await playAudio(ttsUrl);
            await new Promise(r => setTimeout(r, 600));
        }

        async function startStream() {
            document.getElementById('main-btn').style.display = 'none';

            while (true) {
                document.getElementById('status-text').innerText = 'Fetching next unique block...';
                const res = await fetch('/generate');
                const block = await res.json();

                const pal = block.palindrome;
                const matches = block.prosodic_matches;

                document.getElementById('status-text').innerText = `Playing Palindrome Block`;

                // - Narrate Palindromic Phrase, Morse, Narrate Again
                await executePhraseBlock(pal, "★ Core Palindrome");

                // - Loop 3-7 Cadence-Matched Phrases
                for (let i = 0; i < matches.length; i++) {
                    await executePhraseBlock(matches[i], `☊ Cadence Echo ${i+1}/${matches.length}`);
                }

                // - Narrate Palindromic Phrase, Morse, Narrate Again
                await executePhraseBlock(pal, "★ Core Palindrome Anchor");
            }
        }
    </script>
</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route("/generate")
def generate():
    block = get_next_palindrome_block()
    return jsonify(block)

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
