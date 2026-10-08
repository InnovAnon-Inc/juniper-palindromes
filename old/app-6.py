#!/usr/bin/env python3
import asyncio
import io
import json
import os
import re
import threading
import time
import wave
import queue
import aiohttp
import numpy as np
import pyttsx3
import websockets
import requests
import nltk
from collections import defaultdict
from nltk.corpus import cmudict, wordnet, words
from flask import Flask, jsonify, render_template_string, request, send_file, send_from_directory

app = Flask(__name__)

CACHE_DIR = os.path.join(os.path.dirname(__file__), "audio_cache")
os.makedirs(CACHE_DIR, exist_ok=True)

SYNESTHESIA_API_URL = "http://127.0.0.1:5001/sync_chimes"
latest_chimes_state = {}

# Global Melody & Morse State
current_melody = ["C4", "E4", "G4", "B4", "C5"]
melody_lock = threading.Lock()

MORSE_CODE = {
    'A': '.-', 'B': '-...', 'C': '-.-.', 'D': '-..', 'E': '.', 'F': '..-.',
    'G': '--.', 'H': '....', 'I': '..', 'J': '.---', 'K': '-.-', 'L': '.-..',
    'M': '--', 'N': '-.', 'O': '---', 'P': '.--.', 'Q': '--.-', 'R': '.-.',
    'S': '...', 'T': '-', 'U': '..-', 'V': '...-', 'W': '.--', 'X': '-..-',
    'Y': '-.--', 'Z': '--..', '1': '.----', '2': '..---', '3': '...--',
    '4': '....-', '5': '.....', '6': '-....', '7': '--...', '8': '---..',
    '9': '----.', '0': '-----', ' ': '/'
}

# --- NLTK & PALINDROME ENGINE SETUP ---
print("Initializing NLTK and NLP Engine... This may take a moment.")
nltk.download('wordnet', quiet=True)
nltk.download('words', quiet=True)
nltk.download('cmudict', quiet=True)

WORD_USAGE_COUNTS = defaultdict(int)
CMU_DICT = cmudict.dict()
VALID_SHORT_WORDS = {"a", "i", "in", "on", "no", "is", "it", "or", "to", "at", "am", "an", "so", "do", "go", "me", "my", "we", "he", "be", "us", "up", "if"}

def is_valid_real_word(w):
    w_clean = w.lower()
    if not w_clean.isalpha():
        return False
    if len(w_clean) < 3 and w_clean not in VALID_SHORT_WORDS:
        return False
    if w_clean != w and w.isupper():
        return False
    return w_clean in CMU_DICT

VOCAB = [w.lower() for w in set(wordnet.all_lemma_names()) if is_valid_real_word(w)]
VOCAB_SET = set(VOCAB)

class TrieNode:
    def __init__(self):
        self.children = {}
        self.is_word = False

class Trie:
    def __init__(self):
        self.root = TrieNode()

    def insert(self, word):
        node = self.root
        for char in word:
            if char not in node.children:
                node.children[char] = TrieNode()
            node = node.children[char]
        node.is_word = True

    def get_valid_prefixes(self, prefix):
        node = self.root
        for char in prefix:
            if char not in node.children:
                return []
            node = node.children[char]
        
        results = []
        def _dfs(curr_node, path):
            if curr_node.is_word:
                results.append(path)
            for ch, child in curr_node.children.items():
                _dfs(child, path + ch)

        _dfs(node, prefix)
        return results

TRIE = Trie()
for w in VOCAB:
    TRIE.insert(w)

def edit_distance(s1, s2):
    if len(s1) < len(s2):
        return edit_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)
    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    return previous_row[-1]

def is_phrase_valid(phrase):
    words = phrase.lower().split()
    return all(w in VOCAB_SET for w in words)

def record_phrase_usage(phrase):
    for word in phrase.lower().split():
        WORD_USAGE_COUNTS[word] += 1

