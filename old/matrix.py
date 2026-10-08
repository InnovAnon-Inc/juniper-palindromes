#!/usr/bin/env python3
import cmath
import math
import os
import re
from collections import defaultdict, Counter
import nltk
import pronouncing
from flask import Flask, jsonify, render_template_string, request

nltk.download("wordnet", quiet=True)
nltk.download("words", quiet=True)

app = Flask(__name__)

# ==============================================================================
# 1. METRICAL FEET DICTIONARY
# ==============================================================================
METRICAL_FEET = {
    "01": "Iamb", "10": "Trochee", "11": "Spondee", "00": "Pyrrhic",
    "100": "Dactyl", "001": "Anapest", "010": "Amphibrach", "101": "Amphimacer",
    "110": "Antibacchius", "011": "Bacchius", "111": "Molossus", "000": "Tribrach",
    "1000": "Primus Paeon", "0100": "Secundus Paeon", "0010": "Tertius Paeon",
    "0001": "Quartus Paeon", "1100": "Major Ionic", "0011": "Minor Ionic",
    "1001": "Choriamb", "0110": "Antispast", "1010": "Ditrochee", "0101": "Diiamb"
}

def identify_metrical_foot(stress_pattern):
    normalized = "".join(["1" if c == "1" else "0" for c in stress_pattern])
    return METRICAL_FEET.get(normalized, "Custom Foot")


# ==============================================================================
# 2. PHONETIC & RHYME ENGINE
# ==============================================================================
class UnifiedPhonicsEngine:
    def __init__(self, max_word_length=20):
        self.max_word_length = max_word_length
        self.vowel_phonemes = {
            "AA", "AE", "AH", "AO", "AW", "AY", "EH", "ER", 
            "EY", "IH", "IY", "OW", "OY", "UH", "UW"
        }
        self.word_profiles = {}
        self.rhyme_matrix = defaultdict(lambda: defaultdict(list))
        self._build_indices()

    def _clean_word(self, word):
        return re.sub(r"[^a-z]", "", word.lower())

    def _extract_phonetic_parts(self, phones_str):
        tokens = phones_str.split()
        stresses = "".join([char for token in tokens for char in token if char.isdigit()])

        stressed_idx = -1
        for i, t in enumerate(tokens):
            clean_p = "".join([c for c in t if not c.isdigit()])
            if clean_p in self.vowel_phonemes:
                if "1" in t or stressed_idx == -1:
                    stressed_idx = i
                    if "1" in t:
                        break

        if stressed_idx == -1:
            return None

        rhyme_tokens = ["".join([c for c in t if not c.isdigit()]) for t in tokens[stressed_idx:]]
        rhyme_tail = "_".join(rhyme_tokens)
        binary_stress = "".join(["1" if char == "1" else "0" for char in stresses])

        return {
            "stress": binary_stress,
            "raw_stress": stresses,
            "syllables": len(stresses),
            "rhyme_tail": rhyme_tail,
        }

    def _build_indices(self):
        all_words = pronouncing.search(".*")
        for word in all_words:
            clean = self._clean_word(word)
            if not clean or len(clean) > self.max_word_length or clean in self.word_profiles:
                continue

            phones_list = pronouncing.phones_for_word(clean)
            if not phones_list:
                continue

            parts = self._extract_phonetic_parts(phones_list[0])
            if not parts:
                continue

            self.word_profiles[clean] = parts
            self.rhyme_matrix[parts["stress"]][parts["rhyme_tail"]].append(clean)

    def analyze_phrase(self, text):
        words = re.findall(r"\b[a-zA-Z]+\b", text.lower())
        results = []
        full_stress = ""

        for w in words:
            prof = self.word_profiles.get(w)
            if not prof:
                phones = pronouncing.phones_for_word(w)
                if phones:
                    prof = self._extract_phonetic_parts(phones[0])

            if prof:
                results.append({
                    "word": w,
                    "stress": prof["stress"],
                    "syllables": prof["syllables"],
                    "rhyme_tail": prof["rhyme_tail"],
                    "foot": identify_metrical_foot(prof["stress"]),
                })
                full_stress += prof["stress"]
            else:
                results.append({
                    "word": w,
                    "stress": "?",
                    "syllables": 1,
                    "rhyme_tail": "unknown",
                    "foot": "Unknown",
                })

        return {"tokens": results, "full_stress_pattern": full_stress}

    def get_words_for_selection(self, stress_pattern, line_context_words=None, tail_index=0):
        if stress_pattern not in self.rhyme_matrix:
            return {"tails": [], "current_tail": None, "words": []}

        available_tails = list(self.rhyme_matrix[stress_pattern].keys())
        if not available_tails:
            return {"tails": [], "current_tail": None, "words": []}

        # Priority 1: Extract rhyme tails from existing line/stanza words
        prioritized_tails = []
        if line_context_words:
            pref_tails = []
            for pw in line_context_words:
                clean_pw = self._clean_word(pw)
                prof = self.word_profiles.get(clean_pw)
                if prof and prof["rhyme_tail"] in available_tails:
                    pref_tails.append(prof["rhyme_tail"])
            
            tail_counts = Counter(pref_tails)
            prioritized_tails = [t for t, _ in tail_counts.most_common()]

        for t in sorted(available_tails):
            if t not in prioritized_tails:
                prioritized_tails.append(t)

        selected_tail = prioritized_tails[tail_index % len(prioritized_tails)]
        word_list = self.rhyme_matrix[stress_pattern][selected_tail]

        return {
            "tails_count": len(prioritized_tails),
            "current_tail_index": tail_index % len(prioritized_tails),
            "current_tail": selected_tail,
            "metrical_foot": identify_metrical_foot(stress_pattern),
            "words": sorted(list(set(word_list))),
            "is_prioritized": len(prioritized_tails) > 0 and selected_tail in prioritized_tails[:len(line_context_words or [])]
        }


