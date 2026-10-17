"""Private source construction and separately published read-only public cases."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
import errno
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
from uuid import uuid4

from .memory_types import (CASE_SCHEMA_VERSION, LocalCaseRevision, PublicCase,
    canonical_json, public_case_from_dict, public_hash, public_to_dict)

STORE_SCHEMA_VERSION = "cemas-public-case-store-v1"
DATABASE_FILENAME = "observable_source_memory_v1.sqlite"
SOURCE_POLICIES = ("minimum", "maximum_feasible", "uniform_legal_independent_rng", "tuned_threshold")
_PURPOSES = ("fixture", "development", "evaluation_ready")
_TABLE_COLUMNS = {
    "case_revisions": ("case_id", "revision", "payload_json", "public_content_sha256"),
    "active_revision": ("case_id", "revision"),
    "case_group": ("case_id", "opaque_group"), "metadata": ("key", "value")}


class CaseStoreError(RuntimeError):
    """Fatal source, schema, provenance, or integrity failure."""


class CaseStoreUnavailable(OSError):
    """A classified temporary read error, safe to retry next week."""


def _sha(value, name):
    if type(value) is not str or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise CaseStoreError(f"{name} must be a lowercase SHA-256")
    return value


def _file_sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _temporary_read_error(exc):
    if isinstance(exc, OSError):
        return exc.errno in (errno.EAGAIN, errno.EINTR, errno.EBUSY, errno.ETIMEDOUT, getattr(errno, "ESTALE", -1))
    if isinstance(exc, sqlite3.OperationalError):
        return getattr(exc, "sqlite_errorcode", None) in (
            sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED, getattr(sqlite3, "SQLITE_IOERR_READ", 266))
    return False


def public_content_sha256(case):
    """Semantic identity excludes IDs, grouping, and generated prose."""
    payload = public_to_dict(case)
    for key in ("case_id", "revision", "description", "public_source"):
        payload.pop(key, None)
    return public_hash(payload)


@dataclass(frozen=True, slots=True)
class StoreManifest:
    schema_version: str
    purpose: str
    storage_state: str
    public_task_sha256: str
    database_sha256: str
    case_count: int
    revision_count: int
    active_revisions: tuple[tuple[int, int], ...]
    database_filename: str = DATABASE_FILENAME

    def __post_init__(self):
        if self.schema_version != STORE_SCHEMA_VERSION or self.purpose not in _PURPOSES or self.storage_state != "immutable":
            raise CaseStoreError("unsupported store manifest identity")
        _sha(self.public_task_sha256, "public_task_sha256")
        _sha(self.database_sha256, "database_sha256")
        if (type(self.case_count) is not int or self.case_count < 0 or type(self.revision_count) is not int
                or self.revision_count < self.case_count):
            raise CaseStoreError("invalid manifest counts")
        revisions = tuple(tuple(pair) for pair in self.active_revisions)
        if (any(len(p) != 2 or any(type(v) is not int or v <= 0 for v in p) for p in revisions)
                or tuple(sorted(revisions)) != revisions or len({p[0] for p in revisions}) != len(revisions)
                or len(revisions) != self.case_count):
            raise CaseStoreError("invalid active revision identities")
        if Path(self.database_filename).name != self.database_filename or not self.database_filename:
            raise CaseStoreError("manifest database filename must be a simple name")
        object.__setattr__(self, "active_revisions", revisions)

    def to_dict(self):
        return public_to_dict(asdict(self))


@dataclass(frozen=True, slots=True)
class CollectionReport:
    trajectory_count: int
    completed_trajectory_count: int
    case_count: int
    revision_count: int
    private_manifest_path: str


def load_store_manifest(value):
    if isinstance(value, StoreManifest):
        return value
    if isinstance(value, (str, Path)):
        try:
            value = json.loads(Path(value).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise CaseStoreError("store manifest cannot be read") from exc
    if not isinstance(value, Mapping):
        raise CaseStoreError("verified store manifest is required")
    try:
        return StoreManifest(**dict(value))
    except (TypeError, ValueError) as exc:
        raise CaseStoreError("invalid store manifest fields") from exc


def _world(seed):
    index = seed - 30001
    return {"beta_scale": (.9, 1, 1.12)[index // 9],
            "screening_capacity_ratio": (.02, .05, .1)[(index // 3) % 3], "replicate": index % 3}


def _compatibility(value, required):
    if not isinstance(value, Mapping):
        raise CaseStoreError("source compatibility must be a mapping")
    result = dict(value)
    if required:
        for key in ("source_code_sha256", "calibration_artifact_sha256", "objective_sha256"):
            _sha(result.get(key), key)
        if type(result.get("execution_days")) is not int or result["execution_days"] <= 0:
            raise CaseStoreError("source execution_days must be positive")
    return json.loads(canonical_json(result))


def _registration(value, purpose, compatibility):
    if not isinstance(value, Mapping):
        raise CaseStoreError("private source registration must be a mapping")
    result = json.loads(canonical_json(dict(value)))
    if type(result.get("trajectory_id")) is not str or not result["trajectory_id"].strip():
        raise CaseStoreError("private trajectory_id is required")
    if result.get("purpose", purpose) != purpose:
        raise CaseStoreError("source purpose mismatch")
    result["purpose"] = purpose
    if purpose != "fixture":
        if result.get("source_kind") != "source_simulation" or result.get("split") != "source":
            raise CaseStoreError("only audited source simulations may enter a source store")
        seed = result.get("seed")
        if type(seed) is not int or not 30001 <= seed <= 30027:
            raise CaseStoreError("source seed outside memory collection pool")
        if result.get("policy") not in SOURCE_POLICIES or result.get("world") != _world(seed):
            raise CaseStoreError("unsupported policy or incorrect source world mapping")
        if _compatibility(result.get("compatibility", {}), True) != compatibility:
            raise CaseStoreError("source compatibility mismatch")
    return result

class PublicCaseBuilder:
    """Append-only public revisions with a separate private registration DB."""

    def __init__(self, staging_dir, public_task_sha256, *, purpose="fixture", compatibility=None):
        if purpose not in _PURPOSES:
            raise CaseStoreError("unsupported collection purpose")
        self.staging_dir = Path(staging_dir).resolve()
        self.public_task_sha256 = _sha(public_task_sha256, "public_task_sha256")
        self.purpose = purpose
        self.compatibility = _compatibility(compatibility or {}, purpose != "fixture")
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.staging_dir / DATABASE_FILENAME
        self.private_path = self.staging_dir / "private_sources.sqlite"
        if any(path.exists() for path in (self.path, self.private_path, self.staging_dir / "private_manifest.json")):
            raise CaseStoreError("staging output already exists; use a new directory")
        self._public = sqlite3.connect(self.path)
        self._private = sqlite3.connect(self.private_path)
        self._closed = self._finalized = False
        self._public.executescript("""
            PRAGMA foreign_keys=ON;
            CREATE TABLE case_revisions(case_id INTEGER NOT NULL,revision INTEGER NOT NULL,
                payload_json TEXT NOT NULL,public_content_sha256 TEXT NOT NULL,PRIMARY KEY(case_id,revision));
            CREATE TABLE active_revision(case_id INTEGER PRIMARY KEY,revision INTEGER NOT NULL,
                FOREIGN KEY(case_id,revision) REFERENCES case_revisions(case_id,revision));
            CREATE TABLE case_group(case_id INTEGER PRIMARY KEY,opaque_group TEXT NOT NULL);
            CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        """)
        self._public.executemany("INSERT INTO metadata VALUES(?,?)", (
            ("schema_version", STORE_SCHEMA_VERSION), ("case_schema_version", CASE_SCHEMA_VERSION),
            ("public_task_sha256", self.public_task_sha256)))
        self._public.commit()
        self._private.executescript("""
            CREATE TABLE trajectories(trajectory_id TEXT PRIMARY KEY,registration_json TEXT NOT NULL,
                opaque_group TEXT NOT NULL,status TEXT NOT NULL);
            CREATE TABLE identities(trajectory_id TEXT NOT NULL,local_id INTEGER NOT NULL,
                case_id INTEGER NOT NULL UNIQUE,PRIMARY KEY(trajectory_id,local_id));
        """)
        self._private.commit()

    def append(self, local_revisions, private_source_registration):
        if self._closed or self._finalized:
            raise CaseStoreError("collection is already finalized")
        revisions = tuple(local_revisions)
        if any(type(item) is not LocalCaseRevision for item in revisions):
            raise TypeError("append accepts only LocalCaseRevision values")
        registration = _registration(private_source_registration, self.purpose, self.compatibility)
        trajectory = registration["trajectory_id"]
        encoded, ids = canonical_json(registration), []
        try:
            self._public.execute("BEGIN IMMEDIATE")
            self._private.execute("BEGIN IMMEDIATE")
            existing = self._private.execute("SELECT registration_json,opaque_group,status FROM trajectories WHERE trajectory_id=?", (trajectory,)).fetchone()
            if existing:
                if existing[0] != encoded or existing[2] != "collecting":
                    raise CaseStoreError("trajectory registration changed or was already closed")
                group = existing[1]
            else:
                group = uuid4().hex
                self._private.execute("INSERT INTO trajectories VALUES(?,?,?,?)", (trajectory, encoded, group, "collecting"))
            next_id = self._public.execute("SELECT COALESCE(MAX(case_id),0)+1 FROM case_revisions").fetchone()[0]
            for local in revisions:
                identity = self._private.execute("SELECT case_id FROM identities WHERE trajectory_id=? AND local_id=?", (trajectory, local.local_id)).fetchone()
                if identity:
                    case_id = identity[0]
                else:
                    if local.revision != 1:
                        raise CaseStoreError("new local case must begin at revision one")
                    case_id, next_id = next_id, next_id + 1
                    self._private.execute("INSERT INTO identities VALUES(?,?,?)", (trajectory, local.local_id, case_id))
                case = PublicCase(case_id=case_id,revision=local.revision,schema_version=CASE_SCHEMA_VERSION,
                    public_task_sha256=self.public_task_sha256,pre_observation=local.pre_observation,
                    executed_window=local.executed_window,window_days=local.window_days,
                    followup_window=local.followup_window,status=local.status,
                    available_through_day=local.available_through_day,attribution="descriptive_not_causal",
                    flags=local.flags,description=local.description,public_source={"kind":"source_simulation",
                        "observation_sha256":public_hash(local.pre_observation),
                        "feedback_sha256":public_hash(local.executed_window),
                        "followup_sha256":None if local.followup_window is None else public_hash(local.followup_window)})
                if self.purpose != "fixture" and case.pre_observation.execution_days != self.compatibility["execution_days"]:
                    raise CaseStoreError("case horizon mismatches source compatibility")
                payload = canonical_json(public_to_dict(case))
                old = self._public.execute("SELECT payload_json FROM case_revisions WHERE case_id=? AND revision=?", (case_id, local.revision)).fetchone()
                if old:
                    if old[0] != payload:
                        raise CaseStoreError("same revision has different public content")
                    ids.append(case_id)
                    continue
                active = self._public.execute("SELECT revision FROM active_revision WHERE case_id=?", (case_id,)).fetchone()
                if local.revision != (active[0]+1 if active else 1):
                    raise CaseStoreError("case revisions must be consecutive and append-only")
                if active:
                    prior = public_case_from_dict(json.loads(self._public.execute("SELECT payload_json FROM case_revisions WHERE case_id=? AND revision=?", (case_id,active[0])).fetchone()[0]))
                    if prior.pre_observation != case.pre_observation or prior.executed_window != case.executed_window:
                        raise CaseStoreError("revision cannot change original public transition")
                self._public.execute("INSERT INTO case_revisions VALUES(?,?,?,?)", (case_id,local.revision,payload,public_content_sha256(case)))
                self._public.execute("INSERT OR REPLACE INTO active_revision VALUES(?,?)", (case_id,local.revision))
                self._public.execute("INSERT OR IGNORE INTO case_group VALUES(?,?)", (case_id,group))
                ids.append(case_id)
            self._private.commit()
            self._public.commit()
        except Exception:
            self._private.rollback()
            self._public.rollback()
            raise
        return tuple(ids)

    def finalize(self, source_run_status):
        if self._closed or self._finalized:
            raise CaseStoreError("collection is already finalized")
        trajectories = self._private.execute("SELECT trajectory_id,registration_json,opaque_group FROM trajectories ORDER BY trajectory_id").fetchall()
        statuses = ({row[0]:source_run_status for row in trajectories} if isinstance(source_run_status,str)
                    else dict(source_run_status) if isinstance(source_run_status,Mapping) else {})
        if set(statuses) != {row[0] for row in trajectories} or any(v not in ("completed","failed","cancelled") for v in statuses.values()):
            raise CaseStoreError("statuses must identify every trajectory exactly")
        entries = []
        for trajectory, encoded, group in trajectories:
            self._private.execute("UPDATE trajectories SET status=? WHERE trajectory_id=?", (statuses[trajectory],trajectory))
            entry = json.loads(encoded)
            entry.update(status=statuses[trajectory],opaque_group=group,
                case_ids=[row[0] for row in self._private.execute("SELECT case_id FROM identities WHERE trajectory_id=? ORDER BY case_id",(trajectory,))])
            entries.append(entry)
        self._private.commit()
        cases = self._public.execute("SELECT COUNT(*) FROM active_revision").fetchone()[0]
        revisions = self._public.execute("SELECT COUNT(*) FROM case_revisions").fetchone()[0]
        manifest = {"schema_version":STORE_SCHEMA_VERSION,"purpose":self.purpose,
            "public_task_sha256":self.public_task_sha256,"compatibility":self.compatibility,
            "trajectories":entries,"case_count":cases,"revision_count":revisions}
        path = self.staging_dir / "private_manifest.json"
        with path.open("x",encoding="utf-8",newline="\n") as stream:
            stream.write(canonical_json(manifest)+"\n")
        self._finalized = True
        self.close()
        return CollectionReport(len(entries),sum(e["status"]=="completed" for e in entries),cases,revisions,str(path))

    def close(self):
        if not self._closed:
            self._public.commit()
            self._public.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self._public.close()
            self._private.close()
            self._closed = True

    def __enter__(self):
        return self

    def __exit__(self,*_args):
        self.close()

def _private_manifest(value):
    if isinstance(value,(str,Path)):
        try:
            value = json.loads(Path(value).read_text(encoding="utf-8"))
        except (OSError,ValueError) as exc:
            raise CaseStoreError("private build manifest cannot be read") from exc
    if not isinstance(value,Mapping):
        raise CaseStoreError("private build manifest is required")
    return json.loads(canonical_json(dict(value)))


def verify_source_manifest(value, expected_compatibility=None, *, purpose=None, compatibility=None):
    """Private runner gate, independent of the public runtime reader."""
    manifest = _private_manifest(value)
    if "database_sha256" in manifest:
        expected_database_hash = _sha(manifest["database_sha256"], "database_sha256")
        if isinstance(value, (str, Path)):
            database = Path(value).resolve().parent / DATABASE_FILENAME
            try:
                if _file_sha(database) != expected_database_hash:
                    raise CaseStoreError("private source manifest database hash mismatch")
            except OSError as exc:
                raise CaseStoreError("private source manifest database missing or unreadable") from exc
    actual = manifest.get("purpose")
    if manifest.get("schema_version") != STORE_SCHEMA_VERSION or actual not in _PURPOSES or purpose is not None and actual != purpose:
        raise CaseStoreError("private source purpose/version mismatch")
    _sha(manifest.get("public_task_sha256"),"public_task_sha256")
    compat = _compatibility(manifest.get("compatibility",{}),actual!="fixture")
    expected = expected_compatibility if expected_compatibility is not None else compatibility
    if expected is not None and compat != _compatibility(expected,actual!="fixture"):
        raise CaseStoreError("source compatibility does not match current runner")
    trajectories = manifest.get("trajectories")
    if type(trajectories) is not list or not trajectories:
        raise CaseStoreError("source manifest has no trajectories")
    seen, identities, groups, case_ids = set(),set(),set(),set()
    for entry in trajectories:
        if not isinstance(entry,dict):
            raise CaseStoreError("invalid source trajectory entry")
        registration = _registration({k:v for k,v in entry.items() if k not in ("status","opaque_group","case_ids")},actual,compat)
        identity = registration["trajectory_id"]
        if identity in seen or entry.get("status") != "completed":
            raise CaseStoreError("source trajectories must be unique and completed")
        seen.add(identity)
        group = entry.get("opaque_group")
        if type(group) is not str or len(group)!=32 or any(c not in "0123456789abcdef" for c in group) or group in groups:
            raise CaseStoreError("invalid or duplicated opaque trajectory group")
        groups.add(group)
        ids = entry.get("case_ids")
        if (type(ids) is not list or not ids or any(type(i) is not int or i<=0 or i in case_ids for i in ids)
                or len(set(ids)) != len(ids)):
            raise CaseStoreError("trajectory case identities must be nonempty and unique")
        case_ids.update(ids)
        if actual != "fixture":
            pair = (registration["seed"],registration["policy"])
            if pair in identities:
                raise CaseStoreError("duplicated source world/policy trajectory")
            identities.add(pair)
    if manifest.get("case_count") != len(case_ids):
        raise CaseStoreError("source manifest case coverage mismatch")
    if actual == "evaluation_ready":
        required = {(s,p) for s in range(30001,30028) for p in SOURCE_POLICIES}
        if identities != required or len(trajectories)!=108:
            raise CaseStoreError("evaluation_ready requires exactly all 108 world/policy trajectories")
        # P6 owns the threshold and common H/objective artifact schemas. A caller
        # cannot replace those artifacts with self-declared booleans or hashes.
        raise CaseStoreError("evaluation_ready requires supported Phase 6 threshold/horizon/objective freeze artifacts; Phase 5 cannot publish it")
    return manifest


def coverage_report(staging_or_manifest):
    value = (Path(staging_or_manifest)/"private_manifest.json"
             if isinstance(staging_or_manifest,(str,Path)) and Path(staging_or_manifest).is_dir() else staging_or_manifest)
    manifest = _private_manifest(value)
    entries = manifest.get("trajectories",[])
    observed = {(item.get("seed"),item.get("policy")) for item in entries}
    required = {(s,p) for s in range(30001,30028) for p in SOURCE_POLICIES}
    return {"purpose":manifest.get("purpose"),"trajectory_count":len(entries),
        "completed_trajectory_count":sum(e.get("status")=="completed" for e in entries),
        "case_count":manifest.get("case_count",0),"revision_count":manifest.get("revision_count",0),
        "policies":sorted({e["policy"] for e in entries if "policy" in e}),
        "missing_world_policy_identities":[[s,p] for s,p in sorted(required-observed)],
        "exact_108_identity_coverage":observed==required and len(entries)==108}


def freeze_public_store(staging, private_manifest, output_dir, purpose=None):
    """Copy a closed staging file into a fresh publication directory."""
    staging, output = Path(staging),Path(output_dir).resolve()
    source = (staging/DATABASE_FILENAME if staging.is_dir() else staging).resolve()
    if source.parent==output or source==output or output.exists():
        raise CaseStoreError("freeze output must be a new directory distinct from staging")
    manifest = verify_source_manifest(private_manifest,purpose=purpose)
    if not source.is_file() or any(Path(str(source)+suffix).exists() for suffix in ("-wal","-journal")):
        raise CaseStoreError("staging database must be closed and checkpointed before freeze")
    connection = sqlite3.connect(source,timeout=0)
    try:
        connection.execute("BEGIN EXCLUSIVE")
        if connection.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            raise CaseStoreError("staging database integrity check failed")
        active = tuple(connection.execute("SELECT case_id,revision FROM active_revision ORDER BY case_id"))
        count = connection.execute("SELECT COUNT(*) FROM case_revisions").fetchone()[0]
        metadata = dict(connection.execute("SELECT key,value FROM metadata"))
        if (metadata != {"schema_version":STORE_SCHEMA_VERSION,"case_schema_version":CASE_SCHEMA_VERSION,
                         "public_task_sha256":manifest["public_task_sha256"]}
                or len(active)!=manifest.get("case_count") or count!=manifest.get("revision_count")):
            raise CaseStoreError("staging database mismatches private build manifest")
        expected_groups = {case_id:e["opaque_group"] for e in manifest["trajectories"] for case_id in e["case_ids"]}
        if dict(connection.execute("SELECT case_id,opaque_group FROM case_group")) != expected_groups:
            raise CaseStoreError("public grouping mismatches source registration")
        connection.rollback()
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except sqlite3.DatabaseError as exc:
        raise CaseStoreError("staging database cannot be frozen") from exc
    finally:
        connection.close()
    source_hash = _file_sha(source)
    result = StoreManifest(STORE_SCHEMA_VERSION,manifest["purpose"],"immutable",manifest["public_task_sha256"],source_hash,len(active),count,active)
    with FrozenPublicCaseStore.open(source,result) as reader:
        cases = reader.cases()
        if manifest["purpose"] != "fixture":
            for entry in manifest["trajectories"]:
                windows = sorted((c.executed_window for c in cases if c.case_id in entry["case_ids"]),key=lambda w:w.start_day)
                horizon = manifest["compatibility"]["execution_days"]
                if (not windows or windows[0].start_day!=0 or windows[-1].end_day!=horizon-1
                        or any(a.end_day+1!=b.start_day for a,b in zip(windows,windows[1:]))):
                    raise CaseStoreError("completed source trajectory must cover its entire horizon")
    output.mkdir(parents=True,exist_ok=False)
    destination = output/DATABASE_FILENAME
    with source.open("rb") as incoming,destination.open("xb") as outgoing:
        shutil.copyfileobj(incoming,outgoing)
        outgoing.flush()
        os.fsync(outgoing.fileno())
    if _file_sha(destination)!=source_hash or _file_sha(source)!=source_hash:
        raise CaseStoreError("database changed during publication; output is invalid")
    manifest["database_sha256"] = source_hash
    for name,value in (("store_manifest.json",result.to_dict()),("build_manifest.json",manifest)):
        with (output/name).open("x",encoding="utf-8",newline="\n") as stream:
            stream.write(canonical_json(value)+"\n")
    return result

class FrozenPublicCaseStore:
    """Immutable public rows and internal, meaningless trajectory groups."""

    def __init__(self):
        raise TypeError("use FrozenPublicCaseStore.open")

    @classmethod
    def open(cls,path,verified_manifest):
        manifest = load_store_manifest(verified_manifest)
        source = Path(path).resolve()
        if source.is_dir():
            source = source/manifest.database_filename
        instance = object.__new__(cls)
        instance.path,instance.manifest = source,manifest
        instance.purpose,instance.public_task_sha256 = manifest.purpose,manifest.public_task_sha256
        instance.store_sha256,instance._closed,instance._groups = manifest.database_sha256,False,{}
        instance.verify_integrity()
        try:
            instance._connection = sqlite3.connect(source.as_uri()+"?mode=ro",uri=True,timeout=0)
            instance._connection.execute("PRAGMA query_only=ON")
            instance._connection.execute("PRAGMA trusted_schema=OFF")
            tables = {r[0] for r in instance._connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if tables != set(_TABLE_COLUMNS):
                raise CaseStoreError("unexpected public database schema")
            for name,columns in _TABLE_COLUMNS.items():
                actual = tuple(r[1] for r in instance._connection.execute(f"PRAGMA table_info({name})"))
                if actual!=columns:
                    raise CaseStoreError("unexpected public database columns")
            if dict(instance._connection.execute("SELECT key,value FROM metadata")) != {
                    "schema_version":STORE_SCHEMA_VERSION,"case_schema_version":CASE_SCHEMA_VERSION,
                    "public_task_sha256":manifest.public_task_sha256}:
                raise CaseStoreError("public database metadata mismatch")
            if instance._connection.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                raise CaseStoreError("public database integrity check failed")
            instance._groups = dict(instance._connection.execute("SELECT case_id,opaque_group FROM case_group"))
            if any(type(g) is not str or len(g)!=32 or any(c not in "0123456789abcdef" for c in g) for g in instance._groups.values()):
                raise CaseStoreError("malformed opaque trajectory grouping")
            instance.cases()
            denied = {sqlite3.SQLITE_ATTACH,sqlite3.SQLITE_DETACH,sqlite3.SQLITE_INSERT,
                sqlite3.SQLITE_UPDATE,sqlite3.SQLITE_DELETE,sqlite3.SQLITE_CREATE_TABLE,
                sqlite3.SQLITE_DROP_TABLE,sqlite3.SQLITE_ALTER_TABLE}
            instance._connection.set_authorizer(lambda action,_a,_b,_db,_trigger:
                sqlite3.SQLITE_DENY if action in denied else sqlite3.SQLITE_OK)
            return instance
        except Exception as exc:
            if hasattr(instance,"_connection"):
                instance._connection.close()
            if isinstance(exc,(CaseStoreError,CaseStoreUnavailable)):
                raise
            raise CaseStoreError("public database cannot be opened") from exc

    def verify_integrity(self):
        if self._closed:
            raise CaseStoreError("public store is closed")
        try:
            if _file_sha(self.path)!=self.manifest.database_sha256:
                raise CaseStoreError("immutable public database hash changed")
        except OSError as exc:
            if _temporary_read_error(exc):
                raise CaseStoreUnavailable("temporary public database read error") from exc
            raise CaseStoreError("immutable public database missing or unreadable") from exc

    def cases(self):
        self.verify_integrity()
        try:
            active = tuple(self._connection.execute("SELECT case_id,revision FROM active_revision ORDER BY case_id"))
            if active!=self.manifest.active_revisions or set(self._groups)!={r[0] for r in active}:
                raise CaseStoreError("active revision/group identities changed")
            rows = self._connection.execute("SELECT case_id,revision,payload_json,public_content_sha256 FROM case_revisions ORDER BY case_id,revision").fetchall()
            if len(rows)!=self.manifest.revision_count:
                raise CaseStoreError("revision count mismatch")
            latest,counts,result = {},{},{}
            for case_id,revision,payload,content_hash in rows:
                case = public_case_from_dict(json.loads(payload))
                if (case.case_id!=case_id or case.revision!=revision or case.public_task_sha256!=self.public_task_sha256
                        or case.schema_version!=CASE_SCHEMA_VERSION or public_content_sha256(case)!=content_hash):
                    raise CaseStoreError("public case identity/content mismatch")
                counts[case_id] = counts.get(case_id,0)+1
                if revision!=counts[case_id]:
                    raise CaseStoreError("public revisions must be consecutive")
                if case_id in result:
                    previous = result[case_id]
                    if case.pre_observation!=previous.pre_observation or case.executed_window!=previous.executed_window:
                        raise CaseStoreError("public revision changed original transition")
                latest[case_id],result[case_id] = revision,case
            if tuple(sorted(latest.items()))!=active:
                raise CaseStoreError("active revision must be the latest revision")
            return tuple(result[case_id] for case_id,_ in active)
        except (CaseStoreError,CaseStoreUnavailable):
            raise
        except Exception as exc:
            if _temporary_read_error(exc):
                raise CaseStoreUnavailable("temporary public database query error") from exc
            raise CaseStoreError("public database query/schema/content failure") from exc

    def group_for(self,case_id):
        try:
            return self._groups[case_id]
        except KeyError as exc:
            raise CaseStoreError("public case has no opaque grouping") from exc

    def close(self):
        if not self._closed:
            self._connection.close()
            self._closed = True

    def __enter__(self):
        return self

    def __exit__(self,*_args):
        self.close()
