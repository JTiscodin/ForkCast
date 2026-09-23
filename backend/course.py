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

# --- Dish KINDS: what category of food a dish is ---------------------------
# Course says what ROLE a dish plays in a meal (bread/curry/complete/...);
# kind says what CATEGORY of food it is. The two axes are independent: a
# gulab jamun is course=side AND kind=sweet; a samosa is course=side AND
# kind=snack; a biryani is course=complete AND kind=meal.
#
# WHY: the optimizer's hard filter for meal slots needs the category axis.
# Course alone can't express it — course=side covers sweets, snacks, drinks
# AND condiments, and course=complete covers a few desserts whose names carry
# a meal-ish form word. The live catalog surfaced exactly these failures:
# "Rasmalai" ₹89 and "Ice Cream Sundae" sailed the default-COMPLETE path into
# dinner slots. Kind gives the planner one field to gate on: meal slots take
# kind=meal, full stop.
KIND_MEAL = "meal"
KIND_SNACK = "snack"
KIND_SWEET = "sweet"
KIND_BEVERAGE = "beverage"
KINDS = (KIND_MEAL, KIND_SNACK, KIND_SWEET, KIND_BEVERAGE)

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
        # PLURALS of the forms above: _contains_word is exact-token matching,
        # so the singular-only entries missed "Samosas"/"Pakoras"/"Kachoris"/
        # "Spring Rolls" on real Swiggy menus and they rode the COMPLETE
        # default into meal slots.
        "samosas", "pakoras", "pakodas", "kachoris", "spring rolls",
        # Multi-word snacks whose GENERIC second word would otherwise claim the
        # dish as a meal form/keyword: "Bread Roll" (stuffed-fried potato roll —
        # "Kathi Roll"/"Egg Roll" carry no "bread" and stay meals) beats the
        # "roll" COMPLETE keyword; "Poha Chivda" (poha-flake namkeen) beats the
        # "poha" COMPLETE form; "Sandwich Dhokla" (layered dhokla) beats the
        # "sandwich" form via longest-match.
        "bread roll", "poha chivda", "sandwich dhokla",
        # Mumbai chaat cutlet family: "Ragda Pattice" ("cutlet" is already a
        # form). Singular "cheese ball" — the plural form above only matched
        # "Cheese Balls". Bangalore chaat "Masala Puri", joining the sev/dahi/
        # pani puri family — the "puri" BREAD keyword would otherwise make it
        # a 2-pc accompaniment.
        "pattice", "cheese ball", "masala puri",
        # Marathi "Kanda Bhaji" (onion fritters) missed the bhajiya/bhajji
        # spellings. "pav bhaji" is the longer form so it still wins
        # longest-match and Pav Bhaji stays a COMPLETE meal.
        "bhaji",
        # CONDIMENTS & ACCOMPANIMENTS live here, not in the keyword table below.
        # Tier order made anything named "Masala X" a curry before the SIDE
        # keywords were ever consulted: "Masala Papad" was classified a curry
        # (confidently — bypassing the price floor) and served with two rotis.
        # A condiment's FORM is what it is regardless of flavour words, so these
        # beat every ingredient keyword.
        "papad", "papadum", "poppadom", "appalam", "fryums", "vadam",
        "raita", "chutney", "chutneys", "achar", "achaar", "pickle", "salan",
        "dip", "dips", "salsa",
        # drinks — "Mango Shake" defaulted to COMPLETE and got planned as dinner
        "juice", "shake", "milkshake", "smoothie", "mojito", "soda",
        "jaljeera", "nimbu pani", "shikanji", "thandai", "tea", "coffee",
        "chai", "water", "beverage",
        # Indian dairy drinks. These were only in the keyword tier, which
        # "Masala X" beat as a curry keyword: "Masala Chaas" classified as a
        # curry main and got planned as dinner. The form tier outranks all
        # ingredient keywords, so the drink wins here.
        "lassi", "chaas", "chaach", "buttermilk",
        # desserts beyond gulab jamun / ice cream / brownie: "Rasmalai" ₹89
        # sailed through the default-COMPLETE price gate as an entire meal
        "rasmalai", "ras malai", "kulfi", "jalebi", "halwa", "phirni",
        "kheer", "payasam", "seviyan", "malpua", "rabri", "rabdi",
        "shahi tukda", "basundi", "peda", "barfi", "burfi", "katli",
        # more sweets the live catalogs surfaced: "Rasgulla" and "Laddoo"
        # missed the list above and defaulted to COMPLETE dinners. As FORMS
        # they also beat any ingredient keyword ("Dry Fruit Laddoo" can't be
        # read as a curry by its words).
        "gulab jamun", "rasgulla", "laddoo", "laddu", "sandesh",
        "modak", "sheera", "sooji halwa", "double ka meetha", "mithai",
        "ice cream", "brownie", "cheesecake", "cupcake", "pudding", "cake",
        "dessert",
        # cookie-counter forms — see the _KIND_SWEET_WORDS note on the
        # Chocolate Cookie that rode the COMPLETE default into breakfast.
        "cookie", "cookies", "macaron", "macarons", "cinnamon roll",
        "strudel", "flan",
        # NON-MEAL platters. A bare "platter" is deliberately not a form (see
        # the COMPLETE tuple), so these multi-word entries are what catches
        # the assortments outright: "Dessert Platter" is six sweets on a
        # tray, not dinner, and "Snack Platter" is a starter board.
        "dessert platter", "sweet platter", "snack platter", "drinks platter",
        # soups are starters, not dinners ("Tomato Soup" ₹120 → COMPLETE)
        "soup", "shorba", "consomme",
        # fried starters the snack list missed
        "lollipop", "wings", "winglet", "drumlet", "cheese sticks",
        "mozzarella sticks", "hush puppies",
        # more fried snack sides from live promo catalogs ("Veg Nuggets" ₹80
        # defaulted to COMPLETE and was planned as a whole dinner nine times)
        "nachos", "nacho", "french fries", "hash brown", "hashbrown",
        "chips", "nuggets",
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
        # NOTE on "platter": deliberately NOT a bare COMPLETE form. A food
        # platter already resolves to a COMPLETE meal through its food word
        # ("Momo Platter" -> "momo") or the default pass, while a bare
        # "platter" form would give generic names ("Zzz Mystery Platter")
        # form-confidence and block the description tier from settling them —
        # which is exactly how test_description_settles_unknown_names works.
        # The multi-word SIDE forms above ("dessert platter", "snack platter",
        # ...) still beat everything for the non-meal assortments.
        "pav bhaji", "vada pav", "misal", "bhurji", "omelette", "paratha roll",
        # "Puri Bhaji" is a standalone potato-curry-with-puri breakfast; the
        # shorter SIDE form "bhaji" (fritters, "Kanda Bhaji") must not claim it
        # — longest-match makes this the winner, same guard pattern as "pav
        # bhaji". Meal-with-dessert combos ("Paneer Thali with Gulab Jamun")
        # must stay meals: the MAIN is the dish, the sweet is an add-on, so at
        # 16 chars this outranks the 11-char "gulab jamun" SIDE form; the
        # shorter "thali with" covers other dessert add-ons ("Thali with
        # Kheer") the same way.
        "puri bhaji", "thali with", "with gulab jamun",
        # "Misal Pav" companion spellings from live menus.
        "missal",
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
        # Bare spellings too: a live catalog surfaced "Roomali (Whole Wheat)"
        # ₹29 with no "roti" word in the name, so it fell through to the
        # COMPLETE default and got planned as a whole dinner.
        "roomali", "rumali",
        "missi roti", "garlic naan", "butter naan", "cheese naan",
        "laccha paratha", "aloo paratha", "roti", "chapati", "chapathi",
        "phulka", "naan", "kulcha", "bhatura", "bhature", "puri", "poori",
        "paratha", "parantha", "porotta", "appam", "thepla", "bread basket",
        # Bare carrier breads. Form overrides ("pav bhaji", "vada pav") win
        # first via longer-match, so these only catch a bare "Pav Basket" /
        # "Butter Bun" that used to ride the COMPLETE default past the price
        # floor as a ₹49 "meal".
        "pav", "bun",
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
        # soda-pop brands and drinks the live catalog surfaced; also here so
        # the fuzzy tier can catch misspellings of them
        "cola", "lemonade", "nimbu soda", "iced tea", "soft drink",
        "sprite", "fanta", "mirinda", "limca",
        # drinks the kind tables know but the course table didn't — "Masala
        # Chai" and "Mango Lassi" used to fall through to the COMPLETE default
        # and pass the price gate as meals.
        "chai", "tea", "coffee", "juice", "shake", "milkshake", "falooda",
        "sundae",
        "nachos", "nacho", "french fries", "hash brown", "hashbrown",
        "chips", "nuggets",
        # "Salan" is the Hyderabadi condiment served WITH biryani — a ₹19
        # sauce, not a dish you order as dinner. Unlisted, it defaulted to
        # COMPLETE and was planned as a whole dinner; as a CURRY it became
        # "salan + 2 roti", still a poor meal. It is a side, full stop.
        "salan",
        # A BARE egg item ("Roasted Egg" ₹20, "Boiled Egg", "Egg 65") is a
        # single egg — an add-on, not a breakfast. This sits LAST on purpose:
        # every real egg meal carries a form word that an earlier tuple
        # claims first ("Egg Roll" -> roll, "Egg Bhurji" -> bhurji,
        # "Egg Curry" -> curry, "Egg Omelette" -> omelette), so "egg" only
        # ever fires when nothing else described the dish.
        "egg", "anda",
    )),
)

