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
    w_clean = w.lower()
    if not w_clean.isalpha() or len(w_clean) < 2:
        return False
    return w_clean in CMU_DICT

# Clean vocabulary excluding acronyms and single characters
VOCAB = [
    w.lower() for w in set(wn.all_lemma_names()) 
    if w.isalpha() and len(w) >= 2 and is_valid_word(w) and not w.isupper()
]

USED_PALINDROMES = set()
USED_PROSODIC_MATCHES = set()

def get_word_phonetics(word):
    """Returns (stresses, tail_rhyme, vowel_nucleus, initial_phoneme) for a given word."""
    word = word.lower()
    if word not in CMU_DICT:
        return "", "", "", ""

    phones = CMU_DICT[word][0]
    stresses = "".join([char[-1] for char in phones if char[-1].isdigit()])
    
    rhyme_idx = 0
    vowel_nucleus = ""
    for idx, phone in enumerate(phones):
        if any(char.isdigit() for char in phone):
            rhyme_idx = idx
            if not vowel_nucleus:
                vowel_nucleus = re.sub(r'\d+', '', phone)
                
    tail_rhyme = "-".join(phones[rhyme_idx:])
    initial_phoneme = phones[0]
    return stresses, tail_rhyme, vowel_nucleus, initial_phoneme

def analyze_phrase(phrase):
    words = phrase.split()
    phrase_stress = ""
    tail_rhyme = ""
    vowels = []
    first_onset = ""

    for idx, w in enumerate(words):
        stresses, rhyme, nucleus, onset = get_word_phonetics(w)
        phrase_stress += stresses
        if idx == 0:
            first_onset = onset
        if nucleus:
            vowels.append(nucleus)
        tail_rhyme = rhyme

    return phrase_stress, tail_rhyme, set(vowels), first_onset

CADENCE_INDEX = defaultdict(list)
for w in VOCAB:
    stress, rhyme, nucleus, onset = get_word_phonetics(w)
    if stress:
        CADENCE_INDEX[stress].append({
            'word': w, 
            'rhyme': rhyme, 
            'nucleus': nucleus,
            'onset': onset
        })

# --- 3. ADVANCED PALINDROME BUILDER (SANDWICHES & ASYMMETRIC PHRASES) ---
def find_asymmetric_palindromes():
    """Finds multi-word asymmetrical spacing palindromes (e.g., 'race car', 'nan an')."""
    asymmetric = []
    vocab_set = set(VOCAB)
    
    for w1 in VOCAB:
        if len(w1) < 2:
            continue
        rev_w1 = w1[::-1]
        for i in range(1, len(rev_w1)):
            part1, part2 = rev_w1[:i], rev_w1[i:]
            if part1 in vocab_set and part2 in vocab_set:
                phrase = f"{part2} {part1}"
                clean = phrase.replace(" ", "")
                if clean == clean[::-1] and part2 != part1:
                    asymmetric.append(phrase)
    return list(set(asymmetric))

def score_phrase_aesthetics(phrase):
    """Scores palindromes for rhyme, assonance, and alliteration."""
    words = phrase.split()
    if len(words) < 2:
        return 0
    
    score = 0
    phonetics = [get_word_phonetics(w) for w in words]
    
    # Check for alliteration (matching initial phonemes)
    onsets = [p[3] for p in phonetics if p[3]]
    if len(onsets) > 1 and len(set(onsets)) < len(onsets):
        score += 4
        
    # Check for rhyming or vowel assonance across words
    rhymes = [p[1] for p in phonetics if p[1]]
    if len(rhymes) > 1 and len(set(rhymes)) < len(rhymes):
        score += 5

    vowels = [p[2] for p in phonetics if p[2]]
    if len(vowels) > 1 and len(set(vowels)) < len(vowels):
        score += 3

    return score

