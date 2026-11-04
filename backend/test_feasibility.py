"""Tests for feasibility probes matching plan-generation filters."""
from types import SimpleNamespace

import feasibility


def test_analyse_passes_same_taste_profile_to_every_probe(monkeypatch):
    taste = object()
    seen = []

    def fake_optimize(catalog, profile, budget, **kwargs):
        seen.append(kwargs.get("taste_profile"))
        return SimpleNamespace(total_cost=10.0, constraint_status={})

    monkeypatch.setattr(feasibility, "optimize", fake_optimize)

    result = feasibility.analyse(
        catalog=[],
        profile_builder=lambda user_id, level: object(),
        user_id=1,
        appetite_level="moderate",
        budget=1000,
        days=2,
        meals=("lunch",),
        taste_profile=taste,
    )

    assert result["feasible"] is True
    assert seen
    assert all(profile is taste for profile in seen)