phonics_engine = UnifiedPhonicsEngine()

# ==============================================================================
# 3. POLYGON & RHYTHM ENGINE
# ==============================================================================
def bjorklund_euclidean(steps: int, pulses: int) -> list[int]:
    if pulses <= 0: return [0] * steps
    if pulses >= steps: return [1] * steps
    pattern = [[1] for _ in range(pulses)]
    remainder = [[0] for _ in range(steps - pulses)]
    while len(remainder) > 1:
        count = min(len(pattern), len(remainder))
        for i in range(count):
            pattern[i].extend(remainder.pop(0))
    pattern.extend(remainder)
    return [bit for group in pattern for bit in group]

def get_centroid(pattern: list[int], N: int) -> tuple[float, float]:
    if not pattern or sum(pattern) == 0: return 0.0, 0.0
    total_vector = 0j
    for i, active in enumerate(pattern):
        if active:
            angle = 2 * math.pi * i / N
            total_vector += cmath.exp(1j * angle)
    center = total_vector / sum(pattern)
    return center.real, center.imag

def analyze_polygon(pattern: list[int], N: int, tol: float = 1e-5) -> dict:
    cx, cy = get_centroid(pattern, N)
    dist = math.hypot(cx, cy)
    is_c1 = dist < tol
    dft_zeros = sum(1 for k in range(1, N) if abs(sum(cmath.exp(-2j * math.pi * k * i / N) for i, b in enumerate(pattern) if b)) < tol)
    is_c2 = (dft_zeros > 0) and not is_c1
    return {
        "pattern_str": "".join(map(str, pattern)),
        "is_interesting": is_c1 or is_c2 or (sum(pattern) > 1 and N % sum(pattern) != 0),
        "type": "Cyclotomic" if (is_c1 or is_c2) else "Euclidean"
    }

def get_interesting_polygons(N: int) -> list[dict]:
    results, seen = [], set()
    for k in range(1, N):
        euc_pat = bjorklund_euclidean(N, k)
        key = tuple(euc_pat)
        if key not in seen:
            analysis = analyze_polygon(euc_pat, N)
            seen.add(key)
            results.append(analysis)
    return results

