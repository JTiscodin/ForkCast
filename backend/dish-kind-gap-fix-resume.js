export const meta = {
  name: 'dish-kind-gap-fix',
  description: 'Close remaining dish_kind classification gaps: default-tier snack check, multi-lens leak sweep, table extension, full verify',
  phases: [
    { title: 'Fix', detail: 'apply the default-tier snack-word check in course.py' },
    { title: 'Sweep', detail: '5 read-only lenses hunt remaining kind leaks' },
    { title: 'Extend', detail: 'fold confirmed leaks into the word tables' },
    { title: 'Verify', detail: 'golden tests + full suite + adversarial re-sweep' },
  ],
}

const REPO = 'C:/Users/varda/Documents/Swiggy-Builder'
const BE = REPO + '/backend'

const OK_SCHEMA = {
  type: 'object',
  properties: { ok: { type: 'boolean' }, summary: { type: 'string' } },
  required: ['ok', 'summary'],
}

const LEAK_SCHEMA = {
  type: 'object',
  properties: {
    leaks: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          name: { type: 'string' },
          expected: { type: 'string', enum: ['meal', 'snack', 'sweet', 'beverage'] },
          got: { type: 'string' },
          why: { type: 'string' },
        },
        required: ['name', 'expected', 'got', 'why'],
      },
    },
    checked_count: { type: 'number' },
  },
  required: ['leaks', 'checked_count'],
}

// ---------- Phase 1: Fix the default-tier snack gap ----------
phase('Fix')
const fix = await agent(
`You are fixing one precise bug in ${BE}/course.py (a FastAPI backend module that classifies Indian restaurant menu items).

CONTEXT: The module classifies dishes on two axes. \`course\` (bread|staple|curry|complete|side) says the dish's ROLE; \`dish_kind\` (meal|snack|sweet|beverage) says its CATEGORY. The optimizer only plans dishes with dish_kind == "meal" into breakfast/lunch/dinner slots. \`classify(name)\` returns a frozen CourseInfo(course, confidence, dish_kind). Inside classify(), tier 3 ("The default guess", around line 474) gives unrecognised names course=COMPLETE and then tries to rescue the KIND by checking _KIND_SWEET_WORDS then _KIND_DRINK_WORDS — but it NEVER checks _KIND_SNACK_WORDS. So real snacks whose names carry no form word ("Dhokla", "Masala Bonda", "Namkeen", "Khandvi", "Fafda", "Sev", "Peanut Butter", "Toast", "Macaroni", "Khakhra", "Chakli", "Mathri", "Farsan", "Hummus", "Ketchup", "Mayo") keep kind=meal and leak into meal slots.

TASK — two edits via the Edit tool on ${BE}/course.py:

1. In classify()'s default tier, find EXACTLY this block:

    # 3. The default guess. The course stays COMPLETE (it may fill a meal
    # slot), but the KIND gets one last look at the name: a dessert whose
    # name carries no form word we know ("Ice Cream Sundae") must not ride
    # the default into a dinner slot — the kind gate is what catches it.
    kind = _kind_for(COMPLETE, n)
    if kind == KIND_MEAL:
        if any(_contains_word(n, w) for w in _KIND_SWEET_WORDS):
            kind = KIND_SWEET
        elif any(_contains_word(n, w) for w in _KIND_DRINK_WORDS):
            kind = KIND_BEVERAGE
    return CourseInfo(COMPLETE, "default", kind)

and replace it with:

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

2. The comment above the _KIND_SNACK_WORDS table definition (~line 308) currently says the list is "for documentation and for the LLM prompt, not matched" — that is now false (the default tier matches it). Read that comment block and update it to say the table is matched by the default tier in classify() and by _kind_for(), with the doc/LLM-prompt role kept.

Make NO other changes to course.py.

VERIFY (run these, all must pass):
- cd ${BE} && python -c "import course; [print(n, course.dish_kind_of(n)) for n in ['Dhokla','Khandvi','Fafda','Bonda','Bhujia','Namkeen','Sev','Peanut Butter','Toast','Macaroni','Khakhra','Chakli','Mathri','Farsan','Hummus','Ketchup','Mayo']" — every one must print snack.
- cd ${BE} && python -c "import course; [print(n, course.dish_kind_of(n)) for n in ['Paneer Thali','Chicken Biryani','Masala Dosa','Momos','Veg Fried Rice','Butter Naan','Tawa Roti','Gulab Jamun','Pepsi','Rose Milk','Pastry','Shrikhand','Mysore Pak','Falooda']" — meals stay meal, sweets sweet, drinks beverage.
- cd ${BE} && python test_course.py  (39/39 must pass) and python test_quality.py (7/7) and python test_veg_budget.py (8/8).

If a verification fails, fix ONLY within the two edits described (e.g. word present but table order issue) — do not refactor anything else. Return ok=true with a one-paragraph summary, or ok=false explaining the blocker.`,
  { label: 'fix:default-tier', phase: 'Fix', schema: OK_SCHEMA })
