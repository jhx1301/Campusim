"""One transactional, public learning library; one writer, frozen readers."""

import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from .memory_store import CaseStoreError, _file_sha, public_case
from .memory_types import canonical_json, public_case_from_dict


SCHEMA = "cemas-learning-memory-v2"


class LearningMemoryStore:
    def __init__(self, path, public_task_sha256=None, *, readonly=False):
        self.path = Path(path).resolve()
        self.readonly = readonly
        self.episode_id = None
        self.episode_group = None
        if readonly:
            manifest = json.loads(self.path.with_suffix(".manifest.json").read_text(encoding="utf-8"))
            if manifest["schema_version"] != SCHEMA:
                raise CaseStoreError("unsupported learning library schema; create a new v2 library")
            if manifest["database_sha256"] != _file_sha(self.path):
                raise CaseStoreError("frozen learning snapshot identity mismatch")
            self.store_sha256 = manifest["database_sha256"]
            self._db = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._db = sqlite3.connect(self.path)
            self.store_sha256 = None
        self._db.execute("PRAGMA foreign_keys=ON")
        exists = self._db.execute("SELECT name FROM sqlite_master WHERE name='metadata'").fetchone()
        if not exists:
            if readonly or not public_task_sha256:
                self._db.close()
                raise CaseStoreError("a new learning library requires public task identity")
            self._db.executescript("""
                CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE episodes(episode_id TEXT PRIMARY KEY, scenario_hash TEXT NOT NULL,
                    opaque_group TEXT NOT NULL, output_dir TEXT, completed INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE case_ids(case_id INTEGER PRIMARY KEY, episode_id TEXT NOT NULL,
                    local_id INTEGER NOT NULL, UNIQUE(episode_id,local_id),
                    FOREIGN KEY(episode_id) REFERENCES episodes(episode_id));
                CREATE TABLE case_revisions(case_id INTEGER NOT NULL, revision INTEGER NOT NULL,
                    payload_json TEXT NOT NULL, PRIMARY KEY(case_id,revision),
                    FOREIGN KEY(case_id) REFERENCES case_ids(case_id));
                CREATE TABLE rule_revisions(rule_id INTEGER NOT NULL, version INTEGER NOT NULL,
                    payload_json TEXT NOT NULL, PRIMARY KEY(rule_id,version));
                CREATE TABLE rule_updates(
                    rule_id INTEGER NOT NULL,
                    rule_version INTEGER NOT NULL,
                    opaque_group TEXT NOT NULL,
                    case_id INTEGER NOT NULL,
                    case_revision INTEGER NOT NULL,
                    window_start INTEGER NOT NULL,
                    window_end INTEGER NOT NULL,
                    judgment TEXT NOT NULL CHECK(judgment IN ('support','contradict','ignore')),
                    PRIMARY KEY(rule_id, rule_version, opaque_group, window_start, window_end),
                    FOREIGN KEY(rule_id,rule_version) REFERENCES rule_revisions(rule_id,version),
                    FOREIGN KEY(case_id,case_revision) REFERENCES case_revisions(case_id,revision)
                );
                CREATE TABLE operations(episode_id TEXT NOT NULL, operation_key TEXT NOT NULL,
                    result_json TEXT NOT NULL, PRIMARY KEY(episode_id,operation_key));
            """)
            self._db.executemany("INSERT INTO metadata VALUES(?,?)",
                (("schema_version", SCHEMA), ("public_task_sha256", public_task_sha256)))
            self._db.commit()
        metadata = dict(self._db.execute("SELECT key,value FROM metadata"))
        if metadata["schema_version"] != SCHEMA:
            self._db.close()
            raise CaseStoreError("unsupported learning library schema; create a new v2 library")
        self.public_task_sha256 = metadata["public_task_sha256"]
        if public_task_sha256 is not None and public_task_sha256 != self.public_task_sha256:
            self._db.close()
            raise CaseStoreError("learning library belongs to a different public task")

    def begin_episode(self, episode_id, scenario_hash):
        if self.readonly or self.episode_id is not None:
            raise CaseStoreError("learning episode requires an idle writable library")
        self._db.execute("BEGIN IMMEDIATE")
        row = self._db.execute("SELECT scenario_hash,completed FROM episodes WHERE episode_id=?", (episode_id,)).fetchone()
        if row:
            self._db.rollback()
            if row[0] != scenario_hash:
                raise CaseStoreError("episode identity refers to a different scenario")
            if row[1]:
                return False
            raise CaseStoreError("incomplete episode was committed")
        self.episode_group = uuid4().hex
        self._db.execute("INSERT INTO episodes(episode_id,scenario_hash,opaque_group) VALUES(?,?,?)",
                         (episode_id, scenario_hash, self.episode_group))
        self.episode_id = episode_id
        return True

    def _writing(self):
        if self.readonly or self.episode_id is None:
            raise CaseStoreError("writes require an active training episode")

    def complete_episode(self, output_dir):
        self._writing()
        self._db.execute("UPDATE episodes SET completed=1,output_dir=? WHERE episode_id=?",
                         (str(output_dir), self.episode_id))
        self._db.commit()
        self.episode_id = None
        self.episode_group = None

    def rollback(self):
        self._db.rollback()
        self.episode_id = None
        self.episode_group = None

    def append_cases(self, revisions):
        self._writing()
        result = []
        for local in revisions:
            row = self._db.execute("SELECT case_id FROM case_ids WHERE episode_id=? AND local_id=?",
                                   (self.episode_id, local.local_id)).fetchone()
            if row is None:
                if local.revision != 1:
                    raise CaseStoreError("case must begin at revision one")
                cursor = self._db.execute("INSERT INTO case_ids(episode_id,local_id) VALUES(?,?)",
                                          (self.episode_id, local.local_id))
                case_id = cursor.lastrowid
            else:
                case_id = row[0]
            case = public_case(local, case_id, self.public_task_sha256)
            payload = canonical_json(case)
            old = self._db.execute("SELECT revision,payload_json FROM case_revisions WHERE case_id=? ORDER BY revision DESC LIMIT 1",
                                   (case_id,)).fetchone()
            if old and old[0] == local.revision and old[1] == payload:
                result.append(case)
                continue
            if local.revision != (old[0] + 1 if old else 1):
                raise CaseStoreError("case revision is conflicting or out of order")
            if old:
                prior = public_case_from_dict(json.loads(old[1]))
                if (prior.pre_observation != case.pre_observation
                        or (prior.executed_week.start_day, prior.executed_week.end_day)
                           != (case.executed_week.start_day, case.executed_week.end_day)):
                    raise CaseStoreError("case revision changed its decision or execution window")
            self._db.execute("INSERT INTO case_revisions VALUES(?,?,?)", (case_id, local.revision, payload))
            result.append(case)
        return tuple(result)

    def cases(self):
        rows = self._db.execute("""SELECT r.payload_json FROM case_revisions r JOIN
            (SELECT case_id,MAX(revision) revision FROM case_revisions GROUP BY case_id) c
            USING(case_id,revision) ORDER BY case_id""")
        return tuple(public_case_from_dict(json.loads(row[0])) for row in rows)

    def case(self, case_id, revision=None):
        query = "SELECT payload_json FROM case_revisions WHERE case_id=?"
        args = (case_id,)
        if revision is not None:
            query += " AND revision=?"
            args += (revision,)
        row = self._db.execute(query + " ORDER BY revision DESC LIMIT 1", args).fetchone()
        if row is None:
            raise KeyError(case_id)
        return public_case_from_dict(json.loads(row[0]))

    def group_for(self, case_id):
        row = self._db.execute("SELECT e.opaque_group FROM case_ids c JOIN episodes e USING(episode_id) WHERE c.case_id=?",
                               (case_id,)).fetchone()
        if row is None:
            raise KeyError(case_id)
        return row[0]

    def current_rules(self):
        return tuple(json.loads(row[0]) for row in self._db.execute("""SELECT r.payload_json FROM rule_revisions r JOIN
            (SELECT rule_id,MAX(version) version FROM rule_revisions GROUP BY rule_id) v
            USING(rule_id,version) ORDER BY rule_id"""))

    def rule_updates(self, rule_id=None, version=None):
        """Return the small judgment index used for rule statistics and retrieval."""
        query = ("SELECT rule_id,rule_version,opaque_group,case_id,case_revision,"
                 "window_start,window_end,judgment FROM rule_updates")
        clauses, args = [], []
        if rule_id is not None:
            clauses.append("rule_id=?")
            args.append(rule_id)
        if version is not None:
            clauses.append("rule_version=?")
            args.append(version)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY rule_id,rule_version,opaque_group,window_start,window_end"
        names = ("rule_id", "rule_version", "opaque_group", "case_id", "case_revision",
                 "window_start", "window_end", "judgment")
        return tuple(dict(zip(names, row)) for row in self._db.execute(query, args))

    def write_rule_changes(self, changes, updates=()):
        """Commit one parsed batch inside the current episode transaction."""
        self._writing()
        rules = tuple(changes)
        updates = tuple(updates)
        current = {rule["id"]: rule for rule in self.current_rules()}
        for rule in rules:
            old = current.get(rule["id"])
            if old is None:
                valid = rule["version"] == 1
            else:
                same_content = (rule["content"], rule["conditions"]) == (old["content"], old["conditions"])
                valid = rule["version"] == old["version"] + int(not same_content)
            if not valid:
                raise CaseStoreError("rule content/version conflicts with the current library")

        self._db.execute("SAVEPOINT rule_batch")
        try:
            self._db.executemany("""INSERT INTO rule_revisions(rule_id,version,payload_json)
                VALUES(?,?,?) ON CONFLICT(rule_id,version) DO UPDATE SET payload_json=excluded.payload_json""",
                ((r["id"], r["version"], canonical_json(r)) for r in rules))
            self._db.executemany("""INSERT INTO rule_updates
                (rule_id,rule_version,opaque_group,case_id,case_revision,window_start,window_end,judgment)
                VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(rule_id,rule_version,opaque_group,window_start,window_end) DO UPDATE SET
                    case_id=excluded.case_id, case_revision=excluded.case_revision, judgment=excluded.judgment""",
                ((u["rule_id"], u["rule_version"], u["opaque_group"], u["case_id"], u["case_revision"],
                  u["window_start"], u["window_end"], u["judgment"]) for u in updates))
            affected = {(r["id"], r["version"]) for r in rules}
            affected.update((u["rule_id"], u["rule_version"]) for u in updates)
            for identity in affected:
                row = self._db.execute("SELECT payload_json FROM rule_revisions WHERE rule_id=? AND version=?",
                                       identity).fetchone()
                rule = json.loads(row[0])
                counts = dict(self._db.execute("""SELECT judgment,COUNT(*) FROM rule_updates
                    WHERE rule_id=? AND rule_version=? GROUP BY judgment""", identity))
                rule["support_count"] = counts.get("support", 0)
                rule["contradiction_count"] = counts.get("contradict", 0)
                rule["confidence"] = ((rule["support_count"] + 1) /
                                      (rule["support_count"] + rule["contradiction_count"] + 2))
                if rule["status"] != "suspended":
                    rule["status"] = "active" if rule["support_count"] >= 2 else "candidate"
                self._db.execute("UPDATE rule_revisions SET payload_json=? WHERE rule_id=? AND version=?",
                                 (canonical_json(rule), *identity))
        except BaseException:
            self._db.execute("ROLLBACK TO rule_batch")
            raise
        finally:
            self._db.execute("RELEASE rule_batch")

    def operation(self, key):
        row = self._db.execute("SELECT result_json FROM operations WHERE episode_id=? AND operation_key=?",
                               (self.episode_id, key)).fetchone()
        return json.loads(row[0]) if row else None

    def record_operation(self, key, result):
        self._writing()
        self._db.execute("INSERT INTO operations VALUES(?,?,?)", (self.episode_id, key, canonical_json(result)))

    def freeze(self, path):
        if self.episode_id is not None:
            raise CaseStoreError("freeze only at a completed episode boundary")
        path = Path(path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb"):
            pass
        with sqlite3.connect(path) as target:
            self._db.backup(target)
        manifest = {"schema_version": SCHEMA, "public_task_sha256": self.public_task_sha256,
                    "database_sha256": _file_sha(path)}
        with path.with_suffix(".manifest.json").open("x", encoding="utf-8") as handle:
            json.dump(manifest, handle, ensure_ascii=False, indent=2)
        return path

    def close(self):
        self.rollback()
        self._db.close()