# ==============================================================================
# 4. FLASK ROUTES
# ==============================================================================
@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route("/api/polygons", methods=["GET"])
def api_polygons():
    n = int(request.args.get("n", 8))
    return jsonify({"n": n, "polygons": get_interesting_polygons(n)})

@app.route("/api/analyze_phrase", methods=["POST"])
def api_analyze_phrase():
    data = request.get_json() or {}
    return jsonify(phonics_engine.analyze_phrase(data.get("phrase", "")))

@app.route("/api/lookup_words", methods=["POST"])
def api_lookup_words():
    data = request.get_json() or {}
    return jsonify(phonics_engine.get_words_for_selection(
        stress_pattern=data.get("stress_pattern", ""),
        line_context_words=data.get("context_words", []),
        tail_index=int(data.get("tail_index", 0))
    ))

# ==============================================================================
# 5. UI TEMPLATE
# ==============================================================================
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Prosodic Matrix & Stanza Builder</title>
    <style>
        body { font-family: 'Segoe UI', monospace, sans-serif; background: #121214; color: #e0e0e0; margin: 0; padding: 20px; }
        h1, h2, h3 { color: #4db6ac; margin-top: 0; }
        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
        .card { background: #1e1e24; border-radius: 8px; padding: 20px; box-shadow: 0 4px 6px rgba(0,0,0,0.4); }
        .full-width { grid-column: span 2; }
        input, button, textarea { background: #2a2a32; border: 1px solid #444; color: #fff; padding: 8px 12px; border-radius: 4px; }
        button { background: #00897b; font-weight: bold; cursor: pointer; }
        button:hover { background: #00bfa5; }
        .button-secondary { background: #37474f; }
        .button-secondary:hover { background: #455a64; }
        .button-danger { background: #c62828; }
        .button-danger:hover { background: #e53935; }

        /* Element 3: Matrix Syllable Bar */
        .matrix-bar-container { display: flex; gap: 4px; margin: 15px 0; overflow-x: auto; padding: 10px; background: #18181c; border-radius: 6px; }
        .syllables-box { 
            flex: 1; min-width: 36px; height: 50px; display: flex; flex-direction: column; align-items: center; 
            justify-content: center; background: #2a2a32; border: 1px solid #444; border-radius: 4px; 
            cursor: pointer; user-select: none; transition: all 0.2s;
        }
        .syllables-box.selected { border-color: #ffd54f; background: #3d3b2a; }
        .syllables-box.stressed { color: #00e676; font-weight: bold; }
        .syllables-box.unstressed { color: #666; }
        .syllables-idx { font-size: 10px; color: #888; margin-top: 2px; }

        /* Element 4: Stanza Line Builder */
        .stanza-container { display: flex; flex-direction: column; gap: 10px; margin-top: 15px; }
        .line-row { display: flex; align-items: center; gap: 10px; background: #18181c; padding: 10px; border-radius: 6px; border: 1px solid #333; }
        .line-row.active-line { border-color: #00bfa5; background: #1f2826; }
        .line-number { font-weight: bold; color: #4db6ac; width: 60px; font-size: 13px; }
        
        .line-tokens-container { flex-grow: 1; display: flex; flex-wrap: wrap; gap: 6px; min-height: 36px; align-items: center; background: #121214; padding: 6px; border-radius: 4px; }
        .token-chip { display: flex; align-items: center; gap: 6px; background: #2a2a35; border: 1px solid #444; padding: 4px 8px; border-radius: 4px; font-family: monospace; }
        .token-chip .stress-tag { font-size: 10px; color: #00e676; background: #18281e; padding: 1px 4px; border-radius: 2px; }
        .token-chip .remove-btn { cursor: pointer; color: #ff5252; font-weight: bold; margin-left: 4px; }

        .word-chip { display: inline-block; background: #33333d; border-left: 3px solid #00bfa5; padding: 6px 10px; margin: 3px; border-radius: 3px; font-size: 13px; cursor: pointer; }
        .word-chip:hover { background: #004d40; color: #fff; }
        .word-chip.prioritized { border-left-color: #ffd54f; background: #3d3b2a; }
        .poly-item { padding: 6px; background: #2a2a32; margin-bottom: 4px; cursor: pointer; border-radius: 4px; }
        .poly-item:hover { background: #383842; }
    </style>
</head>
<body>

    <h1>Prosodic Matrix & Multi-Line Stanza Builder</h1>

    <div class="grid">
        <!-- 1. POLYGON STRESS GENERATOR -->
        <div class="card">
            <h2>1. Rhythm & Polygon Generator</h2>
            <div style="display: flex; gap: 10px; align-items: center; margin-bottom: 10px;">
                <label>N-gon Syllables:</label>
                <input type="number" id="n-input" value="8" min="3" max="16" style="width: 50px;">
                <button onclick="fetchPolygons()">Find Rhythms</button>
            </div>
            <div id="polygon-list" style="max-height: 120px; overflow-y: auto;"></div>
            <div style="margin-top: 10px;">
                <label>Repeat:</label>
                <input type="number" id="repeat-input" value="2" min="1" max="4" style="width: 50px;">
                <button onclick="applyPolygonVerse()">Apply Master Rhythm</button>
            </div>
        </div>

        <!-- 2. PHRASE DECONSTRUCTION -->
        <div class="card">
            <h2>2. Deconstruct Phrase</h2>
            <textarea id="phrase-input" style="width: 100%; height: 50px;" placeholder="Type phrase to extract metrical stress..."></textarea>
            <button onclick="analyzePhrase()" style="margin-top: 8px;">Load Matrix Pattern</button>
            <div id="phrase-tokens" style="margin-top: 8px;"></div>
        </div>

        <!-- 3. ELEMENT 3: MASTER PROSODIC MATRIX HEADER -->
        <div class="card full-width">
            <h2>3. Master Prosodic Matrix</h2>
            <p style="font-size: 12px; color: #aaa;">Click individual or contiguous syllable blocks below to select stress windows for word lookup.</p>
            
            <div id="matrix-container" class="matrix-bar-container"></div>
            
            <div style="display: flex; gap: 15px; align-items: center; background: #18181c; padding: 10px; border-radius: 6px;">
                <div>Pattern: <strong id="selected-pattern-display" style="color: #ffd54f;">None</strong></div>
                <div>Foot: <span id="foot-display" style="color: #00bfa5;">-</span></div>
                <div>Rhyme Tail: <span id="tail-idx-display">0</span></div>
                <button onclick="cycleTail(1)">Next Rhyme Tail ➔</button>
            </div>

            <h3 style="margin-top: 15px;">Word Recommendations (Clicking spans multi-syllable foot)</h3>
            <div id="word-list-container">
                <p style="color: #666;">Select syllables above to load vocabulary options matching the prosodic structure.</p>
            </div>
        </div>

        <!-- 4. ELEMENT 4: DECOUPLED MULTI-LINE STANZA BUILDER -->
        <div class="card full-width">
            <div style="display: flex; justify-content: space-between; align-items: center;">
                <h2>4. Multi-Line Composition Canvas</h2>
                <button onclick="addNewLine()">+ Add New Line</button>
            </div>
            <p style="font-size: 12px; color: #aaa;">Target a line. Inserted words will auto-calculate their syllable spans, highlight matrix header positions, and auto-prioritize column rhymes.</p>
            
            <div id="stanza-container" class="stanza-container"></div>
        </div>
    </div>

    <script>
        let currentVersePattern = "1001001010010010";
        let selectedIndices = [];
        let currentTailIndex = 0;
        let selectedPolygonPattern = "";

        // Multi-line Stanza Builder State (Array of Word Token Objects per line)
        // Token format: { word: "probably", stress: "100", syllables: 3 }
        let stanzaLines = [[]];
        let activeLineIndex = 0;

        async function fetchPolygons() {
            const n = document.getElementById('n-input').value;
            const res = await fetch(`/api/polygons?n=${n}`);
            const data = await res.json();
            const list = document.getElementById('polygon-list');
            list.innerHTML = '';
            
            data.polygons.forEach(p => {
                const el = document.createElement('div');
                el.className = 'poly-item';
                el.innerHTML = `<strong>[${p.pattern_str}]</strong> <span style="font-size: 11px; color: #888;">${p.type}</span>`;
                el.onclick = () => { selectedPolygonPattern = p.pattern_str; alert('Selected pattern: ' + p.pattern_str); };
                list.appendChild(el);
            });
            if(data.polygons.length > 0) selectedPolygonPattern = data.polygons[0].pattern_str;
        }

        function applyPolygonVerse() {
            if(!selectedPolygonPattern) return;
            const reps = parseInt(document.getElementById('repeat-input').value);
            currentVersePattern = selectedPolygonPattern.repeat(reps);
            selectedIndices = [];
            renderMatrix();
            autoSelectNextSpan();
        }

        function renderMatrix() {
            const container = document.getElementById('matrix-container');
            container.innerHTML = '';
            
            currentVersePattern.split('').forEach((bit, idx) => {
                const box = document.createElement('div');
                box.className = `syllables-box ${bit === '1' ? 'stressed' : 'unstressed'} ${selectedIndices.includes(idx) ? 'selected' : ''}`;
                box.innerHTML = `<div>${bit}</div><div class="syllables-idx">${idx + 1}</div>`;
                box.onclick = () => toggleSelectBit(idx);
                container.appendChild(box);
            });
            updateSelectionAnalysis();
        }

        function toggleSelectBit(idx) {
            if (selectedIndices.includes(idx)) {
                selectedIndices = selectedIndices.filter(i => i !== idx);
            } else {
                selectedIndices.push(idx);
            }
            selectedIndices.sort((a, b) => a - b);
            currentTailIndex = 0;
            renderMatrix();
        }

        function getActiveLineSyllableCount() {
            const tokens = stanzaLines[activeLineIndex] || [];
            return tokens.reduce((sum, t) => sum + (t.syllables || 1), 0);
        }

        function autoSelectNextSpan(length = 1) {
            const currentSyls = getActiveLineSyllableCount();
            selectedIndices = [];
            for (let i = 0; i < length; i++) {
                if (currentSyls + i < currentVersePattern.length) {
                    selectedIndices.push(currentSyls + i);
                }
            }
            renderMatrix();
        }

        async function updateSelectionAnalysis() {
            if(selectedIndices.length === 0) {
                document.getElementById('selected-pattern-display').innerText = "None";
                document.getElementById('foot-display').innerText = "-";
                document.getElementById('word-list-container').innerHTML = '<p style="color: #666;">Select syllables above.</p>';
                return;
            }

            const patternStr = selectedIndices.map(i => currentVersePattern[i]).join('');
            document.getElementById('selected-pattern-display').innerText = patternStr;

            // Extract existing stanza words to auto-prioritize column rhymes
            const contextWords = [];
            stanzaLines.forEach(line => {
                line.forEach(t => { if(t.word) contextWords.push(t.word); });
            });

            const res = await fetch('/api/lookup_words', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ 
                    stress_pattern: patternStr, 
                    context_words: contextWords,
                    tail_index: currentTailIndex 
                })
            });
            const data = await res.json();
            
            document.getElementById('foot-display').innerText = data.metrical_foot || "Custom";
            document.getElementById('tail-idx-display').innerText = `${data.current_tail_index + 1} / ${data.tails_count || 0} (${data.current_tail || 'None'})`;

            const container = document.getElementById('word-list-container');
            if(!data.words || data.words.length === 0) {
                container.innerHTML = '<p style="color: #888;">No exact matches for this foot. Cycle tails or shift selection.</p>';
                return;
            }

            container.innerHTML = '';
            data.words.forEach(w => {
                const chip = document.createElement('div');
                chip.className = `word-chip ${data.is_prioritized ? 'prioritized' : ''}`;
                chip.innerText = w;
                chip.onclick = () => insertWordToStanza(w, patternStr);
                container.appendChild(chip);
            });
        }

        async function insertWordToStanza(word, stress) {
            const syls = stress.length;
            const token = { word: word, stress: stress, syllables: syls };

            if (!stanzaLines[activeLineIndex]) stanzaLines[activeLineIndex] = [];
            stanzaLines[activeLineIndex].push(token);

            renderStanzaBuilder();
            autoSelectNextSpan();
        }

        /* Stanza Canvas Builder UI */
        function renderStanzaBuilder() {
            const container = document.getElementById('stanza-container');
            container.innerHTML = '';

            stanzaLines.forEach((lineTokens, idx) => {
                const row = document.createElement('div');
                row.className = `line-row ${idx === activeLineIndex ? 'active-line' : ''}`;

                let tokensHTML = '';
                lineTokens.forEach((t, tIdx) => {
                    tokensHTML += `
                        <div class="token-chip">
                            <span>${t.word}</span>
                            <span class="stress-tag">${t.stress}</span>
                            <span class="remove-btn" onclick="removeToken(${idx}, ${tIdx})">✕</span>
                        </div>
                    `;
                });

                row.innerHTML = `
                    <div class="line-number">Line ${idx + 1}</div>
                    <div class="line-tokens-container" onclick="setActiveLine(${idx})">
                        ${tokensHTML || '<span style="color:#555; font-size:12px;">Click target button to fill this line...</span>'}
                    </div>
                    <div style="display:flex; gap:6px;">
                        <button class="${idx === activeLineIndex ? '' : 'button-secondary'}" onclick="setActiveLine(${idx})">
                            ${idx === activeLineIndex ? 'Targeted' : 'Target'}
                        </button>
                        <button class="button-danger" onclick="deleteLine(${idx})">✕</button>
                    </div>
                `;
                container.appendChild(row);
            });
        }

        function removeToken(lineIdx, tokenIdx) {
            stanzaLines[lineIdx].splice(tokenIdx, 1);
            renderStanzaBuilder();
            autoSelectNextSpan();
        }

        function setActiveLine(idx) {
            activeLineIndex = idx;
            renderStanzaBuilder();
            autoSelectNextSpan();
        }

        function addNewLine() {
            stanzaLines.push([]);
            activeLineIndex = stanzaLines.length - 1;
            renderStanzaBuilder();
            autoSelectNextSpan();
        }

        function deleteLine(idx) {
            stanzaLines.splice(idx, 1);
            if (stanzaLines.length === 0) stanzaLines = [[]];
            activeLineIndex = Math.max(0, stanzaLines.length - 1);
            renderStanzaBuilder();
            autoSelectNextSpan();
        }

        function cycleTail(step) {
            currentTailIndex += step;
            updateSelectionAnalysis();
        }

        async function analyzePhrase() {
            const phrase = document.getElementById('phrase-input').value;
            const res = await fetch('/api/analyze_phrase', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ phrase: phrase })
            });
            const data = await res.json();
            
            if(data.full_stress_pattern) {
                currentVersePattern = data.full_stress_pattern;
                stanzaLines[activeLineIndex] = data.tokens.map(t => ({
                    word: t.word,
                    stress: t.stress,
                    syllables: t.syllables || t.stress.length
                }));
                selectedIndices = [];
                renderMatrix();
                renderStanzaBuilder();
                autoSelectNextSpan();
            }
        }

        fetchPolygons();
        renderMatrix();
        renderStanzaBuilder();
        autoSelectNextSpan();
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    print("Running Prosodic Matrix App on http://0.0.0.0:5009")
    app.run(host="0.0.0.0", port=5009, debug=True)