log('Default-tier fix: ' + (fix ? fix.summary : 'AGENT FAILED'))

// ---------- Phase 2: Sweep for remaining leaks ----------
phase('Sweep')
const LENSES = [
  {
    key: 'sweets',
    prompt: `Sweep ${BE}/course.py's dish_kind classification for DESSERT leaks. Run e.g.
cd ${BE} && python -c "import course; ci=course.classify('NAME'); print(ci.dish_kind, ci.confidence)"
Test AT LEAST 35 Indian dessert names across traditions: Bengali (mishti, sandesh variants, rosogolla, pantua, ledikeni, chomchum), Mughlai (shahi tukda, phirni, sheer khurma, qubani ka meetha), South Indian (Mysore pak, obbattu, puran poli, adirasam, payasam variants, kaju katli, sohan papdi, motichoor laddu), Punjabi/north (gajar halwa, moong dal halwa, pinni, shrikhand, basundi, rabri variants, gulab jamun tin), bakery-western (pastry, pastries, tart, eclair, muffin, doughnut, red velvet, tiramisu, molten lava cake, ice box cake, cheesecake, falooda, kulfi). Also test size/qty noise: 'Gulab Jamun (2 pcs)', 'Rasmalai [Regular]', 'Special Mysore Pak 250g'.
A LEAK is any of these that returns dish_kind=meal (they must be sweet, or beverage for milk-shake-like items). Also flag the reverse: a genuine MEAL name that returns sweet.
Report leaks as structured output; checked_count = names tested. No file edits.`,
  },
  {
    key: 'snacks',
    prompt: `Sweep ${BE}/course.py's dish_kind classification for SNACK leaks. Run e.g.
cd ${BE} && python -c "import course; ci=course.classify('NAME'); print(ci.dish_kind, ci.confidence)"
Test AT LEAST 35 Indian snack names: Gujarati/Marwari (dhokla variants like khaman dhokla, khandvi, fafda, khakhra, mathri, chakli, murukku, sev, bhujia, namkeen, mixture, chivda, poha chivda, farsan, gathiya), Maharashtrian (sabudana vada, kanda bhaji, batata vada, missal—note 'Misal Pav' should stay meal, vada pav should stay meal), chaat family (dahi puri, sev puri, bhel puri, samosa chaat, papdi chaat, raj kachori, aloo tikki, dahi bhalla), pakora family (onion pakora, paneer pakora, bread pakora, mirchi pakora), bakery/street (toast, toastie, bread roll—note a 'Kathi Roll' must stay meal, cheese balls, corn dogs, popcorn, spring rolls), spreads/condiments (peanut butter, hummus, mayo, ketchup, salsa, macaroni salad, russian salad).
A LEAK is any snack-classified item returning dish_kind=meal, OR any genuine standalone meal (misal pav, vada pav, kathi roll, sandwich, burger) returning snack/sweet. Ambiguous breakfast-y snacks (dhokla, thepla, sabudana khichdi) — report got/expected with why, let the next stage decide.
checked_count = names tested. No file edits.`,
  },
  {
    key: 'beverages',
    prompt: `Sweep ${BE}/course.py's dish_kind classification for BEVERAGE leaks. Run e.g.
cd ${BE} && python -c "import course; ci=course.classify('NAME'); print(ci.dish_kind, ci.confidence)"
Test AT LEAST 30 drink names: milk-based (rose milk, badam milk, kesar milk, haldi doodh, turmeric latte, hot chocolate, cold coffee, flavoured milk, banana milkshake, dry fruit shake, protein shake), traditional (thandai, jaljeera, shikanji, nimbu pani, aam panna, sattu drink, bel sharbat, kokum sharbat, lassi variants: sweet/salted/mango/paneer lassi), modern (bubble tea, boba, kombucha, energy drink, green tea, iced tea, americano, cappuccino, espresso, latte, mojito, virgin mojito, mocktail, smoothie, falooda drink), packaged (mineral water, bottled water, soda can, diet coke), plus noise: 'Masala Chai [Cutting]', 'Filter Coffee (Vendhakkam)', 'Cold Drink Combo @ Rs.49'.
A LEAK is any drink returning kind=meal, OR a real food item wrongly returned as beverage (e.g. a 'Milk Cake' dessert is a sweet not a drink — check which way it goes).
checked_count = names tested. No file edits.`,
  },
  {
    key: 'meals-protection',
    prompt: `Sweep ${BE}/course.py's dish_kind classification for FALSE-NEGATIVE leaks — REAL meals wrongly classified as snack/sweet/beverage. This direction shrinks the optimizer's meal pool, so it matters as much as sweet-leaks. Run e.g.
cd ${BE} && python -c "import course; ci=course.classify('NAME'); print(ci.course, ci.dish_kind, ci.confidence)"
Test AT LEAST 35 genuine standalone meal names: South Indian breakfasts (masala dosa variants, ghee roast, set dosa, neer dosa, podi dosa, idli, ragi idli, uttapam, poha, upma, ven pongal, khara pongal, appam—note appam's COURSE may be bread which is fine as long as kind=meal, curd rice, lemon rice, bisi bele bath, sambar rice, puliyodarai), north (chole bhature, chole kulche, rajma chawal, kadhi chawal, dal khichdi, sabudana khichdi, aloo paratha, egg bhurji, omelette, chilla/cheela, veg pulao, tehri, veg meals unlimited, thali variants: mini thali, special thali, non-veg thali), mains (butter chicken, dal makhani, kadai paneer, malai kofta, egg curry), fast food (burger, pizza, wrap, frankie, shawarma, maggi, pasta, hakka noodles, fried rice, momos, tandoori momos), combos (biryani combo, meal box, family combo).
CRITICAL adversarial cases — a sweet/snack/drink WORD embedded in a REAL meal name must NOT demote it: 'Paneer Thali with Gulab Jamun', 'Veg Meals with Sweet', 'Biryani + Raita Combo', 'Burger Combo with Coke', 'Chicken Bucket + Pepsi 750ml', 'Combo Meal (Nachos + Coke + Burger)' — judge what the DOMINANT item is.
A LEAK is any genuine standalone meal returning kind != meal (or course landing it in a non-headline role that breaks it as a main). checked_count = names tested. No file edits.`,
  },
  {
    key: 'live-shapes',
    prompt: `Sweep ${BE}/course.py's dish_kind classification using names SHAPED LIKE THE LIVE SWIGGY CATALOG — heavy branding noise, size tags, bracketed variants, price suffixes. The classifier must see through the noise to the dish itself. Run e.g.
cd ${BE} && python -c "import course; ci=course.classify('NAME'); print(ci.course, ci.dish_kind, ci.confidence)"
Test AT LEAST 30 names modelled on real catalog rows: 'TCP Special Masala Dosa [Regular]', 'Mini Samosa Bucket (6 pcs)', 'Party Pack Chicken Biryani', 'Nachos + Coke Combo @ Rs.49', 'Gulab Jamun Tin (500g)', 'Sweets Combo Box', 'Shree Ganesh Special Mysore Pak 250g', 'Bhoj Special Rasmalai (2 pcs)', 'Punjabi Zzz Special Dhokla', 'Veg Meals (Unlimited)', 'Rajbhog Thali [Mini]', 'Chef's Paneer Butter Masala (Serves 2)', 'Tandoori Roti (Single)', 'Butter Naan [2 pcs]', 'Jain Special Dhokla (No Onion)', 'Bikaji Bhujia 400g', 'Haldiram Soan Papdi', 'Amul Ice Cream Cup', 'Frooti 200ml', 'Mother Dairy Lassi', 'Freshly Brewed Cappuccino', 'Hotel Shree Vada Pav (2 pcs)', 'Kathi Roll - Egg (Cheese Blast)', 'Sardarji Special Chole Bhature', 'Madras Filter Coffee', 'Mysore Masala Dosa', 'Bombay Bhel Puri', 'Cheese Burst Pizza', 'Peri Peri Fries [Medium]', 'Chicken 65', 'Ghee Roast Dosa (Ghee Podi)'.
Judge each by what the dominant dish IS. A LEAK = wrong kind (snack/sweet/drink shown as meal, or a real main demoted). Note borderline calls in why. checked_count = names tested. No file edits.`,
  },
]

