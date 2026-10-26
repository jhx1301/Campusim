"""W2-only loss, exact tie-breaking and immutable E0 regression checks."""

from copy import deepcopy

import pytest

from cemas.e0.data import load_e0_config
from cemas.replay.study import load_replay_data, select_c, slice_data, w2_loss, _w1_signature


def _world(data):
    return {"dates": list(data["dates"]), "groups": {
                group: {field: list(values) for field, values in fields.items()}
                for group, fields in data["groups"].items()},
            "requested_tests": [a + b for a, b in zip(data["groups"]["students"]["tests"],
                                                       data["groups"]["employees"]["tests"])],
            "roles": {"students": 45540, "employees": 23917},
            "group_test_weights": {"students": 1.3, "employees": .2}}


def test_w2_loss_aligns_before_slicing_and_ignores_other_observation_windows():
    data = load_replay_data(load_e0_config("docs/e0_protocol_v2.json"))
    # Construct raw positives that align exactly with the 19 W2 report dates.
    world = _world(data)
    for group in ("students", "employees"):
        observed = list(data["groups"][group]["positive"])
        world["groups"][group]["positive"] = observed[1:] + [0]
    assert w2_loss(world, data) == 0
    changed = deepcopy(data)
    for group in ("students", "employees"):
        counts = list(changed["groups"][group]["positive"])
        counts[:21] = [999] * 21
        counts[40:] = [777] * 35
        changed["groups"][group]["positive"] = counts
    assert w2_loss(world, changed) == 0
    # Raw 9/6 positives report on 9/7 and must enter W2's first residual.
    world["groups"]["students"]["positive"][20] += 1
    assert w2_loss(world, data) == pytest.approx(19 / 1404 ** 2)


def test_select_c_averages_per_world_losses_and_breaks_exact_ties_upward():
    records = [{"h": 1.15, "c": c, "seed": seed, "loss": loss}
               for c, losses in ((0, [4, 4]), (.2, [0, 2]), (.4, [1, 1]), (1, [8, 8]))
               for seed, loss in zip((12101, 12102), losses)]
    selected = select_c(records, 1.15)
    assert selected["best_c"] == .4
    assert selected["best_loss"] == 1
    assert selected["identifiable"] is False
    assert selected["one_se_cs"] == [.2, .4]
    # Other fixed dormitory assumptions cannot enter this profile.
    records.extend({"h": 1.0, "c": 1, "seed": seed, "loss": 0} for seed in (12101, 12102))
    assert select_c(records, 1.15) == selected


def test_boundary_and_recovery_order_are_reported():
    records = [{"h": 1.15, "c": c, "seed": seed, "loss": loss}
               for c, loss in ((0, 3), (.6, 2), (1, 1)) for seed in (12101, 12102)]
    selected = select_c(records, 1.15)
    assert selected["best_c"] == 1
    assert selected["boundary_best"]
    assert selected["recovery_order_inconsistent"]
    assert not selected["identifiable"]


def test_w1_signature_and_slicing_leave_the_input_unchanged():
    data = load_replay_data(load_e0_config("docs/e0_protocol_v2.json"))
    original = deepcopy(data)
    short = slice_data(data, 40)
    assert len(short["dates"]) == 40
    assert data == original
    world = _world(short)
    before = _w1_signature(world)
    world["groups"]["students"]["positive"][30] += 1
    assert _w1_signature(world) == before
    world["groups"]["students"]["tests"][20] += 1
    assert _w1_signature(world) != before


def test_full_orchestration_preserves_stage_counts_and_frozen_selection(tmp_path, monkeypatch):
    from contextlib import nullcontext
    from types import SimpleNamespace
    from cemas.replay import study, reporting

    anchor_path = tmp_path / "control_anchor.json"
    anchor_path.write_text("{}", encoding="utf-8")
    for stage in ("fit", "evaluation"):
        (tmp_path / f"worlds_{stage}.jsonl").write_text("", encoding="utf-8")
    anchor = SimpleNamespace(beta=.056666666665, sha256="test-anchor", payload={
        "compatibility": {"source_sha256": {}, "runtime": {"python": "test", "packages": {}}}})
    monkeypatch.setattr(study, "load_calibration_artifact", lambda *args: anchor)
    monkeypatch.setattr(study, "_references", lambda *args: {
        seed: {} for seed in list(range(12101, 12121)) + list(range(12201, 12241))})
    calls = []

    def fake_stage(pool, config, data, beta, specs, output, stage, references):
        calls.append((stage, len(data["dates"]), specs))
        world = _world(data)
        return [{**spec, "world": world, "loss": (spec["c"] - .35) ** 2,
                 "w1_exact_match": True} for spec in specs]

    monkeypatch.setattr(study, "_run_stage", fake_stage)
    monkeypatch.setattr(study, "ProcessPoolExecutor", lambda **kwargs: nullcontext(None))
    monkeypatch.setattr(reporting, "summarize_worlds", lambda worlds, data: {})
    monkeypatch.setattr(reporting, "write_report", lambda *args: None)
    summary = study.run_replay_study(anchor_path, tmp_path / "output", workers=1)
    assert [(stage, days, len(specs)) for stage, days, specs in calls] == [
        ("fixed_w2", 40, 120), ("fit", 40, 1260), ("evaluation", 75, 480)]
    assert all(profile["best_c"] == .35 for profile in summary["profiles"])
    assert summary["worlds_completed"] == 1860
    assert len(summary["scenarios"]) == 12
    fit_seeds = {r["seed"] for r in calls[1][2]}
    evaluation_seeds = {r["seed"] for r in calls[2][2]}
    assert not fit_seeds & evaluation_seeds
    assert fit_seeds == set(range(12101, 12121))
    assert evaluation_seeds == set(range(12201, 12241))
    assert {r["recovery"] for r in calls[2][2]} == {.25, .5, .75}
