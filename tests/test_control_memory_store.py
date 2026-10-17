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
    public_content_sha256, verify_source_manifest)
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
    week = PublicWeeklyRecord(day,min(day+6,horizon-1),10,resources=pre.resources)
    followup = PublicWeeklyRecord(day+7,min(day+13,horizon-1),12,resources=pre.resources) if revision==2 else None
    return LocalCaseRevision(local_id,revision,pre,week,followup,
        "closed_two" if revision==2 else "terminal_censored" if week.end_day==horizon-1 else "closed_one",
        ("missing_baseline","truncated_followup") if revision==1 else ("missing_baseline",),"Deterministic public record.")


def registration(seed=30001,policy="minimum"):
    i = seed-30001
    return {"trajectory_id":f"private-{seed}-{policy}","purpose":"development","source_kind":"source_simulation",
        "split":"source","seed":seed,"policy":policy,"world":{"beta_scale":(.9,1,1.12)[i//9],
            "screening_capacity_ratio":(.02,.05,.1)[(i//3)%3],"replicate":i%3},"compatibility":COMPATIBILITY}


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
            connection.execute("ATTACH DATABASE ? AS secret",(str(builder.private_path),))
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
