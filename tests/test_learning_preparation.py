"""Offline preparation must preserve scenarios without starting any learning."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from examples.control_v1 import prepare_learning as preparation


def scenario(world, day=21):
    return {"world_seed": world, "scenario_options": {
        "snapshot_path": f"{world}-{day}.json", "future_seed": world * 100 + day,
        "screening_capacity_ratio": .05, "calibration_artifact": "anchor.json",
        "calibration_data_path": None}}


def install_plan(monkeypatch, scenarios):
    calls = []

    class Plan:
        def __init__(self, protocol, seed, artifact, data_path):
            calls.append((protocol, seed, artifact, data_path))
            self.items = scenarios
            self.index = 0

        def __call__(self):
            value = self.items[self.index]
            self.index += 1
            return value

    monkeypatch.setattr(preparation, "SnapshotEpisodePlan", Plan)
    return calls


def test_unique_world_selection_keeps_first_scenario_values(monkeypatch):
    scenarios = [scenario(100, 35), scenario(100, 21), scenario(200, 63)]
    calls = install_plan(monkeypatch, scenarios)
    actual = preparation.select_unique_world_episodes("protocol", 11, "anchor", "data", count=2)
    assert calls == [("protocol", 11, "anchor", "data")]
    assert [row["world_seed"] for row in actual] == [100, 200]
    assert [row["episode_id"] for row in actual] == ["llm-seed11-episode001", "llm-seed11-episode002"]
    assert actual[0]["scenario_options"] == {
        "snapshot_path": "100-35.json", "future_seed": 10035, "screening_capacity_ratio": .05}
    assert "calibration_artifact" in scenarios[0]["scenario_options"]


def test_64_episode_schedule_is_deterministic_and_world_disjoint_between_batches(monkeypatch):
    scenarios = [item for world in range(64) for item in (scenario(world, 35), scenario(world, 21))]
    install_plan(monkeypatch, scenarios)
    first = preparation.select_unique_world_episodes("protocol", 22, "anchor")
    second = preparation.select_unique_world_episodes("protocol", 22, "anchor")
    assert first == second
    assert len(first) == 64
    assert first[-1]["episode_id"] == "llm-seed22-episode064"
    earlier = {row["world_seed"] for row in first[:32]}
    later = {row["world_seed"] for row in first[32:]}
    assert len(earlier) == len(later) == 32
    assert earlier.isdisjoint(later)


def test_insufficient_unique_worlds_fails_instead_of_repeating_schedule(monkeypatch):
    install_plan(monkeypatch, [scenario(100, 21), scenario(100, 35)])
    with pytest.raises(ValueError, match="only 1 distinct eligible training worlds; need 2"):
        preparation.select_unique_world_episodes("protocol", 33, "anchor", count=2)


@pytest.fixture
def prepared_inputs(tmp_path, monkeypatch):
    from cemas.control import knowledge, learning, llm, memory, runner, snapshots
    from cemas.e0 import artifacts

    library = tmp_path / "snapshots"
    library.mkdir()
    catalog = {"identity": {"recipe": "fixture"}, "snapshots": {}}

    def entry(world, split):
        metadata = {"history_seed": world, "snapshot_day": 21, "split": split,
                    "state_file": f"{world}-21.pkl"}
        path = library / f"{world}-21.json"
        path.write_text(json.dumps(metadata), encoding="utf-8")
        path.with_suffix(".pkl").write_bytes(b"not a pickle: preparation must not deserialize")
        catalog["snapshots"][path.name] = {key: metadata[key] for key in ("history_seed", "snapshot_day", "split")}
        return {"world_seed": world, "scenario_options": {
            "snapshot_path": str(path), "future_seed": world + 50, "screening_capacity_ratio": .05}}

    training = [entry(1000 + index, "train") for index in range(64)]
    evaluation = {split: [entry(world, split)] for split, world in (("val", 20101), ("test", 50001))}
    (library / "snapshots_manifest.json").write_text(json.dumps(catalog), encoding="utf-8")
    protocol = SimpleNamespace(source_sha256="protocol-digest", execution_days=119,
        definition={"snapshot_training": {"library": "snapshots", "observation_days": 7, "control_days": 112},
                    "source": {"train_seed_values": [11, 22, 33]}})
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps({"provider": "deepseek", "endpoint": "https://api.deepseek.com",
        "api_key_env": "PREPARATION_TEST_CREDENTIAL", "tokenizer_manifest": str(tmp_path / "tokenizer.json"),
        "memory_mode": "both", "feedback_backend": "llm", "rule_memory": "adaptive"}), encoding="utf-8")
    monkeypatch.setenv("PREPARATION_TEST_CREDENTIAL", "secret-must-not-be-written")
    validations = []

    class Counter:
        identity = {"manifest_sha256": "tokenizer-digest"}

        def __init__(self, path):
            pass

        def validate(self, settings):
            validations.append(settings)

    def forbidden(*args, **kwargs):
        pytest.fail("Preparation started a model call, learning, or snapshot restoration")

    monkeypatch.setattr(preparation, "ROOT", tmp_path)
    monkeypatch.setattr(preparation, "load_training_protocol", lambda path: protocol)
    monkeypatch.setattr(preparation, "select_unique_world_episodes", lambda p, seed, *args: [
        {"episode_id": f"llm-seed{seed}-episode{index + 1:03d}", **row} for index, row in enumerate(training)])
    monkeypatch.setattr(preparation, "snapshot_scenarios", lambda p, split: evaluation[split])
    monkeypatch.setattr(preparation.subprocess, "check_output", lambda *args, **kwargs: "source-commit\n")
    monkeypatch.setattr(llm, "OfficialInputTokenCounter", Counter)
    monkeypatch.setattr(llm.LLMTransport, "complete", forbidden)
    monkeypatch.setattr(learning, "train_memory", forbidden)
    monkeypatch.setattr(snapshots, "restore_snapshot", forbidden)
    monkeypatch.setattr(runner, "make_llm_settings", lambda *args, **kwargs: SimpleNamespace(
        input_token_budget=131072, request_parameters=lambda: {"model": "deepseek-flash", "max_tokens": 131072}))
    monkeypatch.setattr(memory, "load_memory_profile", lambda path: SimpleNamespace(resource_path=lambda key: "knowledge.json"))
    monkeypatch.setattr(knowledge, "load_knowledge_bundle", lambda path: SimpleNamespace(sha256="knowledge-digest"))
    monkeypatch.setattr(artifacts, "load_calibration_artifact", lambda *args, **kwargs: SimpleNamespace(sha256="anchor-digest"))
    monkeypatch.setattr(snapshots, "snapshot_identity", lambda *args: catalog["identity"])
    return SimpleNamespace(settings=settings_path, root=tmp_path, validations=validations,
                           training=training, evaluation=evaluation)


def test_prepare_writes_cumulative_checkpoints_and_independent_paths_without_learning(prepared_inputs):
    inputs = prepared_inputs
    output = inputs.root / "prepared"
    manifest = preparation.prepare_experiment("protocol.json", inputs.settings, "anchor.json", output)
    assert manifest["status"] == "prepared"
    assert manifest["model_calls"] == 0 and manifest["training_started"] is False
    assert len(inputs.validations) == 1
    assert manifest["total_days"] == 119
    assert [row["seed"] for row in manifest["seeds"]] == [11, 22, 33]
    assert len({row["library"] for row in manifest["seeds"]}) == 3
    assert not list(output.rglob("*.sqlite"))
    for seed in manifest["seeds"]:
        checkpoints = seed["checkpoints"]
        rows = [json.loads(Path(checkpoint["episodes_path"]).read_text(encoding="utf-8")) for checkpoint in checkpoints]
        assert [len(part) for part in rows] == [16, 32, 64]
        assert rows[0] == rows[2][:16] and rows[1] == rows[2][:32]
        assert all(batch["distinct_worlds"] == 32 for batch in seed["batches"])
        assert {row["world_seed"] for row in rows[2]}.isdisjoint({20101, 50001})
        assert not Path(seed["library"]).exists()
    assert manifest["checks"]["training_worlds_disjoint_from_evaluation"] is True
    assert "secret-must-not-be-written" not in "".join(path.read_text(encoding="utf-8") for path in output.rglob("*.json"))


def test_only_selected_seed_uses_low_configuration(prepared_inputs, monkeypatch):
    calls = []

    def low(protocol, settings, directory):
        calls.append(directory)
        return {"protocol_path": "low-protocol.json", "settings_path": "low-settings.json",
                "request_parameters": {"extra_body": {"reasoning_effort": "low"}}}

    monkeypatch.setattr(preparation, "prepare_low_reasoning", low)
    manifest = preparation.prepare_experiment("protocol.json", prepared_inputs.settings,
        "anchor.json", prepared_inputs.root / "mixed", low_reasoning_seed=33)
    first, second, third = manifest["seeds"]
    assert first["protocol_path"] == second["protocol_path"] == manifest["protocol_path"]
    assert first["settings_path"] == second["settings_path"] == manifest["settings_path"]
    assert third["protocol_path"] == "low-protocol.json"
    assert third["settings_path"] == "low-settings.json"
    assert len(calls) == 1 and calls[0].parent.name == "seed33"


def test_low_configuration_binds_input_mode_without_changing_high_resources(tmp_path, monkeypatch):
    from cemas.control import llm
    from cemas.control.runner import make_llm_settings
    from cemas.control.snapshot_protocol import load_training_protocol

    source = tmp_path / "high-tokenizer"
    source.mkdir()
    (source / "tokenizer.json").write_text("fixture", encoding="utf-8")
    original = {"files": {"tokenizer.json": "fixture-hash"},
                "template_kwargs": {"reasoning_effort": "high"},
                "input_tokenization_sha256": "high-hash"}
    (source / "manifest.json").write_text(json.dumps(original), encoding="utf-8")

    class Counter:
        identity = {"manifest_sha256": "low-hash"}

        def __init__(self, path):
            self.manifest = json.loads(Path(path).read_text(encoding="utf-8"))

        def validate(self, settings):
            assert self.manifest["template_kwargs"]["reasoning_effort"] == settings.primary_effort == "low"
            assert self.manifest["input_tokenization_sha256"] == preparation.snapshot_sha256(
                settings.input_tokenization_parameters())

    monkeypatch.setattr(llm, "OfficialInputTokenCounter", Counter)
    protocol = load_training_protocol("docs/baseline_snapshot_training_v1.json")
    settings = {"provider": "deepseek", "endpoint": "https://api.deepseek.com",
                "api_key_env": "TEST_KEY", "tokenizer_manifest": str(source / "manifest.json")}
    result = preparation.prepare_low_reasoning(protocol, settings, tmp_path / "low")
    low = load_training_protocol(result["protocol_path"])
    actual = make_llm_settings(low, provider="deepseek", endpoint=settings["endpoint"], api_key_env="TEST_KEY")
    assert actual.primary_effort == "low" and actual.max_output_tokens == 131072
    assert protocol.definition["controllers"]["llm"]["primary_effort"] == "high"
    assert low.definition["snapshot_training"]["replay_parameters"] == protocol.definition["snapshot_training"]["replay_parameters"]
    assert json.loads((source / "manifest.json").read_text(encoding="utf-8")) == original
    assert (tmp_path / "low/tokenizer/tokenizer.json").read_bytes() == (source / "tokenizer.json").read_bytes()


def test_prepare_refuses_existing_output_without_touching_it(prepared_inputs):
    output = prepared_inputs.root / "already-prepared"
    output.mkdir()
    marker = output / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    with pytest.raises(FileExistsError, match="new directory"):
        preparation.prepare_experiment("protocol.json", prepared_inputs.settings, "anchor.json", output)
    assert marker.read_text(encoding="utf-8") == "keep"
    assert prepared_inputs.validations == []


def test_prepare_rejects_training_evaluation_overlap_before_creating_output(prepared_inputs):
    inputs = prepared_inputs
    inputs.evaluation["val"] = [inputs.training[0]]
    output = inputs.root / "overlap"
    with pytest.raises(ValueError, match="Training and evaluation worlds overlap"):
        preparation.prepare_experiment("protocol.json", inputs.settings, "anchor.json", output)
    assert not output.exists()


@pytest.mark.parametrize("failure", ["missing_state", "wrong_world"])
def test_snapshot_preparation_rejects_missing_or_misidentified_resources(tmp_path, failure):
    path = tmp_path / "100-21.json"
    path.write_text(json.dumps({"history_seed": 101 if failure == "wrong_world" else 100,
        "state_file": "100-21.pkl", "snapshot_day": 21, "split": "train"}), encoding="utf-8")
    if failure != "missing_state":
        path.with_suffix(".pkl").write_bytes(b"fixture")
    with pytest.raises(ValueError, match="Missing or inconsistent snapshot resource"):
        preparation._snapshot_resources([{"world_seed": 100, "scenario_options": {"snapshot_path": str(path)}}])
