"""Indian-cuisine course classification + meal composition rules.

WHY THIS EXISTS
---------------
Swiggy's search_menu returns menu-item names with no notion of what role a dish
plays in a meal. So the optimizer happily planned "Tawa Roti ₹10" as an entire
dinner (it scored brilliantly on the cheap-is-good price term). A roti is a
SIDE. A paneer sabzi is a CURRY and needs bread or rice with it. A biryani is a
COMPLETE meal and needs nothing.

That knowledge is stable, cultural, and small — so it lives in code, not in an
LLM prompt. Same reasoning as keeping the money math in optimizer.py: we want
it deterministic, free, and testable. An LLM would re-derive identical facts on
every slot of every plan, at token cost, with sampling variance.

TIERED CLASSIFICATION
---------------------
  Tier 1  keyword match on the dish name          (this module, covers the bulk)
  Tier 2  fuzzy match for spelling variants        (rapidfuzz, optional dep)
  Tier 3  LLM classify + cache by dish_id forever  (see classify_unknown)

Tier 1 works because Indian menu naming is highly conventional: almost every
roti has "roti" in its name, almost every biryani has "biryani". We exploit that
regularity rather than fighting it with a dataset lookup that would need fuzzy
matching anyway.

COURSES
-------
  bread     roti/naan/paratha — never a meal alone, pairs with curry
  staple    rice/pulao        — never a meal alone, pairs with curry
  curry     paneer/dal/sabzi  — needs a bread or staple to be a meal
  complete  biryani/thali/dosa — a meal by itself
  side      raita/papad/salad — never planned as a meal at all
"""
from dataclasses import dataclass

BREAD = "bread"
STAPLE = "staple"
CURRY = "curry"
COMPLETE = "complete"
SIDE = "side"

# Courses that can occupy a meal slot on their own.
STANDALONE = frozenset({COMPLETE})
# Courses that are a meal only once paired with an accompaniment.
NEEDS_ACCOMPANIMENT = frozenset({CURRY})
# Courses that may serve AS an accompaniment to a curry.
ACCOMPANIMENT = frozenset({BREAD, STAPLE})
# Courses that must never be planned as a meal, paired or otherwise.
NEVER_STANDALONE = frozenset({BREAD, STAPLE, SIDE})

# --- Dish FORMS that override any ingredient ------------------------------
# The single most important rule in this module.
#
# An Indian dish name is usually "<ingredients> <form>": "Dal Kachori" is a
# KACHORI made with dal, "Dal Makhani" is a MAKHANI made with dal. The form
# word decides what the dish IS; the ingredients only say what is in it.
#
# Plain substring matching gets this catastrophically wrong. Matching "dal"
# anywhere in the name classified "Samosa Party Bucket - Mini Dal Kachori" as a
# curry, so the planner served it with two rotis. Same failure for "Paneer
# Tikki", "Dal Vada", "Chilli Paneer" — one flawed matcher, many symptoms.
#
# So: whenever a name contains one of these form words, the form wins outright
# and the ingredient keywords below are never consulted. Snacks and street food
# are their own course precisely because they are neither a meal nor a gravy.
_FORM_OVERRIDES = (
    # fried / street snacks — never a meal, never take an accompaniment
    (SIDE, (
        "kachori", "kachauri", "samosa", "tikki", "vada", "bhalla", "bhalle",
        "pakoda", "pakora", "bhajiya", "bhajji", "chaat", "papdi", "golgappa",
        "pani puri", "puchka", "dahi puri", "sev puri", "bhel", "cutlet",
        "croquette", "nugget", "fries", "wedges", "spring roll", "wonton",
        "garlic bread", "cheese balls", "popcorn",
    )),
    # complete dishes whose form makes them a meal regardless of ingredient
    (COMPLETE, (
        # NB: "pulao" is deliberately NOT here — a plain veg pulao is a staple
        # eaten alongside a curry, not a meal in itself. Only the loaded
        # versions below stand alone.
        "momo", "momos", "dimsum", "dim sum", "biryani", "thali",
        # Regional spellings matter: "Masala Dosai" (Tamil) missed the "dosa"
        # form and fell through to the "masala" curry keyword, earning a dosa
        # two rotis. Same for idly/wada/uthappam.
        "khichdi", "dosa", "dosai", "idli", "idly", "uttapam", "uthappam",
        "wada", "chilla", "cheela", "poha",
        "upma", "noodles", "chowmein", "chow mein", "hakka", "manchurian",
        "burger", "pizza", "sandwich", "wrap", "frankie", "shawarma",
        "maggi", "pasta", "risotto", "bowl", "combo", "meal box", "tiffin",
        "pav bhaji", "vada pav", "misal", "bhurji", "omelette", "paratha roll",
        # Dry Indo-Chinese starters. "Chilli Paneer" is stir-fried and eaten on
        # its own, not a gravy — without this the "paneer" keyword would give it
        # two rotis.
        "chilli paneer", "chilli chicken", "chilli mushroom", "chilli potato",
        "paneer chilli", "honey chilli", "salt and pepper", "crispy",
        # STUFFED parathas are a breakfast in their own right (eaten with curd
        # or pickle), unlike a plain/laccha paratha which accompanies a curry.
        "aloo paratha", "gobi paratha", "paneer paratha", "mooli paratha",
        "onion paratha", "pyaz paratha", "mix paratha", "stuffed paratha",
        "cheese paratha", "egg paratha", "keema paratha", "methi paratha",
    )),
)