# --- DRINK-COMBO DEMOTION ---------------------------------------------------
# Promo SKUs bundle a drink with a snack: "Nachos + Coke Combo @ Rs.49". The
# word "combo" is a COMPLETE form override, so a nachos-and-soda promo
# classified as a full dinner — and was served as DINNER nine times in one
# month. Rule: when a name carries a DRINK word, the item is at most a snack,
# UNLESS it also names real food (a burger, a biryani, a chicken bucket...):
# "Burger + Coke Combo" is dinner, "Nachos + Coke Combo" is not.
#
# Checked BEFORE the form overrides: this is itself a form judgment, and it
# exists precisely to beat the "combo"/"bowl"/"box" complete-form words.
_DRINK_WORDS = (
    "coca cola", "cold drink", "soft drink", "iced tea", "lemonade",
    "coke", "cola", "pepsi", "mirinda", "sprite", "fanta", "thumbs up",
    "thums up", "mountain dew", "limca", "soda", "mojito",
)
_DRINK_SET = frozenset(_DRINK_WORDS)
# Real-food forms strong enough that a drink alongside them is just a combo
# add-on. Deliberately EXCLUDES the promo words themselves ("combo", "bowl",
# "meal box") — those are what the demotion protects against.
_STRONG_MEAL_FORMS = (
    "burger", "pizza", "sandwich", "wrap", "roll", "biryani", "thali",
    "momos", "dosa", "paratha", "fried rice", "rice", "noodles", "pasta",
    "frankie", "shawarma", "khichdi", "poha", "upma", "omelette", "bhurji",
    "pav bhaji", "vada pav", "idli", "uttapam",
    "chicken", "mutton", "fish", "prawn", "egg", "kebab", "tikka",
)

