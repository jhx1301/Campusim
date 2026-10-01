"""
Dual-branch memory retrieval and compression for LLM-driven campus policy selection.

Provides:
- EmbeddingProvider: lazy-loaded sentence-transformers wrapper (shared across stores)
- MemoryStore: SQLite-backed two-phase memory persistence
- Vector builders: state_distance_similarity, build_state_vector, build_layer_vector,
  build_trend_context
- Short-term trajectory compression: compress_short_term_trajectory
- Similar scenario retrieval: retrieve_similar_scenarios
- Pending entry builder: build_pending_memory_entry
"""

from __future__ import annotations

import json
import math
import sqlite3
from pathlib import Path
from typing import Optional

import numpy as np


# ---------------------------------------------------------------------------
# EmbeddingProvider
# ---------------------------------------------------------------------------

class EmbeddingProvider:
    """Lazy-loaded sentence-transformers wrapper, shareable across stores."""

    def __init__(self, model_name: str = "paraphrase-multilingual-MiniLM-L12-v2"):
        self.model_name = model_name
        self._model = None

    def encode(self, text: str) -> np.ndarray:
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self.model_name)
        return self._model.encode([text])[0]


# ---------------------------------------------------------------------------
# ReadOnlyError
# ---------------------------------------------------------------------------

class ReadOnlyError(Exception):
    """Raised when a write operation is attempted on a read-only MemoryStore."""