def build_palindrome_pool():
    pool = []

    # 1. Collect all single-word palindromes (used strictly as center fillings)
    single_palindromes = [w for w in VOCAB if len(w) >= 2 and w == w[::-1]]

    # 2. Collect long or multisyllabic single-word palindromes (e.g. "redivider", "detartrated", "rotator")
    long_singles = [w for w in single_palindromes if len(w) >= 6 or len(get_word_phonetics(w)[0]) >= 3]
    pool.extend(long_singles)

    # 3. Asymmetric spacing & complex multi-word phrases
    known_asymmetric = [
        "race car", "taco cat", "red rum sir is murder", "no lemon no melon", 
        "borrow or rob", "was it a car or a cat i saw", "never odd or even"
    ]
    dynamic_asymmetric = find_asymmetric_palindromes()
    pool.extend(known_asymmetric)
    pool.extend(dynamic_asymmetric)

    # 4. Reversible word pairs MANDATORY 3-Word Sandwiches (e.g., "loot xanax tool", "ed pop de")
    rev_map = {}
    for w in VOCAB:
        rev = w[::-1]
        if w != rev and is_valid_word(rev) and len(w) >= 2:
            rev_map[w] = rev

    rev_words = list(rev_map.keys())

    # Build rich 3-word sandwiches: [reversible_word] + [palindromic_filling] + [reverse_word]
    sandwich_candidates = []
    for w1 in rev_words:
        w2 = rev_map[w1]
        if single_palindromes:
            # Sample central fillings to create aesthetic sandwiches
            sample_centers = random.sample(single_palindromes, min(5, len(single_palindromes)))
            for mid in sample_centers:
                phrase = f"{w1} {mid} {w2}"
                score = score_phrase_aesthetics(phrase)
                sandwich_candidates.append((score, phrase))

    # Prioritize sandwiches with high rhyme/alliteration scores
    sandwich_candidates.sort(key=lambda x: x[0], reverse=True)
    top_sandwiches = [phrase for _, phrase in sandwich_candidates]
    pool.extend(top_sandwiches)

    return list(set(pool))

ALL_PALINDROMES = build_palindrome_pool()

def find_prosodic_companions(seed_phrase, count=5):
    global USED_PROSODIC_MATCHES
    target_stress, target_rhyme, target_vowels, target_onset = analyze_phrase(seed_phrase)
    if not target_stress:
        return []

    candidates = CADENCE_INDEX.get(target_stress, [])
    scored_matches = []
    seed_words = set(seed_phrase.lower().split())

    for cand in candidates:
        word = cand['word']
        if word in seed_words:
            continue
        
        score = 1
        if cand['rhyme'] == target_rhyme:
            score += 5  
        if cand['nucleus'] in target_vowels:
            score += 3  
        if cand['onset'] == target_onset:
            score += 2  

        if word in USED_PROSODIC_MATCHES:
            score -= 10

        scored_matches.append((score, word))

    scored_matches.sort(key=lambda x: x[0], reverse=True)
    
    selected = []
    for _, word in scored_matches:
        if len(selected) >= count:
            break
        
        stresses, rhyme, _, _ = get_word_phonetics(word)
        selected.append({
            "word": word,
            "stress": stresses or "N/A",
            "rhyme": rhyme or "N/A"
        })
        USED_PROSODIC_MATCHES.add(word)

    if len(USED_PROSODIC_MATCHES) > 1500:
        USED_PROSODIC_MATCHES.clear()

    return selected