# --- KIND word tables -------------------------------------------------------
# Used to split course=side items into beverage / sweet / snack, and to catch
# the few desserts that a meal-ish FORM word mislabels as a meal ("Ice Cream
# Sundae" carries no sweet form word, so it rides the COMPLETE default into a
# dinner slot). _kind_for checks SWEET first (see its docstring); "Mango
# Shake" still lands beverage because "shake"/"milkshake" are SIDE forms, so
# _kind_for never sees it — a drink word with no sweet word in the name is a
# drink.
_KIND_DRINK_WORDS = _DRINK_WORDS + (
    "lassi", "chai", "tea", "coffee", "juice", "shake", "milkshake", "soda",
    "nimbu pani", "thandai", "buttermilk", "chaach", "chaas",
    "water", "beverage", "smoothie", "mojito", "jaljeera", "shikanji",
    # Milk-based drinks that carry no "shake" word — "Rose Milk", "Badam
    # Milk", "Hot Chocolate" are drinks, not meals. Bare "milk" stays here
    # ("Milk 500ml" is a beverage); the SWEET table wins "Milk Cake" because
    # _kind_for below checks sweet BEFORE drink.
    "rose milk", "badam milk", "flavoured milk", "flavored milk",
    "hot chocolate", "cold coffee", "milk",
)
_KIND_SWEET_WORDS = (
    "gulab jamun", "rasgulla", "rasmalai", "ras malai", "jalebi", "kheer",
    "payasam", "barfi", "burfi", "laddoo", "laddu", "peda", "halwa",
    "sandesh", "kulfi", "phirni", "ice cream", "brownie", "cake", "dessert",
    "mithai", "modak", "sheera", "basundi", "double ka meetha", "sundae",
    "cheesecake", "cupcake", "pudding", "malpua", "rabri", "rabdi",
    "shahi tukda", "seviyan", "katli",
    # Missed by the first pass — all real Swiggy dessert-section names that
    # rode the COMPLETE default past the price gate into meal slots.
    "mishti", "pastry", "pastries", "custard", "shrikhand", "motichoor",
    "ghevar", "puran poli", "mysore pak", "boondi", "falooda", "zarda",
    "kulfi falooda", "sharabi", "chena", "chhena", "khoya", "mawa",
    "kaju katli", "kaju pista", "sohan papdi", "soan papdi", "chum chum",
    "cham cham", "rasbhari", "firni", "bebinca", "dodol", "pipa",
    "chikki", "gajak", "revdi", "prasad", "prashad", "panjiri",
    "sweet box", "sweet basket", "mithai box", "dry fruit sweet",
    # Regional/transliteration variants of listed words plus distinct regional
    # sweets — all confirmed riding the COMPLETE default into meal slots on the
    # live sweep. Bengali: sondesh/rosogolla/rasogolla/pantua/ledikeni/chom
    # chum/kala jamun (dark gulab-jamun family — bare "jamun" stays out so it
    # can't fire inside "gulab jamun" unlisted contexts)/khaja (flaky dry
    # sweet)/shahi tukra (tukda spelling). Eid/Hyderabad: sheer khurma,
    # qubani/khubani ka meetha, sewaiyan. Kannada: obbattu/holige (puran poli
    # synonyms), pedha spelling. Tamil/Kerala: adirasam, ada pradhaman
    # (payasam family), pinni (Punjabi ghee-flour sweet).
    "sondesh", "rosogolla", "rasogolla", "pantua", "ledikeni",
    "chom chum", "chomchum", "kala jamun", "khaja", "shahi tukra",
    "sheer khurma", "qubani ka meetha", "khubani ka meetha", "sewaiyan",
    "obbattu", "holige", "pedha", "adirasam", "ada pradhaman",
    "pinni",
    # Bakery desserts the first pass missed: tart, eclair, muffin, doughnut/
    # donut, tiramisu, red velvet (dessert-section staple that carries neither
    # "cake" nor "pastry" in the name).
    "tart", "tarts", "eclair", "muffin", "muffins",
    "doughnut", "doughnuts", "donut", "donuts", "tiramisu", "red velvet",
    # Bakery/cookie-counter staples. "Dark Chunk Chocolate Cookie (Eggless)"
    # rode the COMPLETE default (no form word matched) past the price gate and
    # into breakfast slots. Cookies are sweets; "chocolate" itself stays out
    # (Hot Chocolate is a drink, Chocolate Cake matches "cake" already).
    "cookie", "cookies", "macaron", "macarons", "brownie cookie",
    "rugoelach", "rugelach", "cinnamon roll", "danish", "strudel", "flan",
    # "Milk Cake" is a solid kalakand-type sweet, not a drink: bare "milk" in
    # the drink table must not win it. "milk cake" outranks "milk" because
    # _kind_for checks drinks first — so guard the drink side instead (see the
    # milk-word note in _KIND_DRINK_WORDS).
    "milk cake",
)
# The fallback bucket — matched by the default tier in classify() (an
# unrecognised name like "Dhokla" or "Masala Bonda" gets KIND_SNACK here, so
# it cannot ride the COMPLETE default into a meal slot) and by _kind_for()
# (anything SIDE that is neither a drink nor a sweet is a snack). Also feeds
# the LLM prompt as documentation.
_KIND_SNACK_WORDS = (
    "samosa", "pakora", "pakoda", "chaat", "vada", "bhel", "pani puri",
    "golgappa", "kachori", "tikki", "cutlet", "nachos", "chips", "nuggets",
    "fries", "spring roll", "papad", "raita", "chutney", "salad", "soup",
    # Gujarati/Maharashtrian snack-counter staples that used to default to
    # COMPLETE/meal and headline lunch slots.
    "dhokla", "khandvi", "fafda", "bonda", "bhujia", "namkeen", "sev",
    "farsan", "khakhra", "mathri", "chakli", "murukku", "ribbon pakoda",
    "toast", "toastie", "garlic bread", "bread sticks", "breadstick",
    "keema pav", "masala pav", "cheese balls", "corn dogs", "corndog",
    "popcorn", "peanut butter", "hummus", "dip", "salsa", "mayo",
    "mayonnaise", "ketchup", "sauce", "macaroni",
    # Farsan/namkeen-counter words the sweep confirmed riding the COMPLETE
    # default into meal slots: "khaman" (every Swiggy farsan counter names it
    # bare — "Nylon Khaman", "Sada Khaman"), "mixture" (the classic namkeen
    # blend — "Navratna Mixture"), "chivda" (poha-flake namkeen; the form
    # "poha chivda" already catches the compound), "gathiya" (Bhavnagar sev
    # snack). Plurals of snack words for the same exact-token reason as the
    # form table: "corn dogs" was listed but singular "corn dog" was not.
    "khaman", "mixture", "chivda", "gathiya", "corn dog",
    "samosas", "pakoras", "kachoris",
)

