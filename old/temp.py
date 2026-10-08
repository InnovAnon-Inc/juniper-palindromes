import random
import re
from collections import defaultdict

# Dynamic word usage frequency tracker
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

VOCAB = [
    w.lower() for w in set(wordnet.all_lemma_names()) 
    if is_valid_real_word(w)
]
VOCAB_SET = set(VOCAB)

# Trie implementation for efficient character-level cross-boundary lookup
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
        """Finds all complete words that start with prefix."""
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

# --- 3. ADVANCED ASYMMETRIC PALINDROME ENGINE ---
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

def get_palindrome_fudge(phrase):
    clean = re.sub(r'[^a-z]', '', phrase.lower())
    return edit_distance(clean, clean[::-1])

def is_phrase_valid(phrase):
    words = phrase.lower().split()
    return all(w in VOCAB_SET for w in words)

def letter_overlap_score(word1, word2):
    s1 = set(word1.lower())
    s2 = set(word2.lower())
    return len(s1.intersection(s2))


def get_word_weight(word, decay_rate=0.15):
    """
    Calculates a smooth, gradual weight reduction for used words.
    Prevents abrupt drop-offs while prioritizing lesser-used vocabulary.
    """
    print('get_word_weight')
    count = WORD_USAGE_COUNTS[word.lower()]
    return 1.0 / (1.0 + decay_rate * (count ** 0.75))

def record_phrase_usage(phrase):
    """Increments frequency counters for every word in a phrase."""
    print('record_phrase_usage')
    for word in phrase.lower().split():
        WORD_USAGE_COUNTS[word] += 1

#def generate_target_palindrome(target_word, max_results=20): # FIXME no candidates
#    """
#    Generates asymmetric, cross-boundary palindromes that explicitly contain
#    the target_word (e.g., target='radar', target='murder', target='lemon').
#    """
#    print('generate_target_palindrome')
#    target = target_word.lower()
#    if target not in VOCAB_SET:
#        return []
#
#    results = {}
#    target_rev = target[::-1]
#
#    # Strategy A: Target Word as Left Anchor
#    # Look for right-hand words starting with target_rev prefix
#    valid_prefixes = TRIE.get_valid_prefixes(target_rev[:3])
#    valid_prefixes = [w for w in valid_prefixes if w != target]
#
#    # Weight candidates by usage
#    prefix_weights = [get_word_weight(w) for w in valid_prefixes]
#
#    if valid_prefixes and sum(prefix_weights) > 0:
#        sampled_matches = random.choices(
#            valid_prefixes,
#            weights=prefix_weights,
#            k=min(15, len(valid_prefixes))
#        )
#    else:
#        sampled_matches = valid_prefixes[:15]
#
#    for w2 in sampled_matches:
#        # Case 1: w2 is longer than target (e.g., target='red', w2='murder')
#        if len(w2) > len(target):
#            rem_rev = w2[:-len(target)][::-1]
#            if rem_rev in VOCAB_SET:
#                phrase = f"{target} {rem_rev} {w2}"
#                if is_phrase_valid(phrase):
#                    results[phrase] = get_palindrome_fudge(phrase)
#
#            # Center bridge insertions weighted by frequency
#            centers = ["is", "or", "sir", "car", "no", "on", "a", "i"]
#            center_weights = [get_word_weight(c) for c in centers]
#            chosen_centers = random.choices(centers, weights=center_weights, k=3)
#
#            for center in chosen_centers:
#                phrase = f"{target} {center} {rem_rev} {w2}"
#                if is_phrase_valid(phrase):
#                    results[phrase] = get_palindrome_fudge(phrase)
#
#        # Case 2: target is longer than w2 (e.g., target='borrow', w2='rob')
#        elif len(target) > len(w2):
#            rem_rev = target[len(w2):][::-1]
#            if rem_rev in VOCAB_SET:
#                phrase = f"{target} {rem_rev} {w2}"
#                if is_phrase_valid(phrase):
#                    results[phrase] = get_palindrome_fudge(phrase)
#
#            centers = ["or", "on", "no", "is", "a"]
#            center_weights = [get_word_weight(c) for c in centers]
#            chosen_centers = random.choices(centers, weights=center_weights, k=3)
#
#            for center in chosen_centers:
#                phrase = f"{target} {rem_rev} {center} {w2}"
#                if is_phrase_valid(phrase):
#                    results[phrase] = get_palindrome_fudge(phrase)
#
#    # Strategy B: Target Word as Center Anchor
#    if target == target_rev: # If target is a natural palindrome itself (e.g. 'radar', 'level')
#        reversible_pairs = [w for w in VOCAB if w[::-1] in VOCAB_SET and w != w[::-1] and len(w) >= 3]
#        pair_weights = [get_word_weight(w) * get_word_weight(w[::-1]) for w in reversible_pairs]
#
#        if reversible_pairs and sum(pair_weights) > 0:
#            chosen_pairs = random.choices(reversible_pairs, weights=pair_weights, k=min(10, len(reversible_pairs)))
#            for w1 in chosen_pairs:
#                phrase = f"{w1} {target} {w1[::-1]}"
#                if is_phrase_valid(phrase):
#                    results[phrase] = get_palindrome_fudge(phrase)
#
#    # Sort results by lowest fudge score (closest to perfect structural palindrome)
#    sorted_results = dict(sorted(results.items(), key=lambda item: item[1]))
#    return sorted_results
def get_fuzzy_matches(prefix, max_dist=1, max_candidates=15):
    """
    Finds vocabulary words whose starting prefixes match 'prefix'
    within a small Levenshtein edit distance allowance.
    """
    matches = []
    prefix_len = len(prefix)

    # Fast path: exact prefix lookup first
    exact = TRIE.get_valid_prefixes(prefix)
    if exact:
        return exact[:max_candidates]

    # Fuzzy path: scan vocabulary for close prefix matches
    for w in VOCAB:
        if len(w) >= 2:
            sub = w[:prefix_len]
            if edit_distance(sub, prefix) <= max_dist:
                matches.append(w)
                if len(matches) >= max_candidates * 2:
                    break
    return matches