def extract_structural_candidates(target_word, max_candidates=30):
    target_rev = target_word.lower()[::-1]
    candidates = set()
    t_len = len(target_rev)
    for slice_len in range(t_len, 1, -1):
        sub_prefix = target_rev[:slice_len]
        matches = TRIE.get_valid_prefixes(sub_prefix)
        for m in matches:
            if m != target_word.lower() and len(m) >= 2:
                candidates.add(m)
        if len(candidates) >= max_candidates:
            break
    if len(candidates) < max_candidates and t_len >= 4:
        for i in range(t_len - 2):
            ngram = target_rev[i:i+3]
            for w in VOCAB:
                if len(w) >= 3 and ngram in w:
                    candidates.add(w)
                    if len(candidates) >= max_candidates:
                        break
    return list(candidates)

def find_dynamic_pivots(left_str, right_str, max_pivots=10):
    pivots = []
    for w in VOCAB:
        if len(w) < 2 and len(left_str) > 2:
            continue
        combined = left_str + w + right_str
        clean_c = re.sub(r'[^a-z]', '', combined.lower())
        fudge = edit_distance(clean_c, clean_c[::-1])
        if fudge / len(clean_c) <= 0.8:
            pivots.append((w, fudge))
    pivots.sort(key=lambda x: x[1])
    return [p[0] for p in pivots[:max_pivots]]

def calculate_entropy_fudge(phrase):
    words = phrase.lower().split()
    clean_phrase = re.sub(r'[^a-z]', '', phrase.lower())
    if not clean_phrase:
        return float('inf')
    raw_fudge = edit_distance(clean_phrase, clean_phrase[::-1])
    short_word_count = sum(1 for w in words if len(w) == 1)
    short_penalty = short_word_count * 2.0
    unique_words = set(words)
    repetition_penalty = (len(words) - len(unique_words)) * 1.5
    length_bonus = sum(0.3 for w in words if len(w) >= 4)
    return raw_fudge + short_penalty + repetition_penalty - length_bonus

def generate_target_palindrome(target_word, used_palindromes, max_results=10, max_fudge_ratio=1.2):
    target = target_word.lower()
    if target not in VOCAB_SET:
        return {}
    results = {}
    target_rev = target[::-1]
    candidates = extract_structural_candidates(target)
    for w2 in candidates:
        dynamic_pivots = find_dynamic_pivots(target, w2)
        if not dynamic_pivots:
            dynamic_pivots = [""] 
        for pivot in dynamic_pivots:
            phrase_variants = [
                f"{target} {pivot} {w2}".strip(),
                f"{target} {w2[::-1]} {pivot} {w2}".strip(),
            ]
            if len(target) > len(w2):
                rem = target[len(w2):][::-1]
                if rem in VOCAB_SET:
                    phrase_variants.append(f"{target} {pivot} {rem} {w2}".strip())
            for phrase in phrase_variants:
                clean_p = re.sub(r'[^a-z]', '', phrase.lower())
                fudge_score = calculate_entropy_fudge(phrase)
                fudge_ratio = fudge_score / len(clean_p)
                if fudge_ratio <= max_fudge_ratio and is_phrase_valid(phrase):
                    if phrase not in results or fudge_score < results[phrase]:
                        results[phrase] = round(fudge_score, 2)
    if not results:
        fallback_pivots = find_dynamic_pivots(target, target_rev, max_pivots=5)
        for pivot in fallback_pivots:
            fallback = f"{target} {pivot} {target_rev}".strip()
            fudge_score = calculate_entropy_fudge(fallback)
            results[fallback] = round(fudge_score, 2)

    valid_results = {k: v for k, v in results.items() if k != target_word and k not in used_palindromes}
    sorted_results = dict(sorted(valid_results.items(), key=lambda item: item[1]))
    return dict(list(sorted_results.items())[:max_results])