# Accompaniment quantity per curry, by course.
# Two thin rotis per curry is the realistic Indian serving; rice is one portion.
ACCOMPANIMENT_QTY = {BREAD: 2, STAPLE: 1}

# Breads where ONE is the realistic serving: a naan/kulcha/bhatura/paratha is
# roughly two rotis of flour already. Serving two of those alongside a curry
# produced the live plan's overstuffed dinners (Rs90 of rumali roti beside a
# Rs75 curry). Thin flatbreads keep the classic two.
_ONE_PIECE_BREADS = ("naan", "kulcha", "bhatura", "bhature",
                     "paratha", "parantha")

# Price floor for a standalone meal. No real Swiggy meal costs less than this —
# anything cheaper is an add-on (a ₹19 salan, a ₹20 egg, a ₹10 roti) that the
# keyword rules happened not to name. Only applies to DEFAULT-confidence
# classifications: a confidently recognised dish keeps its course whatever the
# price, so a genuine ₹35 street-food breakfast is never demoted.
MIN_MEAL_PRICE = 40


def _memo(fn):
    """Cache by arguments. Dish names repeat constantly inside one optimizer
    run — every budget/scoring pass re-asks what every candidate dish is — and
    classification is pure string work, so the profiler showed millions of
    re-parses of the same few hundred names per plan. Pure functions of their
    string inputs, hence safe to cache without bounds (catalogs are small)."""
    cache = {}

    def wrapper(*args, **kwargs):
        key = args + tuple(sorted(kwargs.items()))
        try:
            return cache[key]
        except KeyError:
            value = fn(*args, **kwargs)
            cache[key] = value
            return value

    return wrapper