# --- Tier 1 keyword table -------------------------------------------------
# Ingredient/preparation keywords, consulted only when NO form word matched.
# Order matters: checked most-specific first, so "chole bhature" resolves to
# COMPLETE before "bhature" could resolve to BREAD. Multi-word keys are checked
# ahead of single words for the same reason.
_COURSE_KEYWORDS = (
    # complete meals — self-sufficient, need no accompaniment
    (COMPLETE, (
        "chole bhature", "pav bhaji", "masala dosa", "rava dosa", "plain dosa",
        "idli vada", "chicken biryani", "veg biryani", "dum biryani",
        "biryani", "thali", "meals", "dosa", "idli", "uttapam", "vada pav",
        "poha", "upma", "khichdi", "pulao biryani", "fried rice", "noodles",
        "hakka noodles", "burger", "pizza", "sandwich", "wrap", "roll",
        "frankie", "maggi", "pasta", "momos", "combo", "curd rice",
        "lemon rice", "bisi bele", "puliyodarai", "rajma chawal",
        "chole chawal", "dal chawal", "kadhi chawal", "sambar rice",
        # Dishes whose names contain a curry keyword but which are self-
        # contained meals — listed here so the COMPLETE pass claims them first.
        # e.g. "Paneer Chilla" would otherwise match "paneer" and be treated as
        # a gravy needing bread.
        "chilla", "cheela", "paneer roll", "paneer wrap", "paneer sandwich",
        "paneer paratha", "paneer dosa", "paneer pizza", "paneer burger",
        "paneer biryani", "paneer pulao", "paneer fried rice", "paneer thali",
        "dal khichdi", "paneer tikka bowl", "rice bowl", "salad bowl",
    )),
    # breads — accompaniment only
    (BREAD, (
        "tandoori roti", "butter roti", "tawa roti", "rumali roti",
        "missi roti", "garlic naan", "butter naan", "cheese naan",
        "laccha paratha", "aloo paratha", "roti", "chapati", "chapathi",
        "phulka", "naan", "kulcha", "bhatura", "bhature", "puri", "poori",
        "paratha", "parantha", "porotta", "appam", "thepla", "bread basket",
    )),
    # plain staples — accompaniment only
    (STAPLE, (
        "steamed rice", "jeera rice", "ghee rice", "plain rice",
        "basmati rice", "veg pulao", "pulao", "rice",
    )),
    # curries / gravies — need bread or rice
    (CURRY, (
        "paneer butter masala", "shahi paneer", "kadai paneer",
        "palak paneer", "matar paneer", "paneer tikka masala",
        "butter chicken", "chicken curry", "chicken masala", "kadai chicken",
        "dal makhani", "dal tadka", "dal fry", "yellow dal",
        "chana masala", "chole masala", "rajma masala", "aloo matar",
        "mix veg", "veg kolhapuri", "malai kofta", "kofta", "korma",
        "rogan josh", "handi", "bhuna", "do pyaza", "lababdar",
        "paneer", "sabzi", "sabji", "curry", "masala", "gravy", "kadai",
        "makhani", "tikka masala", "dal", "chole", "rajma", "kofta",
    )),
    # true sides — never a meal
    (SIDE, (
        "raita", "papad", "salad", "pickle", "achar", "chutney",
        "dahi", "curd", "buttermilk", "chaas", "lassi", "gulab jamun",
        "ice cream", "brownie", "cold drink", "coke", "pepsi", "water",
    )),
)

# Accompaniment quantity per curry, by course.
# Two rotis per curry is the realistic Indian serving; rice is one portion.
ACCOMPANIMENT_QTY = {BREAD: 2, STAPLE: 1}


@dataclass(frozen=True)
class CourseInfo:
    course: str
    confidence: str   # "keyword" | "fuzzy" | "llm" | "default"


