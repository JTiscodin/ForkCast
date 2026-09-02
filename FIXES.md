# Critical Fixes for Swiggy-Builder Planning Issues

## Issues Found

### 1. Classification Bug: Sweet dishes passing meal filter
**Problem**: "Chena Toast" is `course=complete, kind=sweet` - the optimizer only checks `dish_kind == KIND_MEAL`, so sweets with complete course leak through.

**Root cause**: Line 216-220 in optimizer.py filters by `dish_kind` but course=COMPLETE overrides it.

### 2. Constraint Parser Missing Pattern
**Problem**: Parser doesn't understand:
- "dessert with dinner always"
- "drinks with lunch every day"  
- "sweet after every meal"

**Root cause**: intake.py only recognizes "N dish_tag meals" pattern (line 36-39)

### 3. No Per-Slot-Type Constraints
**Problem**: Can't enforce "dessert ONLY with dinner" or "beverage ONLY with breakfast"

**Root cause**: Constraint system has no `slot_type` field

### 4. Repetition Problems
**Multiple causes**:
- Small catalog pools
- Variety guards can be bypassed
- No "must vary" enforcement per constraint

## Solution Plan

### Fix 1: Classification Filter (CRITICAL)
Tighten the meal filter to REJECT any dish with `dish_kind != KIND_MEAL` regardless of course.

### Fix 2: Enhanced Constraint Parser
Add support for:
```python
{
  "dish_kind": "sweet",     # NEW: kind-based constraint
  "slot_type": "dinner",    # NEW: which meal slot(s)
  "frequency": "always"     # NEW: every occurrence vs min_count
}
```

### Fix 3: Slot-Specific Pairing System
New function: `plan_with_pairings(main_slots, pairing_constraints)`
- Fill main meal slots first
- Then add pairings (dessert/drink) that don't blow budget

### Fix 4: Stronger Variety
- Never allow same dish >2 times in any 7-day window
- Force rotation through ALL matching dishes before repeating
- Add "variety_score" that penalizes recent use exponentially
