"""Storage safety, revision identity, and source publication boundaries."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3

import pytest

from cemas.control.memory_store import (DATABASE_FILENAME, SOURCE_POLICIES, CaseStoreError,
    FrozenPublicCaseStore, PublicCaseBuilder, coverage_report, freeze_public_store,
    promote_public_store, public_content_sha256, verify_source_manifest)
from cemas.control.memory_types import LocalCaseRevision, public_to_dict
from cemas.control.types import (ActionVector, PublicObservation, PublicPopulation,
    PublicResources, PublicWeeklyRecord)

TASK = "a"*64
COMPATIBILITY = {"source_code_sha256":"b"*64,"calibration_artifact_sha256":"c"*64,
                 "objective_sha256":"d"*64,"execution_days":14}


def observation(day=0,horizon=14):
    return PublicObservation(day,horizon,1,PublicPopulation(100,(10,20,20,40,10),30,40,5),
        PublicResources(2,5,1),ActionVector((0,0,0,0,0)),(0,)*5,(True,)*324)


def local(local_id=1,revision=1,day=0,horizon=14):
    pre = observation(day,horizon)
    if day == 7:
        pre = replace(pre,history=(PublicWeeklyRecord(),)*3+(PublicWeeklyRecord(0,6,10,resources=pre.resources),),
                      week_valid=(False,False,False,True))
    week = PublicWeeklyRecord(day,min(day+6,horizon-1),10 if day==0 else 12,resources=pre.resources)
    followup = PublicWeeklyRecord(day+7,min(day+13,horizon-1),12,resources=pre.resources) if revision==2 else None
    return LocalCaseRevision(local_id,revision,pre,week,followup,
        "closed_two" if revision==2 else "terminal_censored" if week.end_day==horizon-1 else "closed_one",
        ("missing_baseline","truncated_followup") if revision==1 else ("missing_baseline",),"Deterministic public record.")


def registration(seed=30001,policy="minimum"):
    i = seed-30001
    result = {"trajectory_id":f"private-{seed}-{policy}","purpose":"development","source_kind":"source_simulation",
        "split":"source","seed":seed,"policy":policy,"world":{"beta_scale":(.9,1,1.12)[i//9],
            "screening_capacity_ratio":(.02,.05,.1)[(i//3)%3],"replicate":i%3},"compatibility":COMPATIBILITY}
    if policy == "tuned_threshold":
        result["baseline_artifact_sha256"] = "e" * 64
    return result


def published(tmp_path,revision=True):
    builder = PublicCaseBuilder(tmp_path/"staging",TASK)
    record = local()
    assert builder.append((record,),{"trajectory_id":"secret-world-policy"})==(1,)
    assert builder.append((record,),{"trajectory_id":"secret-world-policy"})==(1,)
    if revision:
        assert builder.append((local(revision=2),),{"trajectory_id":"secret-world-policy"})==(1,)
    report = builder.finalize("completed")
    manifest = freeze_public_store(tmp_path/"staging",report.private_manifest_path,tmp_path/"published")
    return builder,manifest


def test_revisions_monotonic_latest_readonly_and_private_separation(tmp_path):
    builder,manifest = published(tmp_path)
    assert (manifest.case_count,manifest.revision_count,manifest.active_revisions)==(1,2,((1,2),))
    with FrozenPublicCaseStore.open(tmp_path/"published",manifest) as store:
        assert store.cases()[0].revision==2
        connection = store._connection
        assert {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}=={
            "case_revisions","active_revision","case_group","metadata"}
        public_text = json.dumps(public_to_dict(store.cases()))
        assert "secret-world-policy" not in public_text
        assert "opaque_group" not in public_text
        assert len(store.group_for(1))==32
        with pytest.raises(sqlite3.DatabaseError):
            connection.execute("DELETE FROM case_revisions")
        with pytest.raises(sqlite3.DatabaseError):
            connection.execute("ATTACH DATABASE ':memory:' AS extra")
    assert builder.private_path.name=="private_manifest.json"
    assert "secret-world-policy" in builder.private_path.read_text(encoding="utf-8")
    assert not (builder.staging_dir/"private_sources.sqlite").exists()
    with sqlite3.connect(builder.path) as db:
        assert db.execute("SELECT COUNT(*) FROM case_revisions").fetchone()==(2,)


def test_changed_or_skipped_revision_rolls_back(tmp_path):
    with PublicCaseBuilder(tmp_path/"staging",TASK) as builder:
        builder.append((local(),),{"trajectory_id":"one"})
        with pytest.raises(CaseStoreError,match="different public content"):
            builder.append((replace(local(),description="Changed."),),{"trajectory_id":"one"})
        with pytest.raises(CaseStoreError,match="revision one"):
            builder.append((local(local_id=2,revision=2),),{"trajectory_id":"one"})
        report = builder.finalize("completed")
        assert report.case_count==report.revision_count==1


def test_single_database_commit_failure_rolls_back_source_mapping(tmp_path,monkeypatch):
    connect = sqlite3.connect

    class FailedPublicCommit(sqlite3.Connection):
        fail_commit = False

        def commit(self):
            if self.fail_commit:
                raise sqlite3.OperationalError("public commit fixture")
            return super().commit()

    def connection(path,*args,**kwargs):
        if Path(path).name == DATABASE_FILENAME:
            kwargs["factory"] = FailedPublicCommit
        return connect(path,*args,**kwargs)

    monkeypatch.setattr(sqlite3,"connect",connection)
    with PublicCaseBuilder(tmp_path/"staging",TASK) as builder:
        builder._public.fail_commit = True
        with pytest.raises(sqlite3.OperationalError,match="public commit fixture"):
            builder.append((local(),),{"trajectory_id":"one"})
        builder._public.fail_commit = False
        assert builder.append((local(),),{"trajectory_id":"two"})==(1,)
        report = builder.finalize("completed")
    manifest = verify_source_manifest(report.private_manifest_path)
    assert [entry["trajectory_id"] for entry in manifest["trajectories"]]==["two"]
    assert manifest["case_count"]==manifest["revision_count"]==1


def test_source_provenance_uses_json_and_only_one_database(tmp_path,monkeypatch):
    connect,connections = sqlite3.connect,[]

    def connection(path,*args,**kwargs):
        connections.append(Path(path).name)
        return connect(path,*args,**kwargs)

    monkeypatch.setattr(sqlite3,"connect",connection)
    with PublicCaseBuilder(tmp_path/"staging",TASK) as builder:
        assert builder.append((local(),),{"trajectory_id":"z","seed":90001})==(1,)
        assert builder.append((local(),),{"trajectory_id":"a","seed":90002})==(2,)
        assert builder.append((local(revision=2),),{"trajectory_id":"z","seed":90001})==(1,)
        report = builder.finalize({"z":"completed","a":"completed"})
    assert connections==[DATABASE_FILENAME]
    assert {path.name for path in builder.staging_dir.iterdir()}=={DATABASE_FILENAME,"private_manifest.json"}
    manifest = verify_source_manifest(report.private_manifest_path)
    assert [(entry["trajectory_id"],entry["seed"],entry["case_ids"]) for entry in manifest["trajectories"]]==[
        ("a",90002,[2]),("z",90001,[1])]
    assert manifest["case_count"]==2 and manifest["revision_count"]==3


def test_failed_append_discards_new_private_registration(tmp_path):
    with PublicCaseBuilder(tmp_path/"staging",TASK) as builder:
        with pytest.raises(CaseStoreError,match="revision one"):
            builder.append((local(),local(local_id=2,revision=2)),{"trajectory_id":"discarded"})
        assert builder.append((local(),),{"trajectory_id":"kept"})==(1,)
        report = builder.finalize("completed")
    manifest = verify_source_manifest(report.private_manifest_path)
    assert [entry["trajectory_id"] for entry in manifest["trajectories"]]==["kept"]


def test_failed_append_preserves_existing_private_identity_map(tmp_path):
    with PublicCaseBuilder(tmp_path/"staging",TASK) as builder:
        builder.append((local(),),{"trajectory_id":"one"})
        with pytest.raises(CaseStoreError,match="revision one"):
            builder.append((local(local_id=2),local(local_id=3,revision=2)),{"trajectory_id":"one"})
        assert builder.append((local(),),{"trajectory_id":"two"})==(2,)
        assert builder.append((local(local_id=2),),{"trajectory_id":"one"})==(3,)
        report = builder.finalize("completed")
    manifest = verify_source_manifest(report.private_manifest_path)
    assert [entry["case_ids"] for entry in manifest["trajectories"]]==[[1,3],[2]]


def test_semantic_hash_excludes_identity_group_and_prose(tmp_path):
    _,manifest = published(tmp_path,False)
    with FrozenPublicCaseStore.open(tmp_path/"published",manifest) as store:
        case = store.cases()[0]
        assert public_content_sha256(case)==public_content_sha256(replace(case,case_id=999,description="Different phrasing."))
        changed_week = replace(case.executed_window,delivered_diagnoses=11)
        # Reuse builder path to form a fully hash-validated changed PublicCase.
        changed = dict(public_to_dict(case))
        changed["executed_window"] = public_to_dict(changed_week)
        from cemas.control.memory_types import public_case_from_dict, public_hash
        changed["public_source"]["feedback_sha256"] = public_hash(changed_week)
        assert public_content_sha256(case)!=public_content_sha256(public_case_from_dict(changed))


def test_freeze_preserves_inputs_and_never_overwrites(tmp_path):
    builder,manifest = published(tmp_path)
    original = builder.path.read_bytes()
    assert original==(tmp_path/"published"/DATABASE_FILENAME).read_bytes()
    assert hashlib.sha256(original).hexdigest()==manifest.database_sha256
    with pytest.raises(CaseStoreError,match="new directory"):
        freeze_public_store(builder.path,builder.staging_dir/"private_manifest.json",tmp_path/"published")
    assert original==builder.path.read_bytes()
    relocated = tmp_path/"relocated"
    shutil.copytree(tmp_path/"published",relocated)
    with FrozenPublicCaseStore.open(relocated,relocated/"store_manifest.json") as store:
        assert store.store_sha256==manifest.database_sha256


def test_changed_or_missing_store_is_fatal(tmp_path):
    _,manifest = published(tmp_path)
    path = tmp_path/"published"/DATABASE_FILENAME
    store = FrozenPublicCaseStore.open(path,manifest)
    with path.open("ab") as stream:
        stream.write(b"unexpected change")
    with pytest.raises(CaseStoreError,match="hash changed"):
        store.cases()
    store.close()
    with pytest.raises(CaseStoreError):
        FrozenPublicCaseStore.open(tmp_path/"does-not-exist.sqlite",manifest)


@pytest.mark.parametrize("change",[{"seed":40001},{"split":"final_test"},{"world":{}},{"policy":"llm"},
    {"compatibility":{**COMPATIBILITY,"objective_sha256":"f"*64}},{"purpose":"fixture"}])
def test_development_rejects_source_identity_and_compatibility_changes(tmp_path,change):
    with PublicCaseBuilder(tmp_path/"staging",TASK,purpose="development",compatibility=COMPATIBILITY) as builder:
        with pytest.raises(CaseStoreError):
            builder.append((local(),),{**registration(),**change})


def test_development_requires_full_completed_source_horizon(tmp_path):
    with PublicCaseBuilder(tmp_path/"staging",TASK,purpose="development",compatibility=COMPATIBILITY) as builder:
        builder.append((local(),),registration())
        report = builder.finalize("completed")
    with pytest.raises(CaseStoreError,match="entire horizon"):
        freeze_public_store(tmp_path/"staging",report.private_manifest_path,tmp_path/"published")
    assert not (tmp_path/"published").exists()


def test_failed_trajectory_remains_diagnostic_but_cannot_publish(tmp_path):
    with PublicCaseBuilder(tmp_path/"staging",TASK) as builder:
        builder.append((local(),),{"trajectory_id":"one"})
        report = builder.finalize("failed")
    assert Path(report.private_manifest_path).exists()
    with pytest.raises(CaseStoreError,match="completed"):
        freeze_public_store(tmp_path/"staging",report.private_manifest_path,tmp_path/"published")


def test_development_publish_and_private_manifest_hash_binding(tmp_path):
    with PublicCaseBuilder(tmp_path/"staging",TASK,purpose="development",compatibility=COMPATIBILITY) as builder:
        builder.append((local(),local(revision=2),local(local_id=2,day=7)),registration())
        report = builder.finalize("completed")
    manifest = freeze_public_store(tmp_path/"staging",report.private_manifest_path,tmp_path/"published")
    audited = verify_source_manifest(tmp_path/"published"/"build_manifest.json",COMPATIBILITY)
    assert audited["database_sha256"]==manifest.database_sha256
    assert coverage_report(tmp_path/"staging")["exact_108_identity_coverage"] is False


@pytest.mark.parametrize("change",["missing_revision","wrong_followup","conflicting_history","population_changed"])
def test_development_rejects_inconsistent_completed_public_trajectory(tmp_path,change):
    first,updated,last = local(),local(revision=2),local(local_id=2,day=7)
    if change == "wrong_followup":
        updated = replace(updated,followup_window=replace(updated.followup_window,delivered_diagnoses=99))
    elif change == "conflicting_history":
        pre = last.pre_observation
        last = replace(last,pre_observation=replace(pre,history=pre.history[:-1]+(
            replace(pre.history[-1],delivered_diagnoses=99),)))
    elif change == "population_changed":
        last = replace(last,pre_observation=replace(last.pre_observation,
            population=PublicPopulation(200,(20,40,40,80,20),60,80,10)))
    revisions = (first,last) if change == "missing_revision" else (first,updated,last)
    with PublicCaseBuilder(tmp_path/"staging",TASK,purpose="development",compatibility=COMPATIBILITY) as builder:
        builder.append(revisions,registration())
        report = builder.finalize("completed")
    with pytest.raises(CaseStoreError,match="inconsistent public transitions"):
        freeze_public_store(tmp_path/"staging",report.private_manifest_path,tmp_path/"published")
    assert not (tmp_path/"published").exists()


def test_evaluation_ready_exact_cartesian_identity_and_p6_artifact_gate(tmp_path):
    with PublicCaseBuilder(tmp_path/"staging",TASK,purpose="development",compatibility=COMPATIBILITY) as builder:
        builder.append((local(),),registration())
        report = builder.finalize("completed")
    manifest = json.loads(Path(report.private_manifest_path).read_text(encoding="utf-8"))
    manifest["purpose"]="evaluation_ready"
    entries = []
    for index,(seed,policy) in enumerate((s,p) for s in range(30001,30028) for p in SOURCE_POLICIES):
        entry = {**registration(seed,policy),"purpose":"evaluation_ready","status":"completed",
                 "opaque_group":f"{index+1:032x}","case_ids":[index+1]}
        entries.append(entry)
    manifest.update(trajectories=entries,case_count=108,revision_count=108)
    with pytest.raises(CaseStoreError,match="Phase 6"):
        verify_source_manifest(manifest)
    manifest["trajectories"][-1] = {**entries[-2],"trajectory_id":"different-id","opaque_group":"f"*32,"case_ids":[108]}
    with pytest.raises(CaseStoreError,match="duplicated source world/policy"):
        verify_source_manifest(manifest)
    manifest["trajectories"] = entries[:-1]
    manifest["case_count"] = 107
    with pytest.raises(CaseStoreError,match="108"):
        verify_source_manifest(manifest)


def test_threshold_source_requires_actual_artifact_identity(tmp_path):
    source = registration(policy="tuned_threshold")
    del source["baseline_artifact_sha256"]
    with PublicCaseBuilder(tmp_path / "staging", TASK, purpose="development", compatibility=COMPATIBILITY) as builder:
        with pytest.raises(CaseStoreError, match="baseline_artifact_sha256"):
            builder.append((local(),), source)


def test_coverage_lists_public_gaps_without_treating_weeks_as_worlds(tmp_path):
    builder, _manifest = published(tmp_path)
    report = coverage_report(builder.private_path)
    detail = report["public_case_coverage"]
    assert detail["status"] == "available"
    assert detail["case_count"] == 1
    assert detail["missing_dimension_levels"]["S"] == [1, 2, 3]
    assert detail["screening_by_capacity"][0]["missing_levels"] == [1, 2, 3]
    assert detail["history_length_counts"] == {0: 1}
    assert detail["joint_action_counts"] == {"0,0,0,0,0": 1}
    assert detail["independent_worlds"] is False
    assert detail["action_coverage_complete"] is False
    assert report["missing_world_cells"]
    assert coverage_report(json.loads(builder.private_path.read_text(encoding="utf-8")))["public_case_coverage"] == {
        "status": "unavailable", "reason": "database_path_required"}


def _complete_development(tmp_path):
    """Synthetic unit-test trajectories; no source experiment is executed."""
    with PublicCaseBuilder(tmp_path / "staging", TASK, purpose="development", compatibility=COMPATIBILITY) as builder:
        for seed in range(30001, 30028):
            for policy in SOURCE_POLICIES:
                source = {**registration(seed, policy), "run_purpose": "memory_collection"}
                builder.append((local(), local(revision=2), local(local_id=2, day=7)), source)
        report = builder.finalize("completed")
    return freeze_public_store(tmp_path / "staging", report.private_manifest_path, tmp_path / "development")


def test_promotion_preserves_public_bytes_and_actual_source_purposes(tmp_path, monkeypatch):
    import cemas.control.artifacts as artifacts
    original = _complete_development(tmp_path)
    release = tmp_path / "release.json"
    release.write_text('{"synthetic_unit_test":true}', encoding="utf-8")
    calls = []
    # Isolate the publication mechanics; full release validation has separate tests.
    monkeypatch.setattr(artifacts, "validate_phase6_release",
                        lambda path, *, development_dir: calls.append((Path(path), Path(development_dir))))
    source = tmp_path / "development"
    before = (source / "build_manifest.json").read_bytes()
    result = promote_public_store(source, release, tmp_path / "evaluation")
    assert result.purpose == "evaluation_ready"
    assert result.database_sha256 == original.database_sha256
    assert (source / "build_manifest.json").read_bytes() == before
    assert (source / DATABASE_FILENAME).read_bytes() == (tmp_path / "evaluation" / DATABASE_FILENAME).read_bytes()
    manifest = verify_source_manifest(tmp_path / "evaluation" / "build_manifest.json", purpose="evaluation_ready")
    assert len(calls) >= 2
    assert {e["purpose"] for e in manifest["trajectories"]} == {"development"}
    assert {e["run_purpose"] for e in manifest["trajectories"]} == {"memory_collection"}
    with FrozenPublicCaseStore.open(tmp_path / "evaluation", result) as store:
        assert len(store.cases()) == 216
    manifest["trajectories"][0]["run_purpose"] = "evaluation"
    path = tmp_path / "evaluation" / "build_manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(CaseStoreError, match="changed original source provenance"):
        verify_source_manifest(path)


def test_promotion_rejects_fixture_and_incomplete_development(tmp_path):
    published(tmp_path / "fixture")
    with pytest.raises(CaseStoreError, match="purpose/version"):
        promote_public_store(tmp_path / "fixture" / "published", tmp_path / "missing-release.json", tmp_path / "output")
    with PublicCaseBuilder(tmp_path / "staging", TASK, purpose="development", compatibility=COMPATIBILITY) as builder:
        builder.append((local(), local(revision=2), local(local_id=2, day=7)), registration())
        report = builder.finalize("completed")
    freeze_public_store(tmp_path / "staging", report.private_manifest_path, tmp_path / "development")
    with pytest.raises(CaseStoreError, match="108"):
        promote_public_store(tmp_path / "development", tmp_path / "missing-release.json", tmp_path / "output")
    assert not (tmp_path / "output").exists()


def test_collection_loads_threshold_artifact_and_requires_it_before_output(tmp_path):
    from argparse import Namespace
    from cemas.control.artifacts import save_baseline_artifact
    from cemas.control.protocol import load_protocol
    from tools.collect_observable_memory import _controller, collect

    protocol_path = Path(__file__).resolve().parents[1] / "docs/control_protocol_v1.json"
    protocol = load_protocol(protocol_path)
    parameters = {"thresholds": protocol.definition["controllers"]["threshold"]["base_thresholds_per_1000_per_week"],
                  "hysteresis": .75}
    artifact = save_baseline_artifact(tmp_path / "threshold", protocol, "threshold", parameters=parameters)
    controller = _controller("tuned_threshold", 0, protocol, artifact)
    assert controller.controller_type == "threshold"
    assert controller.hysteresis == .75
    assert controller.thresholds["T"] == (1, 5)
    args = Namespace(protocol=protocol_path, seed=None, smoke=False, artifact=tmp_path / "e0.json",
                     population=None, days=None, initial_infections=None, policy=None,
                     threshold_artifact=None, output=tmp_path / "collection")
    with pytest.raises(ValueError, match="--threshold-artifact"):
        collect(args)
    assert not args.output.exists()