const sweeps = await parallel(LENSES.map(l => () =>
  agent(l.prompt + '\n\nReport only real mismatches as leaks; be precise and complete.', { label: 'sweep:' + l.key, phase: 'Sweep', schema: LEAK_SCHEMA })))

const allLeaks = sweeps.filter(Boolean).flatMap(r => r.leaks || [])
const seen = new Set()
const unique = []
for (const l of allLeaks) {
  const k = (l.name || '').toLowerCase().trim()
  if (!k || seen.has(k)) continue
  seen.add(k)
  unique.push(l)
}
log(`Sweep done: ${allLeaks.length} raw leaks, ${unique.length} unique across ${sweeps.filter(Boolean).length} lenses`)
if (unique.length === 0) log('No leaks found — skip extend')

// ---------- Phase 3: Fold leaks into tables ----------
phase('Extend')
let extend = null
if (unique.length > 0) {
  extend = await agent(
`You are extending the dish_kind word tables in ${BE}/course.py to close classification leaks found by an audit sweep.

CONTEXT: course.py classifies Indian menu items on two axes: course (bread|staple|curry|complete|side — the dish's ROLE) and dish_kind (meal|snack|sweet|beverage — its CATEGORY). The optimizer only plans dish_kind=='meal' items into meal slots. Tables that matter:
- _KIND_SWEET_WORDS / _KIND_SNACK_WORDS / _KIND_DRINK_WORDS (~lines 295-340) — whole-word matched by _kind_for() (for course=SIDE items) and by classify()'s default tier.
- _COURSE_KEYWORDS (~line 177) — ingredient keywords per course, incl. the SIDE tuple which catches condiments/drinks by course.
- _STRONG_MEAL_FORMS (~line 281) — forms that survive the drink-combo demotion.
- classify() runs tiers: 0 drink-combo demotion, 1 FORM longest-match, 2 keywords, 3 fuzzy, 4 default. Form matches are decisive; the default tier rescues kind via sweet>drink>snack word checks.

CONFIRMED LEAKS FROM THE SWEEP (JSON: name, expected kind, got kind, why):
${JSON.stringify(unique, null, 2)}

RULES:
1. Fix each leak by extending the _KIND_* word tables (preferred) or _COURSE_KEYWORDS where the COURSE itself is wrong. Match the existing table style — lowercase, multi-word phrases allowed, comments explaining additions.
2. NEVER demote a genuine standalone meal. When a leak is ambiguous (a dish that can be either, e.g. thepla/dhokla as breakfast), prefer the LEAST disruptive choice and note it; if the sweep's expectation looks wrong, skip that item and say why.
3. Watch precedence: sweet before drink before snack in both _kind_for and the default tier; form words beat all keyword tables. A sweet word inside a real meal name ('Paneer Thali with Gulab Jamun') must NOT win — the thali form word should already claim it at tier 1; verify and fix only if it actually misfires.
4. Keep edits minimal and targeted at the leak list — do not refactor, do not touch optimizer/db/app files.
5. Whole-word matching only — check _contains_word semantics before adding a word that could substring-collide (e.g. 'sev' is safe as a word but think about 'sev puri').

VERIFY after your edits (all must hold):
- Every leak name you fixed now classifies to its expected kind: test each with python -c "import course; print('NAME', course.dish_kind_of('NAME'))" from ${BE}.
- Protection list stays meal: ['Paneer Thali','Chicken Biryani','Masala Dosa','Veg Momos','Butter Naan','Tawa Roti','Misal Pav','Vada Pav','Chole Bhature','Rajma Chawal','Butter Chicken','Paneer Butter Masala','Kathi Roll','Burger','Pizza','Poha','Upma','Appam','Thepla','Veg Meals (Unlimited)','Special Thali'] — none may become snack/sweet/beverage (Thepla/Appam may be course=bread, that's fine — kind must stay meal).
- cd ${BE} && python test_course.py (39/39) and python test_quality.py (7/7) and python test_veg_budget.py (8/8) all pass.
Return ok=true + summary of what you added/skipped, or ok=false with the blocker.`,
    { label: 'extend:tables', phase: 'Extend', schema: OK_SCHEMA })
  log('Extend: ' + (extend ? extend.summary : 'AGENT FAILED'))
}

