"""Next Best Action: a selector over ComputedFacts that never invents numbers."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from greeniq.context import load_context
from greeniq.contract import Property
from greeniq.engines.nba import select_next_best_action
from greeniq.pipeline import analyse_home

FIXTURES = {f["property"]["property_id"]: f for f in
            json.loads((Path(__file__).parent / "fixtures" / "sample_properties.json").read_text())}


@pytest.fixture(scope="module")
def ctx():
    return load_context(with_models=False)


def run(ctx, pid, prop_changes=None, **kw):
    prop = {**FIXTURES[pid]["property"], **(prop_changes or {})}
    return analyse_home(Property(**prop), ctx, **kw)


def resolve(obj, path: str):
    """Follow a fact_ref like 'plan[3].standalone.carbon' through the facts JSON."""
    for name, idx in re.findall(r"([a-z_]+)(?:\[(\d+)\])?", path):
        obj = obj[name]
        if idx:
            obj = obj[int(idx)]
    return obj


@pytest.mark.parametrize("pid", list(FIXTURES))
def test_three_reasons_each_traced_to_a_real_fact(ctx, pid):
    f = run(ctx, pid)
    n = f.next_best_action
    assert n is not None and len(n.reasons) == 3
    assert len({r.code for r in n.reasons}) == 3
    data = f.model_dump(mode="json")
    for r in n.reasons:
        assert resolve(data, r.fact_ref) is not None, r.fact_ref


@pytest.mark.parametrize("pid", list(FIXTURES))
def test_never_selects_an_excluded_or_unplanned_measure(ctx, pid):
    f = run(ctx, pid)
    n = f.next_best_action
    if n.action.kind == "retrofit":
        assert n.action.ref in {r.measure_id for r in f.plan}
        assert n.action.ref not in {e.measure_id for e in f.excluded}


@pytest.mark.parametrize("pid", list(FIXTURES))
def test_respects_prerequisites(ctx, pid):
    f = run(ctx, pid)
    n = f.next_best_action
    if n.action.kind == "retrofit":
        chosen = next(r for r in f.plan if r.measure_id == n.action.ref)
        pending = {r.measure_id for r in f.plan}
        assert not set(chosen.depends_on) & pending


def test_heat_pump_not_first_while_fabric_pending_but_eligible_once_done(ctx):
    f = run(ctx, "FX-HP-CANDIDATE", constraints={"objective": "carbon"})
    assert f.next_best_action.action.ref != "air_source_heat_pump"  # the biggest carbon cut, but fabric comes first
    done = [r.measure_id for r in f.plan if r.measure_id != "air_source_heat_pump" and r.stage == 1]
    g = run(ctx, "FX-HP-CANDIDATE", constraints={"completed_measures": done, "objective": "carbon"})
    assert g.next_best_action.action.ref == "air_source_heat_pump"


def test_refers_for_survey_on_a_high_severity_conflict(ctx):
    n = run(ctx, "FX-CONFLICT").next_best_action
    assert n.disposition == "refer_for_survey" and n.action.kind == "survey"
    assert n.blocked_by


def test_asks_how_the_home_is_heated_when_unknown(ctx):
    f = run(ctx, "FX-POOR-SEMI", {"heating_system": None, "boiler_age_years": None})
    n = f.next_best_action
    assert n.disposition == "refer_for_survey"
    assert n.action.kind == "answer_question" and n.action.ref == "heating_system"


def test_no_action_for_a_void_home_and_an_efficient_home(ctx):
    assert run(ctx, "FX-VOID-ZERO").next_best_action.disposition == "no_action"
    assert run(ctx, "FX-LARGE-EFFICIENT").next_best_action.disposition == "no_action"


def test_declined_measure_is_never_selected(ctx):
    first = run(ctx, "FX-POOR-SEMI").next_best_action.action.ref
    g = run(ctx, "FX-POOR-SEMI", constraints={"declined_measures": [first]})
    assert g.next_best_action.action.ref != first


def test_selector_computes_no_new_numbers(ctx):
    """Re-selecting on the same facts is deterministic and leaves the facts untouched."""
    f = run(ctx, "FX-POOR-SEMI")
    before = f.model_dump_json(exclude={"next_best_action"})
    a = select_next_best_action(f)
    assert a == f.next_best_action
    assert f.model_dump_json(exclude={"next_best_action"}) == before


def test_unknown_objective_is_rejected(ctx):
    with pytest.raises(ValueError):
        select_next_best_action(run(ctx, "FX-POOR-SEMI"), "fastest")