def process_dictionary_word(word, used_palindromes):
    candidates = generate_target_palindrome(word, used_palindromes, max_results=10)
    if not candidates:
        return None
    best_phrase = next(iter(candidates.keys()))
    record_phrase_usage(best_phrase)
    return {"target": word, "palindrome": best_phrase, "fudge": candidates[best_phrase]}

# --- PALINDROME GENERATOR PIPELINE ---
phrase_queue = queue.Queue(maxsize=10)

def palindrome_generator_worker():
    """Background loop to fetch wordlists and pre-compute palindromes."""
    used_palindromes = []
    print("Palindrome Worker started.")
    while True:
        try:
            # Modify this endpoint to match how your dictionary server exports the wordlist
            response = requests.get("http://127.0.0.1:5000/api/get_wordlist", timeout=10)
            if response.status_code == 200:
                words = response.json().get("words", [])
                if not words:
                    time.sleep(5)
                    continue

                for word in words:
                    result = process_dictionary_word(word, used_palindromes)
                    if result and result.get("palindrome"):
                        phrase = result["palindrome"]
                        used_palindromes.append(phrase)
                        # Blocks if queue is full, keeping memory footprint low
                        phrase_queue.put(phrase) 
            else:
                time.sleep(5)
        except Exception as e:
            print(f"Error communicating with dictionary server: {e}")
            time.sleep(5)

# --- AUDIO GENERATION ---
def note_name_to_freq(note_str, a4_freq=432.0):
    note_names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
    flats = {'Db': 'C#', 'Eb': 'D#', 'Gb': 'F#', 'Ab': 'G#', 'Bb': 'A#'}
    name = note_str[:-1]
    octave = int(note_str[-1]) if note_str[-1].isdigit() else 4
    if name in flats:
        name = flats[name]
    semitones_from_c0 = note_names.index(name) + (octave + 1) * 12
    return a4_freq * (2.0 ** ((semitones_from_c0 - 69) / 12.0))

def get_active_chord_tones():
    inner_chord = latest_chimes_state.get("inner_hand", {}).get("chord_notes", [])
    outer_chord = latest_chimes_state.get("outer_hand", {}).get("chord_notes", [])
    combined = inner_chord + outer_chord
    return combined if combined else current_melody

def generate_tone(freq, duration_ms, sample_rate=44100):
    t = np.linspace(0, duration_ms / 1000.0, int(sample_rate * (duration_ms / 1000.0)), False)
    tone = 0.4 * np.sin(2 * np.pi * freq * t)
    fade_len = int(sample_rate * 0.005)
    if len(tone) > 2 * fade_len:
        tone[:fade_len] *= np.linspace(0, 1, fade_len)
        tone[-fade_len:] *= np.linspace(1, 0, fade_len)
    return tone

