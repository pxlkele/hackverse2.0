"""
An answer must be written in the language it claims to be in.

_misstated_money guards the figures, and a half-translated answer passes it
cleanly because every figure in it is correct. What reached the phone was
Bengali or Devanagari sentence frames wrapped around verbatim English benefit
text, drifting into romanised Hindi part way through. Fresh generations measure
100% native script, so this is a cache problem, not a prompt problem: the bad
entries were written in earlier sessions and served from disk ever since.

The worst of them were English *fallbacks* that had been deliberately cached —
one transient failure to state money correctly, and that key answered in
English permanently.
"""

from __future__ import annotations

from services.api.core import narrate


class TestNativeRatio:
    def test_fully_native_scores_one(self):
        assert narrate._native_ratio("आप आज पात्र हैं", "hi") == 1.0
        assert narrate._native_ratio("আপনি আজ যোগ্য", "bn") == 1.0

    def test_scheme_names_are_not_counted_against_it(self):
        """KEEP_VERBATIM brands are meant to stay in Latin."""
        text = "आप आज PMSBY और PM SVANidhi के लिए पात्र हैं"
        assert narrate._native_ratio(text, "hi") == 1.0

    def test_the_hinglish_that_prompted_this_is_rejected(self):
        """Verbatim from the cache: Devanagari frame, English body."""
        text = (
            "आप आज PMSBY के लिए पात्र हैं: Rs 2 lakh का accidental death ya "
            "disability cover Rs 20 per year ka premium, auto-debited bank ya "
            "post office account se."
        )
        assert narrate._native_ratio(text, "hi") < narrate.NATIVE_FLOOR

    def test_romanised_drift_is_rejected(self):
        assert narrate._native_ratio("Aap bas do step door hain", "hi") < narrate.NATIVE_FLOOR

    def test_a_bengali_answer_is_not_judged_against_devanagari(self):
        """Two languages, two scripts - one must not pass as the other."""
        bengali = "আপনি আজ যোগ্য"
        assert narrate._native_ratio(bengali, "bn") == 1.0
        assert narrate._native_ratio(bengali, "hi") == 0.0

    def test_english_is_never_policed(self):
        """English has no other script to be in."""
        assert narrate._native_ratio("You qualify today for PMSBY", "en") == 1.0

    def test_digits_and_punctuation_do_not_skew_it(self):
        assert narrate._native_ratio("२,००,००० ₹ — आप पात्र हैं!", "hi") == 1.0

    def test_institution_names_are_allowed_to_stay_latin(self):
        """
        A correct Bengali answer still says "Bank Mitra" and "Jan Dhan". These
        dragged good answers down to 67-73% and had them regenerated on every
        single request, because the first version of this check only knew about
        the four scheme brands.
        """
        text = (
            "যেকোনো ব্যাংক শাখা, ডাকঘর অথবা Bank Mitra তে জিরো-ব্যালান্স "
            "Jan Dhan সেভিং অ্যাকাউন্ট খুলুন।"
        )
        assert narrate._native_ratio(text, "bn") == 1.0

    def test_scheme_names_come_from_the_catalogue(self):
        """So the list cannot drift when schemes.yaml changes."""
        nouns = narrate._proper_nouns()
        assert "FSSAI Basic Registration" in nouns
        assert "PM SVANidhi" in nouns

    def test_longest_name_is_stripped_first(self):
        """
        "FSSAI Basic Registration" must go before bare "FSSAI", or the words
        "Basic Registration" survive and count as untranslated English.
        """
        text = "आप FSSAI Basic Registration के लिए पात्र हैं"
        assert narrate._native_ratio(text, "hi") == 1.0

    def test_ordinary_english_is_still_caught(self):
        """
        The `where` fields contain plain English too - "Any bank branch",
        "post office". Those must NOT be excused, or the check goes blind to
        the half-translated answers it exists to catch.
        """
        text = "আপনি যোগ্য: Open a zero-balance savings account at Any bank branch or post office."
        assert narrate._native_ratio(text, "bn") < narrate.NATIVE_FLOOR


class TestCacheIsNotTrusted:
    def test_a_stale_english_entry_is_rejected_and_regenerated(self, tmp_path, monkeypatch):
        """
        The reported bug: spoke Bengali, heard English. A cached English
        fallback must not be served as a Bengali answer.
        """
        monkeypatch.setattr(narrate, "CACHE_DIR", tmp_path)

        parts = ["You qualify today for PMSBY: 200000 rupees cover."]
        key = narrate._cache_key(parts, "bn")
        narrate._store(key, "You qualify today for PMSBY: 200000 rupees cover.")

        hit = narrate._cached(key)
        assert hit is not None, "the entry is on disk"
        assert not narrate._misstated_money(hit, parts), "money guard sees nothing wrong"
        # ...and yet it must not be served, because it is not Bengali.
        assert narrate._native_ratio(hit, "bn") < narrate.NATIVE_FLOOR

    def test_a_good_entry_still_serves_from_cache(self, tmp_path, monkeypatch):
        """The guard must not invalidate answers that are actually fine."""
        monkeypatch.setattr(narrate, "CACHE_DIR", tmp_path)

        parts = ["You qualify today for PMSBY: 200000 rupees cover."]
        key = narrate._cache_key(parts, "bn")
        good = "আপনি আজ PMSBY এর জন্য যোগ্য: 200000 টাকার কভার।"
        narrate._store(key, good)

        hit = narrate._cached(key)
        assert not narrate._misstated_money(hit, parts)
        assert narrate._native_ratio(hit, "bn") >= narrate.NATIVE_FLOOR