@dataclass(frozen=True)
class CourseInfo:
    course: str
    confidence: str   # "keyword" | "fuzzy" | "llm" | "default"
    # What CATEGORY of food it is (see KIND_* above). Defaults to meal so the
    # two-arg constructions all over this module keep working — and because
    # the default-COMPLETE guess is exactly the "probably a meal" guess.
    dish_kind: str = KIND_MEAL


def _kind_for(course: str, name: str) -> str:
    """Derive the dish KIND from its course and name.

    BREAD/STAPLE/CURRY/COMPLETE are meal categories by definition — a roti is
    part of a meal whatever else the name says. SIDE is the mixed bag (sweets,
    snacks, drinks, condiments), so it gets split by the word tables, SWEET
    before drink (same precedence as the default tier in classify()): bare
    "milk" in the drink table must not claim the solid sweet "Milk Cake",
    while "Mango Shake" still lands beverage because "shake" is a SIDE form
    and its own phrase outranks "milk" here — a drink word with no sweet word
    in the name is still a drink.
    """
    if course != SIDE:
        return KIND_MEAL
    if any(_contains_word(name, w) for w in _KIND_SWEET_WORDS):
        return KIND_SWEET
    if any(_contains_word(name, w) for w in _KIND_DRINK_WORDS):
        return KIND_BEVERAGE
    return KIND_SNACK


