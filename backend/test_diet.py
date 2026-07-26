"""Tests for diet handling — veg / non-veg / high-protein.

Covers a bug where asking for "a budget friendly non-veg diet that can fulfil my
protein intakes" produced a 100% VEGETARIAN plan. Two independent causes, both
of which had to be wrong at once for the symptom to appear:

  1. Every catalog seed query named a vegetarian dish (dosa, paneer, dal, ...),
     so the pool the optimizer chose from contained no non-veg food at all.
     Diet has to steer the SEARCH, not just filter the results.
  2. Swiggy sends isVeg=True for veg items and OMITS the field for non-veg.
     Defaulting a missing value to True marked every chicken dish vegetarian.
"""
import catalog_fetcher as CF
import blueprint_chat as B


def _run(name, fn):
    try:
        fn()
        print(f"PASS {name}")
        return True
    except AssertionError as e:
        print(f"FAIL {name}: {e}")
        return False


# ---- isVeg parsing (cause 2) ---------------------------------------------
def test_missing_isveg_is_not_assumed_veg():
    """Swiggy omits isVeg for non-veg items — a missing flag must NOT mean veg."""
    assert CF._is_veg({"name": "Chicken Lababdar", "isVeg": None}) is False
    assert CF._is_veg({"name": "Dum Chicken Biryani"}) is False
    assert CF._is_veg({"name": "Double Egg Omelette", "isVeg": None}) is False
    assert CF._is_veg({"name": "Bihari Gosht Mutton Burger", "isVeg": None}) is False


def test_explicit_isveg_true_is_respected():
    assert CF._is_veg({"name": "Kadhai Paneer", "isVeg": True}) is True
    assert CF._is_veg({"name": "Dal Makhani", "is_veg": True}) is True


def test_explicit_isveg_false_is_respected():
    assert CF._is_veg({"name": "Anything", "isVeg": False}) is False


def test_veg_name_without_flag_stays_veg():
    """A missing flag falls back to the NAME — veg dishes must survive that."""
    assert CF._is_veg({"name": "Masala Dosa"}) is True
    assert CF._is_veg({"name": "Paneer Butter Masala"}) is True
    assert CF._is_veg({"name": "Veg Dum Biryani Bowl"}) is True


# ---- seed queries (cause 1) ----------------------------------------------
def test_nonveg_seeds_exist_for_every_meal():
    """Without non-veg seeds the fetched pool is vegetarian by construction."""
    for meal in ("breakfast", "lunch", "dinner"):
        assert CF.NONVEG_QUERIES.get(meal), f"no non-veg seeds for {meal}"


def test_base_seeds_are_all_vegetarian():
    """Documents WHY non-veg seeds are needed: the base set has no meat in it."""
    flat = [q for qs in CF.SLOT_QUERIES.values() for q in qs]
    assert not any(any(k in q for k in CF._MEAT_NAME_KW) for q in flat)


def test_protein_seeds_cover_both_diets():
    assert CF.PROTEIN_QUERIES["veg"] and CF.PROTEIN_QUERIES["nonveg"]
    # the non-veg protein seeds must actually name meat/egg
    assert any(any(k in q for k in CF._MEAT_NAME_KW)
               for q in CF.PROTEIN_QUERIES["nonveg"])


# ---- chat extraction -----------------------------------------------------
def test_nonveg_request_clears_veg_only():
    """"non-veg" contains "veg" as a substring — the negative form must win."""
    bp, _, _ = B._fallback_turn(dict(B.EMPTY_BLUEPRINT), "I want non-veg food")
    assert bp["veg_only"] is False


def test_nonveg_overrides_earlier_veg_choice():
    """A user who said veg and then corrects themselves must be able to switch."""
    prev = {**B.EMPTY_BLUEPRINT, "veg_only": True}
    bp, _, _ = B._fallback_turn(prev, "actually make it chicken heavy")
    assert bp["veg_only"] is False


def test_protein_intent_detected():
    for msg in ("need to hit my protein intake", "high protein for the gym",
                "building muscle", "tracking my macros"):
        bp, _, _ = B._fallback_turn(dict(B.EMPTY_BLUEPRINT), msg)
        assert bp["high_protein"] is True, msg


def test_protein_not_falsely_detected():
    bp, _, _ = B._fallback_turn(dict(B.EMPTY_BLUEPRINT), "budget 10000, veg only")
    assert not bp["high_protein"]


def test_full_user_request_parsed():
    """The exact message that produced an all-veg plan."""
    bp, _, _ = B._fallback_turn(
        dict(B.EMPTY_BLUEPRINT),
        "Just shifted to gurgaon, need a budget friendly non-veg diet that can "
        "fulfil my protien intakes and is tasty as well budget is 15 K")
    assert bp["veg_only"] is False, "non-veg request was read as vegetarian"
    assert bp["high_protein"] is True, "protein intent was missed"


def test_blueprint_carries_high_protein():
    assert "high_protein" in B.EMPTY_BLUEPRINT
    merged = B._merge_blueprint(dict(B.EMPTY_BLUEPRINT), {"high_protein": True})
    assert merged["high_protein"] is True


if __name__ == "__main__":
    tests = [(k, v) for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    passed = sum(_run(name, fn) for name, fn in tests)
    print(f"\n{passed}/{len(tests)} passed")
    raise SystemExit(0 if passed == len(tests) else 1)