def generate_target_palindrome(target_word, max_results=10, max_fudge_ratio=0.6):
    """
    Generates pseudo-palindromes for ANY target word using adaptive
    prefix matching, dynamic fuzzy fallback, and fudge-threshold scaling.
    """
    target = target_word.lower()
    if target not in VOCAB_SET:
        return {}

    results = {}
    target_rev = target[::-1]

    # -------------------------------------------------------------
    # 1. Candidate Word Gathering (Strict -> Fuzzy Fallback)
    # -------------------------------------------------------------
    prefix_len = min(3, len(target_rev))
    search_prefix = target_rev[:prefix_len]

    # Tier 1: Exact Prefix Matches via Trie
    candidates = [w for w in TRIE.get_valid_prefixes(search_prefix) if w != target]

    # Tier 2: Reduced Prefix (2-char) fallback if no exact matches found
    if not candidates and prefix_len > 2:
        search_prefix = target_rev[:2]
        candidates = [w for w in TRIE.get_valid_prefixes(search_prefix) if w != target]

    # Tier 3: Levenshtein Fuzzy Search fallback if Trie yields nothing
    if not candidates:
        candidates = get_fuzzy_matches(target_rev[:3], max_dist=1)

    # Tier 4: Emergency Fallback — sample high-utility structural connectors
    if not candidates:
        candidates = ["is", "or", "no", "on", "sir", "car", "a", "i", "red", "raw", "war", "art"]

    # Weight candidate selection using word frequencies
    cand_weights = [get_word_weight(w) for w in candidates]
    sampled_matches = random.choices(
        candidates,
        weights=cand_weights if sum(cand_weights) > 0 else None,
        k=min(20, len(candidates))
    )

    # Bridge center options for creating asymmetric palindromic pivots
    center_pool = ["", "is", "or", "sir", "car", "no", "on", "a", "i", "so", "do", "to", "it"]

    # -------------------------------------------------------------
    # 2. Structural Construction & Fudge Evaluation
    # -------------------------------------------------------------
    for w2 in sampled_matches:
        # Generate candidate phrase structures
        phrase_candidates = [
            f"{target} {w2}",
            f"{target} {w2[::-1]} {w2}"
        ]

        # Add center-bridged permutations
        for c in center_pool:
            if c:
                phrase_candidates.append(f"{target} {c} {w2}")

            # Asymmetric remainder extensions
            if len(w2) > len(target):
                rem_rev = w2[:-len(target)][::-1]
                if rem_rev in VOCAB_SET:
                    phrase_candidates.append(f"{target} {c} {rem_rev} {w2}" if c else f"{target} {rem_rev} {w2}")
            elif len(target) > len(w2):
                rem_rev = target[len(w2):][::-1]
                if rem_rev in VOCAB_SET:
                    phrase_candidates.append(f"{target} {rem_rev} {c} {w2}" if c else f"{target} {rem_rev} {w2}")

        # Evaluate and filter phrases by fudge score ratio
        for phrase in phrase_candidates:
            clean_phrase = re.sub(r'[^a-z]', '', phrase.lower())
            if not clean_phrase:
                continue

            fudge = edit_distance(clean_phrase, clean_phrase[::-1])
            fudge_ratio = fudge / len(clean_phrase)

            # Allow higher absolute fudge scores for difficult/unbalanced target words
            if fudge_ratio <= max_fudge_ratio and is_phrase_valid(phrase):
                if phrase not in results or fudge < results[phrase]:
                    results[phrase] = fudge

    # -------------------------------------------------------------
    # 3. Last-Resort Guarantee (For tricky asymmetrical words)
    # -------------------------------------------------------------
    if not results:
        # Build an immediate mirrored construction with a center pivot
        fallback_phrase = f"{target} is {target_rev}"
        if is_phrase_valid(fallback_phrase):
            results[fallback_phrase] = get_palindrome_fudge(fallback_phrase)
        else:
            fallback_phrase = f"{target} {target_rev}"
            results[fallback_phrase] = get_palindrome_fudge(fallback_phrase)

    # Sort results by lowest fudge score (closest to standard structural palindrome)
    sorted_results = dict(sorted(results.items(), key=lambda item: item[1]))

    # Return top max_results candidates
    return dict(list(sorted_results.items())[:max_results])

def process_dictionary_word(word):
    """
    Helper function to iterate over the dictionary.
    Generates candidates, records word usage, and returns the top palindrome block.
    """
    print('process_dictionary_word')
    candidates = generate_target_palindrome(word, max_results=10)
    if not candidates:
        return None # FIXME no candidates

    # Pick top candidate with lowest fudge score
    best_phrase = list(candidates.keys())[0]

    # Increment word counts gradually
    record_phrase_usage(best_phrase)

    return {
        "target": word,
        "palindrome": best_phrase,
        "fudge": candidates[best_phrase],
        "word_weights": {w: round(get_word_weight(w), 3) for w in best_phrase.split()}
    }