@_memo
def classify(name: str) -> CourseInfo:
    """Classify a menu-item name into a course.

    Passes, in order:
      0. DRINK-COMBO   — a drink word ("coke", "pepsi", ...) demotes the item
                          to a side unless real food is also named. Stops the
                          "Nachos + Coke Combo @ Rs.49" promo classifying as a
                          complete dinner via its "combo" form word.
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

    # 0. A drink is never the meal — unless real food is named alongside it
    # ("Burger + Coke Combo" IS dinner). See _DRINK_WORDS above for why this
    # runs ahead of the form overrides: it exists to beat the "combo"/"bowl"
    # complete-form words on promo SKUs like "Nachos + Coke Combo @ Rs.49".
    has_drink = any(_contains_word(n, w) for w in _DRINK_WORDS)
    if has_drink and not any(_contains_word(n, f) for f in _STRONG_MEAL_FORMS):
        # Kind refinement for the demoted combo: the item is at most a snack,
        # but a sweet or a snack word in the name says which. "Nachos + Coke
        # Combo" -> snack, "Gulab Jamun + Pepsi" -> sweet, bare "Pepsi" ->
        # beverage.
        if any(_contains_word(n, w) for w in _KIND_SNACK_WORDS):
            kind = KIND_SNACK
        elif any(_contains_word(n, w) for w in _KIND_SWEET_WORDS):
            kind = KIND_SWEET
        else:
            kind = KIND_BEVERAGE
        return CourseInfo(SIDE, "form", kind)

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
        return CourseInfo(best, "form", _kind_for(best, n))

    # 2. Ingredient / preparation keywords.
    for course, keywords in _COURSE_KEYWORDS:
        if has_drink and course == SIDE:
            # Real food is named alongside the drink; ignore the drink words so
            # "Chicken Bucket + Pepsi 750ml" doesn't fall through to the bare
            # "pepsi" side keyword and lose its meal status after all.
            keywords = [kw for kw in keywords if kw not in _DRINK_SET]
        for kw in keywords:
            if _contains_word(n, kw):
                return CourseInfo(course, "keyword", _kind_for(course, n))

    fuzzy = _fuzzy_classify(n)
    if fuzzy:
        return CourseInfo(fuzzy, "fuzzy", _kind_for(fuzzy, n))

    # 3. The default guess. The course stays COMPLETE (it may fill a meal
    # slot), but the KIND gets one last look at the name: a dessert or snack
    # whose name carries no form word we know ("Ice Cream Sundae", "Dhokla",
    # "Masala Bonda") must not ride the default into a dinner slot — the kind
    # gate is what catches it. Order: sweet before drink before snack, same
    # precedence as _kind_for.
    kind = _kind_for(COMPLETE, n)
    if kind == KIND_MEAL:
        if any(_contains_word(n, w) for w in _KIND_SWEET_WORDS):
            kind = KIND_SWEET
        elif any(_contains_word(n, w) for w in _KIND_DRINK_WORDS):
            kind = KIND_BEVERAGE
        elif any(_contains_word(n, w) for w in _KIND_SNACK_WORDS):
            kind = KIND_SNACK
    return CourseInfo(COMPLETE, "default", kind)


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


@_memo
def course_of(name: str) -> str:
    """Convenience: just the course string."""
    return classify(name).course


@_memo
def dish_kind_of(name: str) -> str:
    """Convenience: just the kind string (meal|snack|sweet|beverage)."""
    return classify(name).dish_kind


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

# Description signals for the KIND axis, checked in the same tier as
# _DESC_SIGNALS and with the same restraint: they only refine a weak
# (default/keyword) name classification, never a form match. Order matters —
# beverage before sweet, because dessert-shop blurbs love the word "sweet".
_DESC_KIND_SIGNALS = (
    (KIND_BEVERAGE, ("beverage", "drink", "drinks", "refreshing drink",
                     "thirst quencher", "served chilled", "soft drink")),
    (KIND_SWEET, ("dessert", "sweet", "sweets", "sugar syrup", "sweetened",
                  "served hot with rabri", "garnished with pistachios",
                  "milk fudge", "condensed milk")),
    (KIND_SNACK, ("snack", "starter", "appetizer", "finger food", "deep fried",
                  "deep-fried", "crispy", "tea time", "street style")),
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

    n = (name or "").lower().strip()
    d = description.lower()
    for course, phrases in _DESC_SIGNALS:
        for phrase in phrases:
            if phrase in d:
                # Only override a guess or a bare ingredient match.
                if info.confidence in ("default", "keyword") and course != info.course:
                    return CourseInfo(course, "description",
                                      _kind_for(course, n))
                return info

    # The course signals found nothing, but the description may still settle
    # the KIND — "Zzz Mystery Platter" reads as a snack from its blurb even
    # when no course phrase fires. Same restraint as above: a form-matched
    # name keeps its kind, and a confident keyword course is trusted over
    # prose ("served with rice" must not demote a real curry's kind).
    if info.confidence in ("default",):
        for kind, phrases in _DESC_KIND_SIGNALS:
            if any(phrase in d for phrase in phrases):
                if kind != info.dish_kind:
                    return CourseInfo(info.course, "description", kind)
                return info
    return info


@_memo
def is_standalone_meal(name: str) -> bool:
    """True if this dish can fill a meal slot by itself."""
    return course_of(name) in STANDALONE


@_memo
def standalone_meal(name: str, price: float = None) -> bool:
    """Can this dish headline a meal slot on its own?

    The course says what role the dish plays; the price guards against the
    classifier's blind spot. An UNRECOGNISED name defaults to COMPLETE, and
    that default is how a ₹19 salan and a ₹20 roasted egg ended up planned as
    whole dinners. A default-confidence dish below MIN_MEAL_PRICE is treated
    as a side — it can still pair with a curry, just never stand alone.
    """
    info = classify(name)
    if info.course not in STANDALONE:
        return False
    if (info.confidence == "default" and price is not None
            and price < MIN_MEAL_PRICE):
        return False
    return True


# Confidence levels we trust enough to attach bread/rice to a dish.
# A "default" (unrecognised) name is NOT trusted: the cost of a wrong pairing
# (roti served with momos) is far worse than the cost of a missing one (a curry
# arrives without bread). When unsure, do less.
_PAIRABLE_CONFIDENCE = frozenset({"form", "keyword", "fuzzy"})


@_memo
def needs_accompaniment(name: str) -> bool:
    """True if this dish is confidently a curry, so it should get bread/rice.

    Deliberately stricter than `course_of(name) in NEEDS_ACCOMPANIMENT`: a
    guessed classification never earns an accompaniment.
    """
    info = classify(name)
    return (info.course in NEEDS_ACCOMPANIMENT
            and info.confidence in _PAIRABLE_CONFIDENCE)


@_memo
def can_accompany(name: str) -> bool:
    """True if this dish can serve as the bread/rice half of a paired meal."""
    return course_of(name) in ACCOMPANIMENT


@_memo
def accompaniment_qty(name: str) -> int:
    """How many units of this accompaniment go with one curry (2 roti, 1 rice,
    but only 1 of the heavyweight breads — see _ONE_PIECE_BREADS)."""
    course = course_of(name)
    if course == BREAD and any(_contains_word(name.lower(), w)
                               for w in _ONE_PIECE_BREADS):
        return 1
    return ACCOMPANIMENT_QTY.get(course, 1)


# --- Tier 3: LLM fallback, cached forever by dish_id ----------------------
_LLM_CACHE = {}

_CLASSIFY_SYSTEM = """You classify Indian restaurant menu items by their role in a meal.
Reply with TWO words only, no punctuation: <course> <kind>.