// ---------- Phase 4: Verify ----------
phase('Verify')
const VERIFY_SCHEMA = {
  type: 'object',
  properties: {
    ok: { type: 'boolean' },
    details: { type: 'string' },
    suites: { type: 'array', items: { type: 'object', properties: {
      file: { type: 'string' }, passed: { type: 'string' } }, required: ['file', 'passed'] } },
  },
  required: ['ok', 'details'],
}

const verifyResults = await parallel([
  () => agent(
`You are adding golden-list regression tests for the dish_kind classification work just completed in ${BE}.

CONTEXT: backend/test_course.py already has golden-list tests (test_sweets_never_meal_kind, test_snacks_never_meal_kind, test_beverages_never_meal_kind, test_thali_combo_is_complete_meal, test_dessert_platter_is_not_meal, test_momos_is_meal_not_snack, test_gulab_jamun_is_sweet_not_meal). The file is self-running: tests are discovered via sorted(globals()) and run via a local _run helper printing PASS/FAIL lines; exit 1 on any failure. Read the file first and match its exact style.

TASK — extend backend/test_course.py with the newly-covered dishes:
1. Extend the golden lists inside the existing test functions (NOT new functions where an existing one fits):
   - sweets: add Mishti, Pastry, Pastries, Custard, Shrikhand, Motichoor, Ghevar, Puran Poli, Mysore Pak, Boondi, Falooda, Kaju Katli, Sohan Papdi, Chum Chum
   - beverages: add Rose Milk, Badam Milk, Cold Coffee, Iced Tea, Green Tea, Mineral Water, Sugarcane Juice
   - snacks: add Dhokla, Khandvi, Fafda, Bonda, Bhujia, Namkeen, Sev, Peanut Butter, Toast, Macaroni, Khakhra, Chakli, Mathri, Farsan, Hummus, Ketchup
2. Add ONE new protection test, test_meal_names_survive_sweet_and_drink_words: ['Paneer Thali with Gulab Jamun', 'Veg Meals with Sweet', 'Burger Combo with Coke', 'Chicken Bucket + Pepsi 750ml', 'Biryani + Raita Combo', 'Misal Pav', 'Vada Pav', 'Chole Kulche'] must all classify with dish_kind == course.KIND_MEAL (use course.classify(n).dish_kind). NOTE: verify each of these actually passes with a quick python -c check BEFORE adding to the test; if one of them genuinely fails in current code (e.g. the drink-combo demotion fires wrongly), report it in details rather than adding a failing assertion.
3. Run the FULL suite loop from ${BE}: for f in test_*.py; do echo "=== $f ==="; python "$f" 2>&1 | tail -2; done
ALL 13 suites must pass (test_course should now report more than 39 tests). If any suite fails, fix ONLY test_course.py list contents (drop a name that is genuinely ambiguous) — never edit course.py or other backend source; a dropped name goes into details with why.
Return ok=true when all suites green; details = per-suite pass counts + any names you dropped and why.`,
    { label: 'verify:golden+suite', phase: 'Verify', schema: VERIFY_SCHEMA }),
  () => agent(
`You are the ADVERSARIAL verifier for dish_kind classification in ${BE}/course.py. Independent re-check — do NOT trust the earlier fixes; assume something still leaks.

DO (read-only — no edits to any file):
1. Generate your OWN fresh list of 40+ Indian dish names the earlier sweeps likely missed (regional sweets, festival foods, packaged snack brands, café drinks, Indo-Chinese, Tibetan/Nepali momos-thukpa, hyderabadi, coastal) and classify each: cd ${BE} && python -c "import course; ci=course.classify('NAME'); print(ci.course, ci.dish_kind, ci.confidence)". Flag wrong kinds both directions (non-meal shown as meal; real meal demoted).
2. Run the optimizer purity check per appetite with a synthetic catalog mixing kinds — construct dishes via the pattern in ${BE}/test_quality.py (_d helper + replace(dish, course=..., dish_kind=...)) or directly Dish(...); for each appetite level light/moderate/heavy/very_heavy run optimize(cat, profile, 25000, days=10) and assert zero slots with dish_kind != 'meal'. Also assert light gets 0 sides, moderate/heavy get some sides.
3. Spot the persistence path: python -c "import db, plan_service" imports clean; python -m py_compile on course.py optimizer.py.
4. Run: python test_swap.py and python test_optimizer.py from ${BE}.
Report ok=true if ZERO wrong-kind leaks found AND purity holds for all four appetites AND both test files pass; details = everything you checked with counts, and any leaks with name/expected/got. If leaks exist, ok=false with the full leak list.`,
    { label: 'verify:adversarial', phase: 'Verify', schema: VERIFY_SCHEMA }),
])

const [golden, adversarial] = verifyResults
log('Golden+suite: ' + (golden ? (golden.ok ? 'GREEN' : 'ISSUES: ' + golden.details.slice(0, 200)) : 'FAILED'))
log('Adversarial: ' + (adversarial ? (adversarial.ok ? 'CLEAN' : 'LEAKS: ' + adversarial.details.slice(0, 200)) : 'FAILED'))

return {
  fix: fix ? fix.summary : 'FAILED',
  leaks_found: unique.length,
  extend: extend ? extend.summary : 'not needed',
  golden: golden ? { ok: golden.ok, details: golden.details } : 'FAILED',
  adversarial: adversarial ? { ok: adversarial.ok, details: adversarial.details } : 'FAILED',
}