def render_melodic_phrase_wav(text, melody=None, filename="melodic_phrase.wav", dot_ms=125, sample_rate=44100):
    if not melody:
        melody = get_active_chord_tones()
    
    dash_ms = dot_ms * 3
    elem_space = np.zeros(int(sample_rate * (dot_ms / 1000.0)))
    char_space = np.zeros(int(sample_rate * (dash_ms / 1000.0)))
    
    words = text.upper().split()
    audio_chunks = []
    note_idx = 0

    for word in words:
        word_start_sample_count = sum(len(c) for c in audio_chunks)
        for char in word:
            if char in MORSE_CODE:
                pattern = MORSE_CODE[char]
                for symbol in pattern:
                    note_str = melody[note_idx % len(melody)]
                    freq = note_name_to_freq(note_str)
                    note_idx += 1
                    duration = dot_ms if symbol == '.' else dash_ms
                    audio_chunks.append(generate_tone(freq, duration, sample_rate))
                    audio_chunks.append(elem_space)
                audio_chunks.append(char_space)

        current_samples = sum(len(c) for c in audio_chunks)
        word_duration_sec = (current_samples - word_start_sample_count) / sample_rate
        remainder = word_duration_sec - int(word_duration_sec)
        pad_sec = 1.0 - remainder if remainder > 0 else 0.0
        if pad_sec < 0.1:
            pad_sec += 1.0
            
        audio_chunks.append(np.zeros(int(sample_rate * pad_sec)))

    if audio_chunks:
        full_audio = np.concatenate(audio_chunks)
        scaled = np.int16(full_audio / np.max(np.abs(full_audio)) * 32767)
        wavpath = os.path.join(CACHE_DIR, filename)
        with wave.open(wavpath, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(scaled.tobytes())
        return filename
    return None

async def listen_to_chimes():
    global latest_chimes_state
    uri = "ws://127.0.0.1:65432"
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                async with websockets.connect(uri) as ws:
                    while True:
                        msg = await ws.recv()
                        data = json.loads(msg)
                        syn_response = {}
                        try:
                            async with session.post(SYNESTHESIA_API_URL, json=data, timeout=0.2) as resp:
                                if resp.status == 200:
                                    syn_response = await resp.json()
                        except Exception:
                            pass
                        latest_chimes_state = {
                            "tick": data.get("tick"),
                            "inner_hand": {
                                "key": data.get("key"),
                                "mode": data.get("mode"),
                                "scale_notes": data.get("scale_notes", []),
                                "scale_colors": syn_response.get("inner_scale_colors", []),
                                "chord_notes": data.get("chord", []),
                                "chord_colors": syn_response.get("inner_colors", [])
                            },
                            "outer_hand": {
                                "key": data.get("outer_key"),
                                "mode": data.get("outer_mode"),
                                "scale_notes": data.get("outer_scale_notes", []),
                                "scale_colors": syn_response.get("outer_scale_colors", []),
                                "chord_notes": data.get("outer_chord", []),
                                "chord_colors": syn_response.get("outer_colors", [])
                            },
                            "drones": [
                                data.get("sub_root"),
                                data.get("drone_tonic_0"),
                                data.get("drone_tonic_1")
                            ]
                        }
            except Exception:
                await asyncio.sleep(2)

def start_chimes_listener():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(listen_to_chimes())

# --- FRONTEND INTERFACE ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Synchronized Book-Ended Broadcast (Port 5010)</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body { font-family: monospace; background: #0d1117; color: #c9d1d9; padding: 20px; text-align: center; }
        .container { max-width: 600px; margin: 0 auto; }
        .btn { background: #238636; color: white; border: none; padding: 14px 28px; font-size: 1.1rem; border-radius: 6px; cursor: pointer; }
        .btn:hover { background: #2ea043; }
        .card { background: #161b22; border: 1px solid #30363d; border-radius: 6px; padding: 20px; margin-top: 20px; }
        .status { color: #d29922; text-transform: uppercase; font-size: 0.85rem; letter-spacing: 1px; }
        .phrase { font-size: 1.6rem; color: #58a6ff; margin: 15px 0; }
    </style>
</head>
<body>
    <div class="container">
        <h2>Melodic Morse Broadcast Engine (Port 5010)</h2>
        <button class="btn" id="start-btn" onclick="startBroadcastSequence()">Start Broadcast Sequence</button>

        <div class="card" id="display-card" style="display: none;">
            <div class="status" id="status-text">Idle</div>
            <div class="phrase" id="phrase-text">---</div>
        </div>
    </div>

    <script>
        let isMorseLooping = false;

        function playAudio(url) {
            return new Promise((resolve) => {
                const audio = new Audio(url);
                audio.onended = resolve;
                audio.onerror = resolve;
                audio.play();
            });
        }

        async function loopMorseUntilReady(phrase, promiseNextData) {
            isMorseLooping = true;
            while (isMorseLooping) {
                const morseAudioPromise = playAudio(`/api/synthesize_phrase_get?phrase=${encodeURIComponent(phrase)}`);
                const winner = await Promise.race([morseAudioPromise, promiseNextData]);
                
                if (winner && winner.next_phrase) {
                    isMorseLooping = false;
                    return winner;
                }
            }
        }

        async function startBroadcastSequence() {
            document.getElementById('start-btn').style.display = 'none';
            document.getElementById('display-card').style.display = 'block';

            let currentPhrase = "radar level rotator"; 

            while (true) {
                document.getElementById('phrase-text').innerText = `"${currentPhrase}"`;

                // 1. Narrate the phrase
                document.getElementById('status-text').innerText = "1. Narrating Phrase";
                await playAudio(`/api/tts?text=${encodeURIComponent(currentPhrase)}`);

                // 2. Play Morse Code
                document.getElementById('status-text').innerText = "2. Playing Melodic Morse Code";
                await playAudio(`/api/synthesize_phrase_get?phrase=${encodeURIComponent(currentPhrase)}`);

                // 3. Narrate the phrase again (Book-end start)
                document.getElementById('status-text').innerText = "3. Narrating Phrase (Book-end Start)";
                await playAudio(`/api/tts?text=${encodeURIComponent(currentPhrase)}`);

                // 4. Morse code loop while asynchronously generating/fetching the next phrase
                document.getElementById('status-text').innerText = "4. Looping Morse & Waiting for Generation";
                
                const fetchNextPromise = fetch('/api/get_next_phrase')
                    .then(res => res.json());

                const nextPayload = await loopMorseUntilReady(currentPhrase, fetchNextPromise);

                // 5. Narrate phrase again as final book-end transition before switching
                document.getElementById('status-text').innerText = "5. Final Book-end Narration";
                await playAudio(`/api/tts?text=${encodeURIComponent(currentPhrase)}`);

                currentPhrase = nextPayload.next_phrase;
            }
        }
    </script>
</body>
</html>
"""

@app.route('/')
def home():
    return render_template_string(HTML_TEMPLATE)

@app.route('/chimes_state')
def chimes_state():
    return jsonify(latest_chimes_state)

@app.route('/audio/<filename>')
def serve_audio(filename):
    return send_from_directory(CACHE_DIR, filename)

@app.route('/api/tts')
def tts_route():
    text = request.args.get("text", "")
    engine = pyttsx3.init()
    engine.setProperty('rate', 120)
    
    filename = f"tts_{int(time.time() * 1000)}.wav"
    filepath = os.path.join(CACHE_DIR, filename)
    engine.save_to_file(text, filepath)
    engine.runAndWait()
    return send_file(filepath, mimetype="audio/wav")

@app.route('/api/synthesize_phrase_get')
def synthesize_phrase_get():
    phrase = request.args.get("phrase", "").strip()
    with melody_lock:
        melody = list(current_melody)
    filename = f"phrase_{int(time.time() * 1000)}.wav"
    out_file = render_melodic_phrase_wav(phrase, melody, filename=filename)
    return send_from_directory(CACHE_DIR, out_file)

@app.route('/api/get_next_phrase')
def get_next_phrase():
    try:
        # This acts as a block. The frontend promise won't resolve until 
        # a palindrome drops into the queue, enforcing the requested behavior.
        phrase = phrase_queue.get() 
        return jsonify({"next_phrase": phrase})
    except Exception as e:
        print(f"Error popping from local queue: {e}")
        return jsonify({"next_phrase": "fallback phrase"})

@app.route('/api/melody', methods=['GET', 'POST'])
def handle_melody():
    global current_melody
    if request.method == 'POST':
        data = request.get_json() or {}
        notes = data.get("notes", [])
        if notes:
            with melody_lock:
                current_melody = notes
            return jsonify({"status": "success", "melody": current_melody})
        return jsonify({"status": "error", "message": "No notes provided"}), 400
    return jsonify({"melody": current_melody})

if __name__ == '__main__':
    threading.Thread(target=start_chimes_listener, daemon=True).start()
    threading.Thread(target=palindrome_generator_worker, daemon=True).start()
    app.run(host='0.0.0.0', port=5010, debug=False)
