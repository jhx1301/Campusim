"""Episode identity, changed run configuration, and rollback in sequential training."""

import json
from types import SimpleNamespace

import pytest

from cemas.control.learning import train_memory
from cemas.control.learning_store import LearningMemoryStore
from cemas.control.snapshot_protocol import load_training_protocol, history_seeds
from test_control_feedback import add_weeks


def test_resume_reorder_append_and_changed_configuration(tmp_path):
    protocol = load_training_protocol("docs/baseline_snapshot_training_v1.json")
    world = history_seeds(protocol, "train")[0]
    snapshot = tmp_path / f"{world}-21.json"
    snapshot.write_text(json.dumps({"split": "train", "history_seed": world, "snapshot_day": 21}), encoding="utf-8")
    def episode(identity, seed):
        return {"episode_id": identity, "world_seed": world,
                "scenario_options": {"snapshot_path": str(snapshot), "future_seed": seed}}
    calls, configs = [], []
    def factory(protocol, learning_store, **settings):
        configs.append(settings)
        return SimpleNamespace(store=learning_store)
    def run(protocol, controller, output, world, **kwargs):
        calls.append(controller.store.episode_id)
        add_weeks(controller.store, 1)
        output.mkdir()
        if controller.store.episode_id == "fail":
            raise RuntimeError("fatal after writing")
        return SimpleNamespace(output_dir=output)
    library = tmp_path / "library.sqlite"
    def train(entries, settings):
        return train_memory(protocol, entries, library, tmp_path / "runs", settings, "fixture-anchor",
                            controller_factory=factory, run=run)
    train([episode("a", 1), episode("b", 2)], {"provider": "old"})
    result = train([episode("b", 2), episode("a", 1), episode("c", 3)], {"provider": "new", "memory_profile_path": "new-template"})
    assert calls == ["a", "b", "c"]
    assert [r["status"] for r in result] == ["already_completed", "already_completed", "completed"]
    assert configs[-1]["provider"] == "new"
    with pytest.raises(Exception, match="different scenario"):
        train([episode("a", 99)], {})
    with pytest.raises(RuntimeError, match="fatal"):
        train([episode("fail", 4)], {})
    reader = LearningMemoryStore(library)
    assert len(reader.cases()) == 3
    assert reader.begin_episode("fail", "new-scenario")
    reader.rollback()
    reader.close()