First word, the course, from exactly this list:
bread    - roti, naan, paratha, puri (eaten WITH something)
staple   - plain rice, pulao, jeera rice (eaten WITH something)
curry    - paneer/dal/chicken GRAVIES, eaten with bread or rice
complete - biryani, thali, dosa, momos, noodles, burger (a full meal alone)
side     - samosa, kachori, tikki, chaat, pakora, raita, papad, dessert, drinks

Second word, the kind (what CATEGORY of food it is), from exactly this list:
meal     - real food that can be eaten AS a meal (breads, curries, biryani...)
snack    - samosa, kachori, tikki, chaat, pakora, nachos, fries, condiments
sweet    - gulab jamun, kheer, jalebi, ice cream, brownie, any dessert
beverage - chai, lassi, juice, shake, soda, any drink

CRITICAL: judge the dish's FORM, not its ingredients.
"Dal Kachori" is a KACHORI (side snack), not a dal curry.
"Paneer Momos" are MOMOS (complete meal), not a paneer curry.
"Chilli Paneer" is a dry stir-fry (complete meal), not a gravy.
Answer curry ONLY for actual gravies you would eat with roti or rice.
Ignore brand and marketing words ("Party Bucket", "Special", "Combo Pack")."""


def _resolve_unknown(dish_id: str, name: str, use_llm: bool):
    """Shared engine behind classify_unknown / kind_unknown.

    ONE Gemini call resolves BOTH axes: the cache stores a (course, kind)
    tuple per dish_id, so asking for the kind after the course (or vice
    versa) never costs a second call. Bounded by design: each unseen dish
    costs at most one call for the lifetime of the process. Off unless
    use_llm=True so plan generation never silently depends on the network.
    """
    if dish_id in _LLM_CACHE:
        entry = _LLM_CACHE[dish_id]
        # Defensive: an entry written as a bare course string (pre-tuple
        # shape) still answers the course question; derive the kind from the
        # name rules.
        if isinstance(entry, str):
            return entry, dish_kind_of(name)
        return entry

    info = classify(name)
    if info.confidence != "default" or not use_llm:
        entry = (info.course, info.dish_kind)
        _LLM_CACHE[dish_id] = entry
        return entry

    course, kind = info.course, info.dish_kind  # fallbacks if the call fails
    try:
        import gemini
        if gemini.has_key():
            reply = gemini.chat(f"Menu item: {name}", system=_CLASSIFY_SYSTEM)
            words = (reply or "").strip().lower().split()
            # Validate each word INDEPENDENTLY: a good course with a garbled
            # kind (or vice versa) keeps the half the model got right.
            if words and words[0] in (BREAD, STAPLE, CURRY, COMPLETE, SIDE):
                course = words[0]
            if len(words) > 1 and words[1] in KINDS:
                kind = words[1]
    except Exception:  # noqa: BLE001 — classification must never break planning
        pass

    entry = (course, kind)
    _LLM_CACHE[dish_id] = entry
    return entry


def classify_unknown(dish_id: str, name: str, use_llm: bool = False) -> str:
    """Classify with the LLM only when tiers 1-2 defaulted, then cache forever.
    Returns the COURSE; see kind_unknown for the sibling kind accessor."""
    return _resolve_unknown(dish_id, name, use_llm)[0]


def kind_unknown(dish_id: str, name: str, use_llm: bool = False) -> str:
    """The KIND half of the same cached classification. One Gemini call
    resolves both axes — calling this after classify_unknown for the same
    dish_id is a pure cache hit."""
    return _resolve_unknown(dish_id, name, use_llm)[1]


def cache_stats():
    """Visibility into what the LLM tier has been asked to resolve."""
    def _entry(v):
        # Tolerate a bare-string entry (see _resolve_unknown) when counting.
        return v if isinstance(v, tuple) else (v, dish_kind_of(""))

    return {"cached": len(_LLM_CACHE),
            "by_course": {c: sum(1 for v in _LLM_CACHE.values()
                                 if _entry(v)[0] == c)
                          for c in (BREAD, STAPLE, CURRY, COMPLETE, SIDE)},
            "by_kind": {k: sum(1 for v in _LLM_CACHE.values()
                               if _entry(v)[1] == k)
                        for k in KINDS}}