def classify(name: str) -> CourseInfo:
    """Classify a menu-item name into a course.

    Passes, in order:
      1. FORM override  — "kachori", "momo", "biryani". The dish's form beats
                          any ingredient in the name. This is what stops "Dal
                          Kachori" being read as a dal curry.
      2. ingredient     — "paneer", "dal", "curry" keywords.
      3. fuzzy          — spelling variants, when rapidfuzz is available.
      4. default        — COMPLETE, flagged low-confidence.

    Never raises. An unrecognised dish defaults to COMPLETE with confidence
    "default": it may fill a meal slot on its own (worst case, a slightly odd
    meal) but callers can see the guess is a guess — and pairing deliberately
    refuses to attach bread to anything not confidently a curry.
    """
    n = (name or "").lower().strip()
    if not n:
        return CourseInfo(COMPLETE, "default")

    # 1. Form wins outright over any ingredient keyword.
    # Take the LONGEST matching form, not the first one listed: "Idli Vada
    # Combo" contains both "vada" (a snack) and "combo" (a full meal), and the
    # longer, more specific match is the one that describes the dish. Matching
    # in list order instead made it a side and quietly shrank the breakfast pool.
    best, best_len = None, 0
    for course, forms in _FORM_OVERRIDES:
        for form in forms:
            if len(form) > best_len and _contains_word(n, form):
                best, best_len = course, len(form)
    if best:
        return CourseInfo(best, "form")

    # 2. Ingredient / preparation keywords.
    for course, keywords in _COURSE_KEYWORDS:
        for kw in keywords:
            if _contains_word(n, kw):
                return CourseInfo(course, "keyword")

    fuzzy = _fuzzy_classify(n)
    if fuzzy:
        return CourseInfo(fuzzy, "fuzzy")

    return CourseInfo(COMPLETE, "default")


def _contains_word(name: str, phrase: str) -> bool:
    """Whole-word containment, so "dal" does not match inside "dalchini".

    Bare `phrase in name` was the other half of the kachori bug: it matched
    across word boundaries as happily as within them. Menu names are messy
    (punctuation, brackets, sizes), so split on any non-letter rather than
    reaching for a regex per keyword.
    """
    words = _words(name)
    parts = phrase.split()
    if len(parts) == 1:
        return parts[0] in words
    # Multi-word phrase: look for the words consecutively.
    n = len(parts)
    return any(words[i:i + n] == parts for i in range(len(words) - n + 1))


def _words(name: str):
    out, cur = [], []
    for ch in name:
        if ch.isalpha():
            cur.append(ch)
        elif cur:
            out.append("".join(cur))
            cur = []
    if cur:
        out.append("".join(cur))
    return out


def _fuzzy_classify(name: str):
    """Tier 2: catch spelling variants ("Chapathi", "Paneeer") the keyword pass
    missed. Optional — if rapidfuzz isn't installed we simply skip this tier."""
    try:
        from rapidfuzz import process, fuzz
    except ImportError:
        return None
    # Match individual words against the keyword vocabulary; menu names carry a
    # lot of branding noise ("TCP Special ..."), so whole-string ratio is weak.
    for word in name.split():
        if len(word) < 4:
            continue
        for course, keywords in _COURSE_KEYWORDS:
            hit = process.extractOne(word, keywords, scorer=fuzz.ratio,
                                     score_cutoff=85)
            if hit:
                return course
    return None


def course_of(name: str) -> str:
    """Convenience: just the course string."""
    return classify(name).course


# Description phrases that reveal a dish's form when the name doesn't.
# Swiggy's get_restaurant_menu returns a description for every item (search_menu
# does not), and it is often far more legible than the branded name: "Raj
# Kachori" reads as "Crispy Kachori Filled with Potatoes, Moong Dal, Yogurt".
# Checked as ordinary phrases, so wording like "served with rice" carries weight.
_DESC_SIGNALS = (
    # explicit "eat it with X" phrasing => the dish is a gravy
    (CURRY, ("served with rice", "served with roti", "served with naan",
             "best with roti", "best with rice", "goes well with roti",
             "pair with roti", "eat with roti", "rich gravy", "thick gravy",
             "creamy gravy", "in a gravy", "curry base", "makhani gravy")),
    # self-contained meals
    (COMPLETE, ("complete meal", "wholesome meal", "full meal", "meal in itself",
                "wrapped in", "stuffed in a", "served with buttered pav",
                "rice dish", "one pot", "biryani", "fried rice")),
    # snacks / street food
    (SIDE, ("crispy", "deep fried", "deep-fried", "street style", "chutneys",
            "snack", "starter", "appetizer", "finger food", "tea time")),
)