# ---------------------------------------------------------------------------
# MemoryStore — SQLite-backed two-phase memory persistence
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS simulations (
    simulation_id   TEXT PRIMARY KEY,
    rand_seed       INTEGER,
    scenario        TEXT,
    strategy        TEXT,
    pop_size        INTEGER,
    n_days          INTEGER,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS memory_entries (
    entry_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    simulation_id   TEXT NOT NULL,
    decision_day    INTEGER NOT NULL,
    decision_date   TEXT,
    pop_size        INTEGER NOT NULL,

    feedback_status  TEXT DEFAULT 'pending',
    feedback_start_day INTEGER,
    feedback_end_day   INTEGER,
    finalized_at       TEXT,

    new_infections_per_1000  REAL,
    new_diagnoses_per_1000   REAL,
    r_eff_value              REAL,
    r_eff_trend              TEXT,
    r_eff_source             TEXT,
    growth_ratio             REAL,
    tests_per_1000           REAL,
    quarantined_per_1000     REAL,
    teaching_restriction     INTEGER,
    online_teaching          INTEGER,

    infection_trend  TEXT,
    diagnosis_trend  TEXT,
    risk_trend       TEXT,

    layer_contributions       TEXT,
    layer_transmission_trends TEXT,

    policy_requested TEXT,
    policy_executed  TEXT,
    policy_rank      INTEGER,
    risk_level       TEXT,

    execution_feedback TEXT,

    state_summary_text TEXT,

    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (simulation_id) REFERENCES simulations(simulation_id)
);

CREATE TABLE IF NOT EXISTS memory_vectors (
    entry_id      INTEGER PRIMARY KEY,
    state_vector  TEXT,
    layer_vector  TEXT,
    trend_context TEXT,
    text_embedding TEXT,
    FOREIGN KEY (entry_id) REFERENCES memory_entries(entry_id)
);

CREATE INDEX IF NOT EXISTS idx_entries_sim
    ON memory_entries(simulation_id);
CREATE INDEX IF NOT EXISTS idx_entries_day
    ON memory_entries(simulation_id, decision_day);
CREATE INDEX IF NOT EXISTS idx_entries_status
    ON memory_entries(feedback_status);
CREATE INDEX IF NOT EXISTS idx_entries_sim_status
    ON memory_entries(simulation_id, feedback_status);
"""


class MemoryStore:
    """SQLite-backed memory store with two-phase write and optional read-only mode."""

    def __init__(self, db_path: str, read_only: bool = False,
                 embedding_provider: Optional[EmbeddingProvider] = None):
        self.db_path = db_path
        self.read_only = read_only
        self._embedding_provider = embedding_provider or EmbeddingProvider()
        self._connect()

    def _connect(self) -> None:
        """Open the SQLite connection, honoring true filesystem read-only mode."""
        if self.db_path == ":memory:":
            if self.read_only:
                raise ValueError('read_only=True is not supported with db_path=":memory:"')
            self._conn = sqlite3.connect(":memory:")
        elif self.read_only:
            path = Path(self.db_path).expanduser().resolve()
            if not path.is_file():
                raise FileNotFoundError(f"Read-only memory database not found: {path}")
            self._conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
        else:
            path = Path(self.db_path).expanduser()
            path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(path))

        self._conn.row_factory = sqlite3.Row
        if not self.read_only:
            self._conn.executescript(_SCHEMA)

    def __getstate__(self) -> dict:
        state = self.__dict__.copy()
        state["_conn"] = None
        return state

    def __setstate__(self, state: dict) -> None:
        self.__dict__.update(state)
        self._connect()

    # -- simulation management --

    def register_simulation(self, simulation_id: str, rand_seed: int,
                            scenario: str, strategy: str,
                            pop_size: int, n_days: int) -> None:
        if self.read_only:
            raise ReadOnlyError("Cannot register simulation in read-only store")
        self._conn.execute(
            "INSERT OR IGNORE INTO simulations "
            "(simulation_id, rand_seed, scenario, strategy, pop_size, n_days) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (simulation_id, rand_seed, scenario, strategy, pop_size, n_days),
        )
        self._conn.commit()

    def get_all_simulation_ids(self) -> list[str]:
        rows = self._conn.execute(
            "SELECT simulation_id FROM simulations"
        ).fetchall()
        return [r[0] for r in rows]

    # -- two-phase write --

    def create_pending_entry(self, simulation_id: str, decision_day: int,
                             entry_data: dict,
                             state_vector, layer_vector,
                             trend_context, text_embedding) -> int:
        if self.read_only:
            raise ReadOnlyError("Cannot create entry in read-only store")

        cur = self._conn.execute(
            "INSERT INTO memory_entries ("
            "  simulation_id, decision_day, decision_date, pop_size,"
            "  feedback_status,"
            "  new_infections_per_1000, new_diagnoses_per_1000,"
            "  r_eff_value, r_eff_trend, r_eff_source,"
            "  growth_ratio, tests_per_1000, quarantined_per_1000,"
            "  teaching_restriction, online_teaching,"
            "  infection_trend, diagnosis_trend, risk_trend,"
            "  layer_contributions, layer_transmission_trends,"
            "  policy_requested, policy_executed, policy_rank, risk_level,"
            "  execution_feedback, state_summary_text"
            ") VALUES ("
            "  ?, ?, ?, ?, 'pending',"
            "  ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,"
            "  ?, ?, ?, ?, ?, ?, ?, ?"
            ")",
            (
                simulation_id,
                entry_data["decision_day"],
                entry_data.get("decision_date", ""),
                entry_data["pop_size"],
                entry_data.get("new_infections_per_1000", 0.0),
                entry_data.get("new_diagnoses_per_1000", 0.0),
                entry_data.get("r_eff_value", 0.0),
                entry_data.get("r_eff_trend", "flat"),
                entry_data.get("r_eff_source", "unavailable"),
                entry_data.get("growth_ratio", 0.0),
                entry_data.get("tests_per_1000", 0.0),
                entry_data.get("quarantined_per_1000", 0.0),
                entry_data.get("teaching_restriction", 0),
                entry_data.get("online_teaching", 0),
                entry_data.get("infection_trend", "flat"),
                entry_data.get("diagnosis_trend", "flat"),
                entry_data.get("risk_trend", "stable"),
                entry_data.get("layer_contributions", "{}"),
                entry_data.get("layer_transmission_trends", "{}"),
                entry_data.get("policy_requested", ""),
                entry_data.get("policy_executed", ""),
                entry_data.get("policy_rank", 0),
                entry_data.get("risk_level", ""),
                entry_data.get("execution_feedback"),
                entry_data.get("state_summary_text", ""),
            ),
        )
        entry_id = cur.lastrowid

        self._conn.execute(
            "INSERT INTO memory_vectors "
            "(entry_id, state_vector, layer_vector, trend_context, text_embedding) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                entry_id,
                json.dumps(state_vector.tolist() if hasattr(state_vector, "tolist") else state_vector),
                json.dumps(layer_vector.tolist() if hasattr(layer_vector, "tolist") else layer_vector),
                json.dumps(trend_context, ensure_ascii=False) if trend_context else None,
                json.dumps(text_embedding.tolist() if hasattr(text_embedding, "tolist") else text_embedding),
            ),
        )
        self._conn.commit()
        return entry_id

    def finalize_pending_entry(self, simulation_id: str, current_day: int,
                               sim, policy_catalog: dict,
                               window_days: int = 7) -> int:
        """Finalize the most recent pending entry with execution feedback."""
        if self.read_only:
            raise ReadOnlyError("Cannot finalize entry in read-only store")

        row = self._conn.execute(
            "SELECT entry_id, decision_day, policy_executed FROM memory_entries "
            "WHERE simulation_id=? AND feedback_status='pending' "
            "ORDER BY decision_day DESC LIMIT 1",
            (simulation_id,),
        ).fetchone()
        if row is None:
            return -1

        entry_id = row["entry_id"]
        decision_day = row["decision_day"]
        policy_executed = row["policy_executed"]

        feedback_start = decision_day
        feedback_end = current_day - 1
        days_observed = max(0, feedback_end - feedback_start + 1)

        if days_observed <= 0:
            return -1

        # compute feedback from sim.results
        feedback = _compute_execution_feedback(
            sim, feedback_start, feedback_end, policy_executed, policy_catalog
        )

        status = "complete" if days_observed >= window_days else "partial"

        self._conn.execute(
            "UPDATE memory_entries SET "
            "  feedback_status=?, feedback_start_day=?, feedback_end_day=?, "
            "  execution_feedback=?, finalized_at=datetime('now') "
            "WHERE entry_id=?",
            (status, feedback_start, feedback_end,
             json.dumps(feedback, ensure_ascii=False), entry_id),
        )
        self._conn.commit()
        return entry_id

    # -- short-term memory read --

    def get_recent_completed_entries(self, simulation_id: str, n: int,
                                     before_day: Optional[int] = None) -> list[dict]:
        """Return recent n completed/partial entries for a simulation, ASC order."""
        query = (
            "SELECT e.*, v.state_vector, v.layer_vector, v.trend_context, v.text_embedding "
            "FROM memory_entries e "
            "LEFT JOIN memory_vectors v ON e.entry_id = v.entry_id "
            "WHERE e.simulation_id=? "
            "AND e.feedback_status IN ('complete', 'partial') "
        )
        params: list = [simulation_id]
        if before_day is not None:
            query += "AND e.decision_day < ? "
            params.append(before_day)
        query += "ORDER BY e.decision_day DESC LIMIT ?"
        params.append(n)

        rows = self._conn.execute(query, params).fetchall()
        entries = [_row_to_dict(r) for r in rows]
        entries.reverse()  # ASC order
        return entries

    # -- global candidate retrieval --

    def get_candidate_entries_with_vectors(
        self,
        feedback_status: str = "complete",
        exclude_simulation_id: Optional[str] = None,
        exclude_entry_ids: Optional[list[int]] = None,
        before_day: Optional[int] = None,
    ) -> list[dict]:
        query = (
            "SELECT e.*, v.state_vector, v.layer_vector, v.trend_context, v.text_embedding "
            "FROM memory_entries e "
            "LEFT JOIN memory_vectors v ON e.entry_id = v.entry_id "
            "WHERE e.feedback_status=? "
        )
        params: list = [feedback_status]
        if exclude_simulation_id is not None:
            query += "AND e.simulation_id != ? "
            params.append(exclude_simulation_id)
        if before_day is not None:
            query += "AND e.decision_day < ? "
            params.append(before_day)
        rows = self._conn.execute(query, params).fetchall()
        entries = [_row_to_dict(r) for r in rows]
        if exclude_entry_ids:
            exclude_set = set(exclude_entry_ids)
            entries = [e for e in entries if e["entry_id"] not in exclude_set]
        return entries

    def hydrate_entries(self, entry_ids: list[int]) -> list[dict]:
        if not entry_ids:
            return []
        placeholders = ",".join("?" * len(entry_ids))
        rows = self._conn.execute(
            f"SELECT * FROM memory_entries WHERE entry_id IN ({placeholders})",
            entry_ids,
        ).fetchall()
        return [_row_to_dict(r) for r in rows]

    # -- embedding --

    def compute_text_embedding(self, text: str) -> np.ndarray:
        return self._embedding_provider.encode(text)

    # -- lifecycle --

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None


def _row_to_dict(row: sqlite3.Row) -> dict:
    return dict(row)


# ---------------------------------------------------------------------------
# Execution feedback computation
# ---------------------------------------------------------------------------

def _compute_execution_feedback(sim, start_day: int, end_day: int,
                                policy_executed: str,
                                policy_catalog: dict) -> dict:
    """Compute raw execution feedback metrics for a finalized entry."""
    from . import llm_policy as cvlp

    new_infections = cvlp._result_values(sim, "new_infections")
    new_tests = cvlp._result_values(sim, "new_tests")
    n_quarantined = cvlp._result_values(sim, "n_quarantined")

    if new_infections.size == 0:
        return {
            "days_observed": 0,
            "infection_change": 0.0,
            "infection_trend": "flat",
            "tests_sum": 0.0,
            "mean_quarantined": 0.0,
            "teaching_restriction": 0,
            "online_teaching": False,
        }

    s = max(0, min(start_day, new_infections.size - 1))
    e = max(s, min(end_day, new_infections.size - 1))
    inf_window = new_infections[s:e + 1]
    test_window = new_tests[s:e + 1] if new_tests.size else np.array([], dtype=float)
    quar_window = n_quarantined[s:e + 1] if n_quarantined.size else np.array([], dtype=float)

    # lookback: equal-length window before start
    lookback_start = max(0, s - len(inf_window))
    prev_window = new_infections[lookback_start:s] if s > 0 else np.array([], dtype=float)

    current_sum = float(inf_window.sum()) if len(inf_window) else 0.0
    previous_sum = float(prev_window.sum()) if len(prev_window) else 0.0

    profile = policy_catalog.get(policy_executed, {}) if isinstance(policy_catalog, dict) else {}

    return {
        "days_observed": int(max(0, e - s + 1)),
        "infection_change": round(current_sum - previous_sum, 4),
        "infection_trend": cvlp._trend_label(inf_window, prev_window),
        "tests_sum": round(float(test_window.sum()) if len(test_window) else 0.0, 4),
        "mean_quarantined": round(float(quar_window.mean()) if len(quar_window) else 0.0, 4),
        "teaching_restriction": profile.get("restriction_intensity", 0),
        "online_teaching": bool(profile.get("online_teaching_active", False)),
    }


# ---------------------------------------------------------------------------
# Vector builders
# ---------------------------------------------------------------------------

# Normalization ranges for state_vector (8 dims)
_STATE_RANGES = [
    (0.0, 50.0),   # new_infections_per_1000
    (0.0, 30.0),   # new_diagnoses_per_1000
    (0.0, 4.0),    # r_eff_value
    (0.0, 3.0),    # growth_ratio
    (0.0, 150.0),  # tests_per_1000
    (0.0, 80.0),   # quarantined_per_1000
    (0.0, 4.0),    # teaching_restriction
    (0.0, 1.0),    # online_teaching
]


def _normalize(value: float, lo: float, hi: float) -> float:
    if hi <= lo:
        return 0.0
    return max(0.0, min(1.0, (value - lo) / (hi - lo)))


def build_state_vector(state: dict) -> np.ndarray:
    """Build 8-dim normalized state vector from extract_campus_policy_state output."""
    summary = state.get("past_7d_summary", {})
    burden = state.get("intervention_burden_last_7d", {})
    raw = [
        float(state.get("new_infections_per_1000_last_7d", 0.0)),
        float(summary.get("new_diagnoses_sum", 0.0)) * 1000.0 / max(1, state.get("_scaled_pop", 1)),
        float(state.get("r_eff_mean", 0.0)),
        float(state.get("growth_ratio_7d_vs_prev_7d", 0.0)),
        float(burden.get("tests_per_1000", 0.0)),
        float(burden.get("mean_quarantined_per_1000", 0.0)),
        float(burden.get("teaching_restriction_intensity", 0)),
        float(state.get("online_teaching_active", False)),
    ]
    return np.array([_normalize(v, lo, hi) for v, (lo, hi) in zip(raw, _STATE_RANGES)])


def build_layer_vector(state: dict) -> np.ndarray:
    """Build 4-dim layer contribution vector from extract_campus_policy_state output."""
    layer_counts = state.get("layer_transmission_last_7d", {})
    if not layer_counts:
        return np.zeros(4)
    d = float(layer_counts.get("d", 0))
    clu = float(layer_counts.get("clu", 0))
    clg = float(layer_counts.get("clg", 0))
    of_ = float(layer_counts.get("of", 0))
    ta = float(layer_counts.get("ta", 0))
    cm = float(layer_counts.get("cm", 0))
    total = d + clu + clg + of_ + ta + cm
    if total <= 0:
        return np.zeros(4)
    return np.array([
        d / total,
        (clu + clg) / total,
        (of_ + ta) / total,
        cm / total,
    ])


def _compute_layer_shares(layer_counts: dict) -> dict:
    d = float(layer_counts.get("d", 0))
    clu = float(layer_counts.get("clu", 0))
    clg = float(layer_counts.get("clg", 0))
    of_ = float(layer_counts.get("of", 0))
    ta = float(layer_counts.get("ta", 0))
    cm = float(layer_counts.get("cm", 0))
    total = d + clu + clg + of_ + ta + cm
    if total <= 0:
        return {"dorm": 0.0, "classroom": 0.0, "office_lab": 0.0, "community": 0.0}
    return {
        "dorm": d / total,
        "classroom": (clu + clg) / total,
        "office_lab": (of_ + ta) / total,
        "community": cm / total,
    }


def build_trend_context(recent_entries: list[dict], current_state: dict,
                        window: int = 3) -> dict:
    """Build m-period trend context from recent entries + current state."""
    history = recent_entries[-(window - 1):] if recent_entries else []
    scaled_pop = current_state.get("_scaled_pop", 1) or 1

    infections_seq = [float(e.get("new_infections_per_1000", 0.0)) for e in history]
    infections_seq.append(float(current_state.get("new_infections_per_1000_last_7d", 0.0)))

    summary = current_state.get("past_7d_summary", {})
    diag_per_1000 = float(summary.get("new_diagnoses_sum", 0.0)) * 1000.0 / max(1, scaled_pop)
    diagnoses_seq = [float(e.get("new_diagnoses_per_1000", 0.0)) for e in history]
    diagnoses_seq.append(diag_per_1000)

    r_eff_seq = [float(e.get("r_eff_value", 0.0)) for e in history]
    r_eff_seq.append(float(current_state.get("r_eff_mean", 0.0)))

    layer_shares_history = []
    for e in history:
        lc = e.get("layer_contributions", "{}")
        if isinstance(lc, str):
            try:
                lc = json.loads(lc)
            except (json.JSONDecodeError, TypeError):
                lc = {}
        layer_shares_history.append(_compute_layer_shares(lc))

    current_layer = current_state.get("layer_transmission_last_7d", {})
    layer_shares_history.append(_compute_layer_shares(current_layer))

    return {
        "window": len(infections_seq),
        "new_infections_per_1000": infections_seq,
        "new_diagnoses_per_1000": diagnoses_seq,
        "r_eff": r_eff_seq,
        "dorm_share": [ls["dorm"] for ls in layer_shares_history],
        "classroom_share": [ls["classroom"] for ls in layer_shares_history],
        "office_lab_share": [ls["office_lab"] for ls in layer_shares_history],
        "community_share": [ls["community"] for ls in layer_shares_history],
    }


# ---------------------------------------------------------------------------
# Similarity functions
# ---------------------------------------------------------------------------

def state_distance_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Normalized Euclidean distance similarity for [0,1] vectors."""
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    d = len(a)
    dist = float(np.linalg.norm(a - b))
    max_dist = math.sqrt(d)
    return max(0.0, 1.0 - dist / max_dist) if max_dist > 0 else 0.0


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    norm_a, norm_b = np.linalg.norm(a), np.linalg.norm(b)
    if norm_a < 1e-10 or norm_b < 1e-10:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def pearson_similarity(x: list[float], y: list[float]) -> Optional[float]:
    """Pearson similarity mapped to [0, 1]. Returns None if insufficient."""
    if len(x) != len(y) or len(x) < 2:
        return None
    xa, ya = np.array(x, dtype=float), np.array(y, dtype=float)
    x_const = np.std(xa) < 1e-10
    y_const = np.std(ya) < 1e-10
    if x_const and y_const:
        return 1.0
    if x_const or y_const:
        return 0.5
    r = np.corrcoef(xa, ya)[0, 1]
    if np.isnan(r):
        return None
    return float((r + 1.0) / 2.0)


_TREND_METRICS = [
    "new_infections_per_1000", "new_diagnoses_per_1000", "r_eff",
    "dorm_share", "classroom_share", "office_lab_share", "community_share",
]


def compute_trend_similarity(current_ctx: dict, history_ctx: dict) -> Optional[float]:
    """Pearson similarity across 7 trend metrics, mean of valid scores."""
    scores = []
    for m in _TREND_METRICS:
        s = pearson_similarity(
            current_ctx.get(m, []),
            history_ctx.get(m, []),
        )
        if s is not None:
            scores.append(s)
    if not scores:
        return None
    return float(np.mean(scores))


_DEFAULT_LAMBDAS = {"state": 0.30, "layer": 0.25, "trend": 0.20, "text": 0.25}


def combine_similarity(parts: dict, lambdas: Optional[dict] = None) -> float:
    """Weighted combination of similarity components, renormalizing for None values."""
    lam = lambdas or _DEFAULT_LAMBDAS
    valid = {k: v for k, v in parts.items() if v is not None}
    denom = sum(lam.get(k, 0.0) for k in valid)
    if denom <= 0:
        return 0.0
    return sum(lam.get(k, 0.0) * valid[k] for k in valid) / denom


# ---------------------------------------------------------------------------
# State description text builder (for S_text embedding)
# ---------------------------------------------------------------------------

def build_state_description_text(state: dict) -> str:
    """Build a short state description for text embedding (pre-decision state only)."""
    inf = state.get("new_infections_per_1000_last_7d", 0.0)
    summary = state.get("past_7d_summary", {})
    inf_trend = summary.get("new_infections_trend", "flat")
    r_eff = state.get("r_eff_mean", 0.0)
    layer_counts = state.get("layer_transmission_last_7d", {})
    dominant = max(layer_counts, key=layer_counts.get) if layer_counts else "unknown"
    risk = summary.get("estimated_risk_trend", "stable")
    return (
        f"新增感染{inf:.2f}‰, 感染趋势{inf_trend}, "
        f"R_eff={r_eff:.2f}, 主导传播层{dominant}, 风险{risk}"
    )


# ---------------------------------------------------------------------------
# Policy rank helper
# ---------------------------------------------------------------------------

_POLICY_RANK_MAP = {
    "P0_normal": 0,
    "P1_guarded": 1,
    "P2_moderate": 2,
    "P3_strong": 3,
    "P4_emergency": 4,
}


def _get_policy_rank(policy_id: str) -> int:
    return _POLICY_RANK_MAP.get(policy_id, -1)


# ---------------------------------------------------------------------------
# Pending entry builder
# ---------------------------------------------------------------------------

def build_pending_memory_entry(state: dict, record: dict, sim) -> dict:
    """Build entry_data dict for create_pending_entry. No execution_feedback yet."""
    scaled_pop = getattr(sim, "scaled_pop_size", None) or sim["pop_size"]
    summary = state.get("past_7d_summary", {})
    burden = state.get("intervention_burden_last_7d", {})
    return {
        "decision_day": int(record["decision_day"]),
        "decision_date": str(record.get("decision_date", "")),
        "pop_size": int(scaled_pop),
        "new_infections_per_1000": float(state.get("new_infections_per_1000_last_7d", 0.0)),
        "new_diagnoses_per_1000": round(
            float(summary.get("new_diagnoses_sum", 0.0)) * 1000.0 / max(1, scaled_pop), 6),
        "r_eff_value": float(state.get("r_eff_mean", 0.0)),
        "r_eff_trend": str(state.get("r_eff_trend", "flat")),
        "r_eff_source": str(state.get("r_eff_source", "unavailable")),
        "growth_ratio": float(state.get("growth_ratio_7d_vs_prev_7d", 0.0)),
        "tests_per_1000": float(burden.get("tests_per_1000", 0.0)),
        "quarantined_per_1000": float(burden.get("mean_quarantined_per_1000", 0.0)),
        "teaching_restriction": int(burden.get("teaching_restriction_intensity", 0)),
        "online_teaching": int(state.get("online_teaching_active", False)),
        "infection_trend": str(summary.get("new_infections_trend", "flat")),
        "diagnosis_trend": str(summary.get("new_diagnoses_trend", "flat")),
        "risk_trend": str(summary.get("estimated_risk_trend", "stable")),
        "layer_contributions": json.dumps(
            state.get("layer_transmission_last_7d", {}), ensure_ascii=False),
        "layer_transmission_trends": json.dumps(
            state.get("layer_transmission_trends", {}), ensure_ascii=False),
        "policy_requested": str(record.get("model_policy_proposed", "")),
        "policy_executed": str(record.get("applied_policy", "")),
        "policy_rank": _get_policy_rank(record.get("applied_policy", "P0_normal")),
        "risk_level": str(record.get("risk_level", "")),
        "execution_feedback": None,
        "state_summary_text": build_state_description_text(state),
        "feedback_status": "pending",
    }


# ---------------------------------------------------------------------------
# Short-term trajectory compression
# ---------------------------------------------------------------------------

def compress_short_term_trajectory(
    recent_entries: list[dict],
    current_state: dict,
    policy_catalog: dict,
) -> dict:
    """Compress recent decision cycles into trajectory summary."""
    n = len(recent_entries)
    if n == 0:
        return {
            "n_periods": 0,
            "strategy_path": {
                "label": "maintaining",
                "rank_sequence": [],
                "policy_sequence": [],
            },
            "epidemic_trend": {
                "label": "fluctuating",
                "infection_direction": "flat",
                "r_eff_direction": "flat",
                "growth_ratio_current": 0.0,
            },
            "adjustment_stability": {
                "label": "no_recent_change",
                "last_change_day": None,
                "last_change_direction": None,
                "observation_periods": 0,
            },
            "summary_text": "无历史决策记录。",
        }

    rank_sequence = [int(e.get("policy_rank", 0)) for e in recent_entries]
    policy_sequence = [str(e.get("policy_executed", "")) for e in recent_entries]

    path_label = _compute_strategy_path_label(rank_sequence)
    trend_label, inf_dir, r_dir, gr_current = _compute_epidemic_trend(recent_entries, current_state)
    stability = _compute_adjustment_stability(recent_entries)

    compressed = {
        "n_periods": n,
        "strategy_path": {
            "label": path_label,
            "rank_sequence": rank_sequence,
            "policy_sequence": policy_sequence,
        },
        "epidemic_trend": {
            "label": trend_label,
            "infection_direction": inf_dir,
            "r_eff_direction": r_dir,
            "growth_ratio_current": gr_current,
        },
        "adjustment_stability": stability,
        "summary_text": "",
    }
    compressed["summary_text"] = _render_trajectory_summary(compressed)
    return compressed


def _compute_strategy_path_label(rank_sequence: list[int]) -> str:
    if len(rank_sequence) <= 1:
        return "maintaining"
    diffs = [rank_sequence[i + 1] - rank_sequence[i] for i in range(len(rank_sequence) - 1)]
    if all(d == 0 for d in diffs):
        return "maintaining"
    if all(d >= 0 for d in diffs) and any(d > 0 for d in diffs):
        return "escalating"
    if all(d <= 0 for d in diffs) and any(d < 0 for d in diffs):
        return "de_escalating"
    return "fluctuating"


def _compute_epidemic_trend(recent_entries: list[dict],
                            current_state: dict) -> tuple[str, str, str, float]:
    n = len(recent_entries)
    up_count = sum(1 for e in recent_entries if e.get("infection_trend") == "up")
    down_count = sum(1 for e in recent_entries if e.get("infection_trend") == "down")
    threshold = math.ceil(n / 2)

    if up_count >= threshold:
        label = "continued_growth"
    elif down_count >= threshold:
        label = "sustained_relief"
    else:
        label = "fluctuating"

    last = recent_entries[-1]
    inf_dir = str(last.get("infection_trend", "flat"))
    r_dir = str(last.get("r_eff_trend", "flat"))
    gr = float(current_state.get("growth_ratio_7d_vs_prev_7d", 0.0))
    return label, inf_dir, r_dir, gr


def _compute_adjustment_stability(recent_entries: list[dict]) -> dict:
    n = len(recent_entries)
    if n == 0:
        return {
            "label": "no_recent_change",
            "last_change_day": None,
            "last_change_direction": None,
            "observation_periods": 0,
        }

    # reverse scan for last policy change
    change_idx = None
    for i in range(n - 1, 0, -1):
        if recent_entries[i].get("policy_rank") != recent_entries[i - 1].get("policy_rank"):
            change_idx = i
            break

    if change_idx is None:
        return {
            "label": "no_recent_change",
            "last_change_day": int(recent_entries[-1].get("decision_day", -1)),
            "last_change_direction": None,
            "observation_periods": n,
        }

    prev_rank = int(recent_entries[change_idx - 1].get("policy_rank", 0))
    curr_rank = int(recent_entries[change_idx].get("policy_rank", 0))
    change_dir = "upgrade" if curr_rank > prev_rank else "downgrade"
    change_day = int(recent_entries[change_idx].get("decision_day", -1))

    # entries after the change (observation window)
    obs_entries = recent_entries[change_idx + 1:]
    obs_count = len(obs_entries)

    if obs_count < 2:
        return {
            "label": "insufficient_observation",
            "last_change_day": change_day,
            "last_change_direction": change_dir,
            "observation_periods": obs_count,
        }

    # classify each observation period
    improved = 0
    rebounded = 0
    for e in obs_entries:
        inf_trend = e.get("infection_trend", "flat")
        # high risk layer share check
        lc = e.get("layer_contributions", "{}")
        if isinstance(lc, str):
            try:
                lc = json.loads(lc)
            except (json.JSONDecodeError, TypeError):
                lc = {}
        shares = _compute_layer_shares(lc)
        dominant_layer = max(shares, key=shares.get) if shares else None
        dominant_share = shares.get(dominant_layer, 0.0) if dominant_layer else 0.0

        is_improved = (inf_trend == "down")
        is_rebound = (inf_trend == "up")
        if is_improved:
            improved += 1
        if is_rebound:
            rebounded += 1

    # mutually exclusive priority rules
    if improved == obs_count:
        label = "consistent_improvement"
    elif rebounded > 0 and improved > 0:
        label = "mixed_feedback"
    elif rebounded > 0:
        label = "rebound_observed"
    else:
        label = "no_rebound"

    return {
        "label": label,
        "last_change_day": change_day,
        "last_change_direction": change_dir,
        "observation_periods": obs_count,
    }


# Chinese mapping for trajectory summary
_PATH_CN = {
    "maintaining": "持续维持",
    "escalating": "逐步升级",
    "de_escalating": "逐步降级",
    "fluctuating": "频繁切换",
}
_TREND_CN = {
    "sustained_relief": "持续缓解",
    "continued_growth": "继续上升",
    "fluctuating": "波动",
}
_STABILITY_CN = {
    "no_recent_change": "近期无策略调整",
    "insufficient_observation": "观察期不足",
    "consistent_improvement": "连续改善",
    "mixed_feedback": "反馈方向不一致",
    "rebound_observed": "观察到反弹",
}


def _render_trajectory_summary(compressed: dict) -> str:
    n = compressed["n_periods"]
    path = compressed["strategy_path"]
    trend = compressed["epidemic_trend"]
    stability = compressed["adjustment_stability"]

    path_cn = _PATH_CN.get(path["label"], path["label"])
    trend_cn = _TREND_CN.get(trend["label"], trend["label"])
    pol_seq = ",".join(path.get("policy_sequence", []))

    # no_rebound: direction-aware rendering
    stab_label = stability["label"]
    if stab_label == "no_rebound":
        if stability.get("last_change_direction") == "upgrade":
            stab_cn = "未观察到继续恶化"
        else:
            stab_cn = "未观察到反弹"
    else:
        stab_cn = _STABILITY_CN.get(stab_label, stab_label)

    change_dir_cn = ""
    if stability.get("last_change_direction") == "upgrade":
        change_dir_cn = "升级"
    elif stability.get("last_change_direction") == "downgrade":
        change_dir_cn = "降级"

    day = stability.get("last_change_day", "?")

    parts = [f"近{n}周策略{path_cn}({pol_seq})。"]
    parts.append(
        f"疫情趋势{trend_cn}（感染{trend['infection_direction']}，"
        f"R_eff {trend['r_eff_direction']}，增长率{trend['growth_ratio_current']:.3f}）。"
    )
    if change_dir_cn and day is not None:
        parts.append(f"最近一次{change_dir_cn}（第{day}天）：{stab_cn}。")
    else:
        parts.append(f"{stab_cn}。")
    return "".join(parts)


# ---------------------------------------------------------------------------
# Similar scenario retrieval
# ---------------------------------------------------------------------------

def retrieve_similar_scenarios(
    current_state: dict,
    current_trend_context: dict,
    memory_store: MemoryStore,
    top_k: int = 6,
    cases_per_group: int = 2,
    lambdas: Optional[dict] = None,
    exclude_entry_ids: Optional[list[int]] = None,
) -> dict:
    """Retrieve and group similar historical scenarios from memory_store."""
    lam = lambdas or _DEFAULT_LAMBDAS

    # build current vectors
    cur_sv = build_state_vector(current_state)
    cur_lv = build_layer_vector(current_state)
    cur_text = build_state_description_text(current_state)
    cur_text_emb = memory_store.compute_text_embedding(cur_text)

    # fetch candidates
    candidates = memory_store.get_candidate_entries_with_vectors(
        feedback_status="complete",
        exclude_entry_ids=exclude_entry_ids,
    )

    if not candidates:
        return {"retrieved_count": 0, "policy_groups": {}, "summary_text": "无历史相似情景。"}

    scored = []
    for c in candidates:
        # parse stored vectors
        try:
            c_sv = np.array(json.loads(c["state_vector"]), dtype=float)
        except (json.JSONDecodeError, TypeError):
            c_sv = np.zeros(8)
        try:
            c_lv = np.array(json.loads(c["layer_vector"]), dtype=float)
        except (json.JSONDecodeError, TypeError):
            c_lv = np.zeros(4)
        try:
            c_tc = json.loads(c["trend_context"]) if c.get("trend_context") else None
        except (json.JSONDecodeError, TypeError):
            c_tc = None
        try:
            c_te = np.array(json.loads(c["text_embedding"]), dtype=float)
        except (json.JSONDecodeError, TypeError):
            c_te = np.zeros(384)

        s_state = state_distance_similarity(cur_sv, c_sv)
        s_layer = cosine_similarity(cur_lv, c_lv)
        s_trend = compute_trend_similarity(current_trend_context, c_tc) if (
            current_trend_context and c_tc) else None
        s_text = cosine_similarity(cur_text_emb, c_te)

        combined = combine_similarity(
            {"state": s_state, "layer": s_layer, "trend": s_trend, "text": s_text},
            lam,
        )
        scored.append((combined, c))

    scored.sort(key=lambda x: x[0], reverse=True)
    top_entries = scored[:top_k]

    # hydrate full details for top-K
    top_ids = [c["entry_id"] for _, c in top_entries]
    full_entries = {e["entry_id"]: e for e in memory_store.hydrate_entries(top_ids)}

    # group by policy_executed
    groups: dict[str, list] = {}
    for sim_score, c in top_entries:
        full = full_entries.get(c["entry_id"], c)
        pol = full.get("policy_executed", "unknown")
        if pol not in groups:
            groups[pol] = []
        exec_fb = full.get("execution_feedback")
        if isinstance(exec_fb, str):
            try:
                exec_fb = json.loads(exec_fb)
            except (json.JSONDecodeError, TypeError):
                exec_fb = {}
        elif exec_fb is None:
            exec_fb = {}

        lc = full.get("layer_contributions", "{}")
        if isinstance(lc, str):
            try:
                lc = json.loads(lc)
            except (json.JSONDecodeError, TypeError):
                lc = {}

        groups[pol].append({
            "entry_id": int(full.get("entry_id", c["entry_id"])),
            "similarity": round(sim_score, 4),
            "risk_level": full.get("risk_level", ""),
            "dominant_layer": max(lc, key=lc.get) if lc else "unknown",
            "infection_trend_at_time": full.get("infection_trend", "flat"),
            "infections_per_1000": full.get("new_infections_per_1000", 0.0),
            "growth_ratio": full.get("growth_ratio", 0.0),
            "layer_contributions": lc,
            "policy_executed": pol,
            "execution_feedback": exec_fb,
        })

    # cap per group
    for pol in groups:
        groups[pol] = groups[pol][:cases_per_group]

    summary_text = _render_similar_scenarios_summary(groups)
    total = sum(len(v) for v in groups.values())
    return {
        "retrieved_count": total,
        "entry_ids": [int(case["entry_id"]) for cases in groups.values() for case in cases],
        "policy_groups": groups,
        "summary_text": summary_text,
    }


def _render_similar_scenarios_summary(groups: dict) -> str:
    if not groups:
        return "无历史相似情景。"
    total = sum(len(v) for v in groups.values())
    lines = [f"历史相似情景（共{total}例）:"]
    for pol, cases in sorted(groups.items()):
        scores = [c["similarity"] for c in cases]
        rng = f"{min(scores):.2f}-{max(scores):.2f}" if scores else "?"
        lines.append(f"[{pol}, {len(cases)}例, 相似度{rng}]:")
        for i, c in enumerate(cases, 1):
            fb = c.get("execution_feedback", {})
            inf_delta = fb.get("infection_change", 0.0)
            quar = fb.get("mean_quarantined", 0.0)
            lines.append(
                f"  · 案例{i}(相似度{c['similarity']:.2f}): "
                f"风险{c['risk_level']}, 主导层{c['dominant_layer']}, "
                f"感染{c['infections_per_1000']:.2f}‰, 增长率{c['growth_ratio']:.3f}。"
                f"\n    执行后: 感染变化{inf_delta:+.1f}, 隔离{quar:.1f}人。"
            )
    return "\n".join(lines)
