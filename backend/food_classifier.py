"""Enhanced food classifier — bridges course.py name-rules and food_knowledge.py.

Course.py matches any name string to a course+kind, but knows nothing about the
item's serving unit, satiety, or meal-eligibility. food_knowledge.py knows
specific items but not arbitrary names. This module joins them:

  classify(name):
    1. food_knowledge.lookup(name)  -- if known, its metadata is authoritative
    2. else delegate to course.classify(name)  -- keyword/fuzzy/default
    3. use food_knowledge ONLY to override kind when course.py defaulted to meal

The critical output is `main_meal_eligible`: items the knowledge base
explicitly marks as not-ground-meal cannot headline a meal slot, no matter what
course.py said. A "Chhena Toast" that course.py defaults to COMPLETE/meal is
forced sweet/non-eligible here.
"""
from __future__ import annotations
from dataclasses import dataclass

import course as course_rules
import food_knowledge as fk


@dataclass(frozen=True)
class FoodInfo:
    dish_id: str = ""
    name: str = ""
    course: str = course_rules.COMPLETE
    dish_kind: str = course_rules.KIND_MEAL
    source: str = "course_rules"    # food_knowledge | course_rules | default
    main_meal_eligible: bool = True  # can this headline a meal slot?
    serving_unit: str = ""
    satiety: float = 0.5
    confidence: str = "default"


def classify(dish_id: str = "", name: str = "") -> FoodInfo:
    """Classify a dish by name, consulting food knowledge first."""
    entry = fk.lookup(name)

    if entry is not None:
        # Knowledge entry is authoritative on kind, course, and meal eligibility.
        return FoodInfo(
            dish_id=dish_id,
            name=name,
            course=entry.course,
            dish_kind=entry.dish_kind,
            source="food_knowledge",
            main_meal_eligible=entry.main_meal_eligible,
            serving_unit=entry.serving_unit,
            satiety=entry.satiety,
            confidence="knowledge",
        )

    # No knowledge entry — fall through to course.py.
    info = course_rules.classify(name)
    return FoodInfo(
        dish_id=dish_id,
        name=name,
        course=info.course,
        dish_kind=info.dish_kind,
        source="course_rules",
        main_meal_eligible=info.course in course_rules.STANDALONE,
        serving_unit="",
        satiety=0.5,
        confidence=info.confidence,
    )


def classify_instamart(item: dict, query_kind: str) -> FoodInfo:
    """Classify an Instamart normalized product row.

    `query_kind` is the bucket the search came from (beverage/sweet/snack);
    it is only a fallback when the name can't be classified and food_knowledge
    has no entry — categorize()'s default of "meal" must never survive on a
    grocery row or it would headline a meal slot.
    """
    name = item.get("name", "")
    # Knowledge first: a canned "amul lassi" resolves definitively.
    entry = fk.lookup(name)
    if entry is not None:
        return FoodInfo(
            dish_id=item.get("id", ""),
            name=name,
            course=entry.course,
            dish_kind=entry.dish_kind,
            source="food_knowledge",
            main_meal_eligible=entry.main_meal_eligible,
            serving_unit=entry.serving_unit,
            satiety=entry.satiety,
            confidence="knowledge",
        )

    info = course_rules.classify(name)
    # Groceries can never headline meals; if course.py called it kind=meal
    # and it's not a strong meal form, pin it to the query bucket.
    kind = info.dish_kind
    if kind == course_rules.KIND_MEAL:
        kind = query_kind if query_kind in course_rules.KINDS else course_rules.KIND_SNACK
    return FoodInfo(
        dish_id=item.get("id", ""),
        name=name,
        course=info.course,
        dish_kind=kind,
        source="course_rules",
        main_meal_eligible=False,
        serving_unit="",
        satiety=0.5,
        confidence=info.confidence,
    )


def enrich_dish(dish) -> FoodInfo:
    """Enrich an existing Dish object with FoodInfo metadata.

    Returns FoodInfo only; caller copies fields onto the Dish if desired.
    """
    info = classify(dish.dish_id, dish.name)
    if info.source == "food_knowledge":
        return info
    # For a course-rules result, keep the Dish's own course/kind (they were
    # already computed the same way) but derive meal eligibility.
    return FoodInfo(
        dish_id=dish.dish_id,
        name=dish.name,
        course=dish.course,
        dish_kind=dish.dish_kind,
        source=info.source,
        main_meal_eligible=dish.course in course_rules.STANDALONE,
        serving_unit=info.serving_unit,
        satiety=info.satiety,
        confidence=info.confidence,
    )


def main_meal_eligible(name: str) -> bool:
    """Convenience: can this item headline a meal slot?"""
    return classify("", name).main_meal_eligible