def classify_with_description(name: str, description: str = "") -> CourseInfo:
    """Classify using the dish DESCRIPTION as a tiebreaker for weak name matches.

    The name is still authoritative when it carries a clear form word - "Momos"
    is momos whatever the blurb says. The description only gets a vote when the
    name alone produced a low-confidence guess, or when it matched merely on an
    ingredient keyword (the exact case that mislabelled "Dal Kachori" a curry).
    """
    info = classify(name)
    if not description:
        return info
    # A form match on the name is decisive - do not let prose override it.
    if info.confidence == "form":
        return info

    d = description.lower()
    for course, phrases in _DESC_SIGNALS:
        for phrase in phrases:
            if phrase in d:
                # Only override a guess or a bare ingredient match.
                if info.confidence in ("default", "keyword") and course != info.course:
                    return CourseInfo(course, "description")
                return info
    return info


def is_standalone_meal(name: str) -> bool:
    """True if this dish can fill a meal slot by itself."""
    return course_of(name) in STANDALONE


# Confidence levels we trust enough to attach bread/rice to a dish.
# A "default" (unrecognised) name is NOT trusted: the cost of a wrong pairing
# (roti served with momos) is far worse than the cost of a missing one (a curry
# arrives without bread). When unsure, do less.
_PAIRABLE_CONFIDENCE = frozenset({"form", "keyword", "fuzzy"})


def needs_accompaniment(name: str) -> bool:
    """True if this dish is confidently a curry, so it should get bread/rice.

    Deliberately stricter than `course_of(name) in NEEDS_ACCOMPANIMENT`: a
    guessed classification never earns an accompaniment.
    """
    info = classify(name)
    return (info.course in NEEDS_ACCOMPANIMENT
            and info.confidence in _PAIRABLE_CONFIDENCE)


def can_accompany(name: str) -> bool:
    """True if this dish can serve as the bread/rice half of a paired meal."""
    return course_of(name) in ACCOMPANIMENT


def accompaniment_qty(name: str) -> int:
    """How many units of this accompaniment go with one curry (2 roti, 1 rice)."""
    return ACCOMPANIMENT_QTY.get(course_of(name), 1)


# --- Tier 3: LLM fallback, cached forever by dish_id ----------------------
_LLM_CACHE = {}

_CLASSIFY_SYSTEM = """You classify Indian restaurant menu items by their role in a meal.
Reply with ONE word only, no punctuation, from exactly this list:
bread    - roti, naan, paratha, puri (eaten WITH something)
staple   - plain rice, pulao, jeera rice (eaten WITH something)
curry    - paneer/dal/chicken GRAVIES, eaten with bread or rice
complete - biryani, thali, dosa, momos, noodles, burger (a full meal alone)
side     - samosa, kachori, tikki, chaat, pakora, raita, papad, dessert, drinks

CRITICAL: judge the dish's FORM, not its ingredients.
"Dal Kachori" is a KACHORI (side), not a dal curry.
"Paneer Momos" are MOMOS (complete), not a paneer curry.
"Chilli Paneer" is a dry stir-fry (complete), not a gravy.
Answer curry ONLY for actual gravies you would eat with roti or rice.
Ignore brand and marketing words ("Party Bucket", "Special", "Combo Pack")."""


def classify_unknown(dish_id: str, name: str, use_llm: bool = False) -> str:
    """Classify with the LLM only when tiers 1-2 defaulted, then cache forever.

    Bounded by design: the cache key is dish_id, so each unseen dish costs at
    most one call for the lifetime of the process. Off unless use_llm=True so
    plan generation never silently depends on the network.
    """
    if dish_id in _LLM_CACHE:
        return _LLM_CACHE[dish_id]

    info = classify(name)
    if info.confidence != "default" or not use_llm:
        _LLM_CACHE[dish_id] = info.course
        return info.course

    course = info.course  # COMPLETE fallback if the call fails
    try:
        import gemini
        if gemini.has_key():
            reply = gemini.chat(f"Menu item: {name}", system=_CLASSIFY_SYSTEM)
            word = (reply or "").strip().lower().split()
            if word and word[0] in (BREAD, STAPLE, CURRY, COMPLETE, SIDE):
                course = word[0]
    except Exception:  # noqa: BLE001 — classification must never break planning
        pass

    _LLM_CACHE[dish_id] = course
    return course


def cache_stats():
    """Visibility into what the LLM tier has been asked to resolve."""
    return {"cached": len(_LLM_CACHE),
            "by_course": {c: sum(1 for v in _LLM_CACHE.values() if v == c)
                          for c in (BREAD, STAPLE, CURRY, COMPLETE, SIDE)}}
