"""Tests for constraint normalization (blueprint_chat._normalize_constraints).

Covers a 500 on POST /plan: "add egg bhurji and roti" made the LLM return
constraints as bare strings (["egg bhurji", "roti"]) instead of the documented
[{"dish_tag", "min_count"}], and `c["dish_tag"]` on a str raised
"TypeError: string indices must be integers".

The model is prompted for a schema but never bound to it, so every consumer of
model-authored constraints normalizes at the boundary.
"""
from blueprint_chat import _normalize_constraints as N


def _run(name, fn):
    try:
        fn()
        print(f"PASS {name}")
        return True
    except AssertionError as e:
        print(f"FAIL {name}: {e}")
        return False


def test_bare_strings_become_constraints():
    """The exact payload that crashed /plan."""
    assert N(["egg bhurji", "roti"]) == [
        {"dish_tag": "egg bhurji", "min_count": 1},
        {"dish_tag": "roti", "min_count": 1},
    ]


def test_correct_shape_passes_through():
    assert N([{"dish_tag": "paneer", "min_count": 10}]) == [
        {"dish_tag": "paneer", "min_count": 10}]


def test_single_string_is_wrapped():
    assert N("paneer") == [{"dish_tag": "paneer", "min_count": 1}]


def test_alternate_key_names():
    """Models improvise key names — accept the obvious synonyms."""
    assert N([{"tag": "roti", "count": 4}]) == [
        {"dish_tag": "roti", "min_count": 4}]
    assert N([{"dish": "paneer", "min": 3}]) == [
        {"dish_tag": "paneer", "min_count": 3}]


def test_string_count_coerced():
    assert N([{"dish_tag": "egg", "min_count": "3"}])[0]["min_count"] == 3


def test_bad_count_falls_back_to_one():
    for bad in (None, "", "lots", -4, 0):
        assert N([{"dish_tag": "egg", "min_count": bad}])[0]["min_count"] == 1


def test_junk_is_dropped_not_passed_through():
    """A dropped constraint is recoverable; a 500 is not."""
    assert N([None, "", {}, {"min_count": 2}, 42]) == []
    assert N(None) == []
    assert N([]) == []


def test_duplicates_collapse_case_insensitively():
    out = N([{"dish_tag": "egg"}, {"dish_tag": "EGG", "min_count": 5}])
    assert len(out) == 1


def test_sentence_tag_is_reduced_to_dishes():
    """The model returned dish_tag="include egg bhurji with roti" — a sentence
    matches no dish name, so the constraint could never be met. It is really
    two dishes."""
    assert N([{"dish_tag": "include egg bhurji with roti", "min_count": 1}]) == [
        {"dish_tag": "egg bhurji", "min_count": 1},
        {"dish_tag": "roti", "min_count": 1},
    ]


def test_multi_dish_tag_splits_and_keeps_count():
    out = N([{"dish_tag": "add some paneer and biryani", "min_count": 5}])
    assert out == [{"dish_tag": "paneer", "min_count": 5},
                   {"dish_tag": "biryani", "min_count": 5}]


def test_chatty_tag_keeps_only_the_dish():
    assert N([{"dish_tag": "i want atleast 8 egg bhurji", "min_count": 8}]) == [
        {"dish_tag": "egg bhurji", "min_count": 8}]


def test_all_stopwords_yields_nothing():
    assert N([{"dish_tag": "include with and the", "min_count": 2}]) == []


def test_tags_are_lowercased_and_trimmed():
    assert N([{"dish_tag": "  PANEER  ", "min_count": 2}]) == [
        {"dish_tag": "paneer", "min_count": 2}]


def test_adjust_adds_dishes_without_an_llm():
    """Gemini's free tier 429s routinely, and every caller falls back silently.
    An "add X and Y" tweak must still work when the LLM is unavailable, or the
    user is told "Updated your plan" while nothing changed."""
    import blueprint_chat as B
    base = {"budget": 14000, "appetite_level": "moderate", "veg_only": False}
    for msg, want in (
        ("add egg bhurji and roti not just egg bhurji", ["egg bhurji", "roti"]),
        ("add paneer", ["paneer"]),
        ("more chicken please", ["chicken"]),
        ("include dal and rice", ["dal", "rice"]),
    ):
        got = B._extract_added_dishes(msg)
        assert [c["dish_tag"] for c in got] == want, f"{msg} -> {got}"
    # and the merge keeps them on the blueprint
    bp, reply = B.adjust(dict(base), "add paneer")
    assert [c["dish_tag"] for c in bp["constraints"]] == ["paneer"]
    assert "paneer" in reply.lower()


def test_add_stops_at_negation():
    """"add roti, not just egg" must not swallow the negated clause."""
    import blueprint_chat as B
    got = [c["dish_tag"] for c in B._extract_added_dishes("add roti not just egg")]
    assert "egg" not in got, got


def test_plan_endpoint_survives_raw_strings():
    """End-to-end: raw strings must reach the optimizer as valid Constraints."""
    from optimizer import Constraint
    cons = [Constraint(c["dish_tag"], c["min_count"])
            for c in N(["egg bhurji", "roti"])]
    assert [c.dish_tag for c in cons] == ["egg bhurji", "roti"]


if __name__ == "__main__":
    tests = [(k, v) for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    passed = sum(_run(name, fn) for name, fn in tests)
    print(f"\n{passed}/{len(tests)} passed")
    raise SystemExit(0 if passed == len(tests) else 1)
