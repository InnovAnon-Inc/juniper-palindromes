import pytest
from juniper_palindromes.palindromes import (
    VOCAB_SET,
    calculate_entropy_fudge,
    edit_distance,
    extract_structural_candidates,
    generate_target_palindrome,
    get_fuzzy_matches,
    get_palindrome_fudge,
    is_phrase_valid,
    process_dictionary_word,
)


class TestPalindromesCore:
    """Core algorithmic unit tests for distance metrics and phrase validation."""

    def test_edit_distance(self):
        assert edit_distance("kayak", "kayak") == 0
        assert edit_distance("kitten", "sitting") == 3
        assert edit_distance("", "abc") == 3

    def test_get_palindrome_fudge(self):
        assert get_palindrome_fudge("racecar") == 0
        assert get_palindrome_fudge("A man, a plan, a canal: Panama!") == 0
        assert get_palindrome_fudge("hello world") > 0

    def test_phrase_validity(self):
        valid_sample = "a man a plan"
        invalid_sample = "xzqvzx nonexistantword123"
        assert is_phrase_valid(valid_sample) is True
        assert is_phrase_valid(invalid_sample) is False


class TestFuzzyMatchingAndCandidates:
    """Tests prefix tree search, structural extraction, and fuzzy fallback mechanisms."""

    def test_fuzzy_matches_exact_prefix(self):
        matches = get_fuzzy_matches("pala", max_dist=1, max_candidates=10)
        assert len(matches) > 0
        assert all(m.startswith("pala") for m in matches if len(m) >= 4)

    def test_fuzzy_matches_fallback(self):
        # Non-standard prefix to trigger distance-based matching
        matches = get_fuzzy_matches("xzy", max_dist=2, max_candidates=5)
        assert isinstance(matches, list)

    def test_extract_structural_candidates(self):
        candidates = extract_structural_candidates("banana")
        assert isinstance(candidates, list)
        assert "banana" not in candidates


class TestQualityAndRepetitionScoring:
    """Tests entropy scoring to ensure solutions avoid excess repetition and single-letter bloat."""

    def test_entropy_penalty_for_repetitive_words(self):
        score_diverse = calculate_entropy_fudge("race car driver")
        score_repetitive = calculate_entropy_fudge("car car car car")
        
        # Repetitive phrases should yield higher fudge/penalty scores
        assert score_repetitive > score_diverse

    def test_entropy_penalty_for_single_letters(self):
        score_normal = calculate_entropy_fudge("red rum sir is murder")
        score_single_letters = calculate_entropy_fudge("a b c d e f g")
        
        assert score_single_letters > score_normal


class TestPalindromeGeneration:
    """Integration tests verifying palindrome output generation across varied word lengths."""

    @pytest.mark.parametrize("target_word", [
        "radar",        # Short / exact palindrome
        "banana",       # Short non-palindrome
        "elephants",    # Medium length
        "internationally", # Long word
        "extraordinary",   # Long word
    ])
    def test_generate_target_palindrome_finds_results(self, target_word):
        if target_word not in VOCAB_SET:
            pytest.skip(f"Word '{target_word}' is not present in local vocabulary environment.")

        results = generate_target_palindrome(
            target_word=target_word,
            used_palindromes=[],
            max_results=5,
            max_fudge_ratio=2.0
        )

        assert isinstance(results, dict)
        assert len(results) > 0, f"Failed to find any palindrome solution for target: '{target_word}'"

        # Verify best output quality properties
        best_phrase, fudge_score = next(iter(results.items()))
        words = best_phrase.split()

        # Solution contains target or target reversal component
        assert target_word in best_phrase.lower() or target_word[::-1] in best_phrase.lower()
        
        # Vocabulary adherence
        assert is_phrase_valid(best_phrase)

        # Repetition control: at least 50% unique words for non-trivial phrases
        if len(words) > 2:
            unique_ratio = len(set(words)) / len(words)
            assert unique_ratio >= 0.5, f"Phrase '{best_phrase}' is excessively repetitive"

    def test_used_palindromes_deduplication(self):
        target = "banana"
        if target not in VOCAB_SET:
            pytest.skip("Target word not in vocabulary")

        first_pass = generate_target_palindrome(target, used_palindromes=[], max_results=1)
        assert len(first_pass) > 0
        
        used_phrase = next(iter(first_pass.keys()))
        second_pass = generate_target_palindrome(target, used_palindromes=[used_phrase], max_results=1)

        assert used_phrase not in second_pass

    def test_process_dictionary_word_structure(self):
        target = "level"
        if target not in VOCAB_SET:
            pytest.skip("Target word not in vocabulary")

        output = process_dictionary_word(target, used_palindromes=[])
        assert output is not None
        assert "target" in output
        assert "palindrome" in output
        assert "fudge" in output
        assert "word_weights" in output
        assert output["target"] == target