def get_next_palindrome_block():
    global USED_PALINDROMES, ALL_PALINDROMES
    
    available = [p for p in ALL_PALINDROMES if p not in USED_PALINDROMES]
    if not available:
        USED_PALINDROMES.clear()
        available = list(ALL_PALINDROMES)

    chosen = random.choice(available)
    USED_PALINDROMES.add(chosen)

    p_stress, p_rhyme, _, _ = analyze_phrase(chosen)
    prosodic_count = random.randint(3, 7)
    companions = find_prosodic_companions(chosen, count=prosodic_count)

    return {
        "palindrome": chosen,
        "stress": p_stress or "N/A",
        "rhyme": p_rhyme or "N/A",
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

# --- 5. FLASK INTERFACE & CONTROLLED PLAYBACK ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Prosodic Palindrome Stream</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body { font-family: sans-serif; margin: 0; padding: 20px; background: #0f0f11; color: #e0e0e0; text-align: center; }
        .container { max-width: 650px; margin: 0 auto; padding-top: 20px; }
        .start-btn { 
            background: #2e7d32; color: white; border: none; padding: 18px 36px; 
            font-size: 1.4rem; border-radius: 50px; cursor: pointer; width: 100%;
            box-shadow: 0 4px 15px rgba(0,0,0,0.5); margin-bottom: 20px;
        }
        .start-btn:active { background: #1b5e20; }
        .controls { display: flex; justify-content: space-between; align-items: center; background: #18181c; padding: 12px 20px; border-radius: 30px; margin-bottom: 20px; border: 1px solid #2a2a32; }
        .toggle-btn { background: #37474f; color: #fff; border: none; padding: 8px 16px; border-radius: 20px; cursor: pointer; font-size: 0.9rem; }
        .toggle-btn.active { background: #0288d1; }
        .status { font-size: 1rem; color: #888; margin: 0; }
        
        .block-card { background: #18181c; border-radius: 12px; padding: 20px; border: 1px solid #2a2a32; }
        .pal-heading { font-size: 2.2rem; font-weight: bold; color: #81c784; margin: 10px 0; letter-spacing: 1px; }
        .phonetic-tag { font-size: 0.85rem; color: #90caf9; background: #1e293b; padding: 4px 10px; border-radius: 12px; display: inline-block; margin-bottom: 10px; }
        .playing-indicator { font-size: 0.85rem; text-transform: uppercase; letter-spacing: 1.5px; color: #ffd54f; }
        
        .matches-list { list-style: none; padding: 0; margin-top: 20px; text-align: left; }
        .match-item { 
            background: #222228; padding: 12px 16px; margin: 8px 0; border-radius: 8px; 
            display: flex; justify-content: space-between; align-items: center;
            font-size: 1.1rem; color: #b0bec5; transition: all 0.3s ease;
        }
        .match-item.active { background: #2e7d32; color: #ffffff; font-weight: bold; padding-left: 20px; }
        .meta-info { font-size: 0.8rem; opacity: 0.8; font-family: monospace; }
    </style>
</head>
<body>
    <div class="container">
        <h2>Cadence-Matched Palindrome Stream</h2>
        
        <div class="controls">
            <p class="status" id="status-text">Ready to initialize stream</p>
            <button class="toggle-btn active" id="recite-toggle" onclick="toggleRecitation()">Echo Recitation: ON</button>
        </div>
        
        <button class="start-btn" id="main-btn" onclick="startStream()">▶ Start Audio Stream</button>
        
        <div class="block-card" id="display-card" style="display: none;">
            <div class="playing-indicator" id="current-stage">Initializing</div>
            <div class="pal-heading" id="core-palindrome">---</div>
            <div class="phonetic-tag" id="core-phonetics">Stress: - | Rhyme: -</div>
            
            <ul class="matches-list" id="matches-container"></ul>
        </div>
    </div>

    <script>
        let reciteCompanions = true;

        function toggleRecitation() {
            reciteCompanions = !reciteCompanions;
            const btn = document.getElementById('recite-toggle');
            btn.innerText = `Echo Recitation: ${reciteCompanions ? 'ON' : 'OFF'}`;
            btn.classList.toggle('active', reciteCompanions);
        }

        async function playAudio(url) {
            return new Promise((resolve) => {
                const audio = new Audio(url);
                audio.onended = resolve;
                audio.onerror = resolve;
                audio.play();
            });
        }

        async function executePhraseBlock(phrase, stageText) {
            document.getElementById('current-stage').innerText = stageText;

            const ttsUrl = `/tts?text=${encodeURIComponent(phrase)}`;
            const morseUrl = `/morse?text=${encodeURIComponent(phrase)}`;

            await playAudio(ttsUrl);
            await new Promise(r => setTimeout(r, 200));

            await playAudio(morseUrl);
            await new Promise(r => setTimeout(r, 200));

            await playAudio(ttsUrl);
            await new Promise(r => setTimeout(r, 350));
        }

        async function startStream() {
            document.getElementById('main-btn').style.display = 'none';
            document.getElementById('display-card').style.display = 'block';

            while (true) {
                document.getElementById('status-text').innerText = 'Fetching sequence block...';
                const res = await fetch('/generate');
                const block = await res.json();

                const pal = block.palindrome;
                const matches = block.prosodic_matches;

                document.getElementById('core-palindrome').innerText = pal;
                document.getElementById('core-phonetics').innerText = `Stress: ${block.stress} | Rhyme: [${block.rhyme}]`;
                
                const listEl = document.getElementById('matches-container');
                listEl.innerHTML = '';
                
                matches.forEach((m, idx) => {
                    const li = document.createElement('li');
                    li.className = 'match-item';
                    li.id = `match-${idx}`;
                    li.innerHTML = `
                        <span>${idx + 1}. ${m.word}</span>
                        <span class="meta-info">S:${m.stress} | [${m.rhyme}]</span>
                    `;
                    listEl.appendChild(li);
                });

                document.getElementById('status-text').innerText = 'Playing Sequence Block';

                await executePhraseBlock(pal, "★ Core Palindrome Anchor");

                if (reciteCompanions) {
                    for (let i = 0; i < matches.length; i++) {
                        const matchItem = document.getElementById(`match-${i}`);
                        if (matchItem) matchItem.classList.add('active');

                        await executePhraseBlock(matches[i].word, `☊ Prosodic Echo (${i+1}/${matches.length})`);
                        
                        if (matchItem) matchItem.classList.remove('active');

                        await executePhraseBlock(pal, "★ Core Palindrome Anchor");
                    }
                } else {
                    await new Promise(r => setTimeout(r, 1200));
                }
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
