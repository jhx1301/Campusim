"""Campus scene construction and private, fixed population registration."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from fractions import Fraction
from math import ceil, isfinite
from types import MappingProxyType
from typing import Any

import numpy as np

from .protocol import ControlProtocol
from .types import AGE_BANDS, PublicPopulation, PublicResources


@dataclass(frozen=True, slots=True, eq=False)
class PopulationRegistry:
    """Fixed rosters and nominal time budgets; only aggregates reach policies."""

    public_population: PublicPopulation
    school_indices: tuple[int, ...]
    work_indices: tuple[int, ...]
    screening_groups: tuple[tuple[int, ...], tuple[int, ...], tuple[int, ...]]
    school_weights: np.ndarray = field(repr=False)
    work_weights: np.ndarray = field(repr=False)
    community_weights: np.ndarray = field(repr=False)
    layer_groups: Mapping[str, tuple[str, ...]]

    def __deepcopy__(self, memo):
        # All registration objects are fixed for the life of an initialized world.
        return self


def _roster(groups, population: int) -> tuple[int, ...]:
    indices = set()
    for group in groups:
        for kind in ("students", "teachers"):
            for raw_index in group[kind]:
                if (not isinstance(raw_index, (int, np.integer))
                        or isinstance(raw_index, (bool, np.bool_))
                        or not 0 <= int(raw_index) < population):
                    raise ValueError("registration group contains an invalid person index")
                indices.add(int(raw_index))
    return tuple(sorted(indices))


def build_population_registry(people) -> PopulationRegistry:
    """Use persistent teaching/lab membership, never today's contact edges."""
    ages = np.asarray(people.age)
    population = len(ages)
    if (population == 0 or not np.isfinite(ages).all()
            or np.any(ages < 0) or np.any(ages >= 100)):
        raise ValueError("registered ages must be finite and within [0, 100)")
    if not all(hasattr(people, name) for name in
               ("class_groups_ug", "class_groups_gr", "lab_groups")):
        raise ValueError("campus people require persistent teaching and lab groups")
    whole_ages = np.floor(ages).astype(int)
    age_counts = tuple(int(np.count_nonzero((whole_ages >= lo) & (whole_ages <= hi)))
                       for lo, hi in AGE_BANDS)
    school = _roster((*people.class_groups_ug, *people.class_groups_gr), population)
    work = _roster(people.lab_groups, population)
    school_set, work_set = set(school), set(work)
    both = school_set & work_set
    non_school_work = tuple(sorted(work_set - school_set))
    other = tuple(sorted(set(range(population)) - school_set - work_set))

    school_weights = np.zeros(population)
    work_weights = np.zeros(population)
    community_weights = np.full(population, 0.2)
    school_weights[list(school)] = 0.8
    work_weights[list(work)] = 0.8
    school_weights[list(both)] = 0.4
    work_weights[list(both)] = 0.4
    community_weights[list(other)] = 1.0
    for weights in (school_weights, work_weights, community_weights):
        weights.setflags(write=False)
    public = PublicPopulation(population, age_counts, len(school), len(work), len(both))
    return PopulationRegistry(
        public, school, work, (school, non_school_work, other),
        school_weights, work_weights, community_weights,
        MappingProxyType({"home": ("d", "ta"), "school": ("clu", "clg"),
                          "work": ("of",), "community": ("cm",)}),
    )


@dataclass(frozen=True, slots=True)
class ScenarioBundle:
    """Runner-owned simulation and adapters; controllers see only observations."""

    sim: Any
    executor: Any
    public_analyzer: Any
    private_analyzer: Any
    private_metadata: Mapping[str, Any] = field(repr=False)

    @property
    def registry(self) -> PopulationRegistry:
        return self.executor.registry


def _thaw(value):
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _positive_int(value, name: str, *, minimum: int = 1) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an ordinary integer >= {minimum}")
    return value


def build_scenario(protocol: ControlProtocol, world_seed: int, *, population=None,
                   execution_days=None, initial_infections=None, beta=None,
                   screening_capacity_ratio=None, purpose="smoke") -> ScenarioBundle:
    """Build once; smoke beta is explicit and never labelled as E0 calibration.

    Scientific construction requires an explicit beta supplied by the caller.
    Reading and verifying a calibration artifact belongs to the later runner.
    """
    if type(protocol) is not ControlProtocol:
        raise TypeError("protocol must be ControlProtocol")
    if type(world_seed) is not int or not 0 <= world_seed < 2**32:
        raise ValueError("world_seed must be an ordinary integer within [0, 2**32)")
    if purpose not in ("smoke", "scientific"):
        raise ValueError("purpose must be smoke or scientific")
    engine = protocol.definition["engine"]
    if engine["pop_type"] != "campus":
        raise ValueError("Phase 2 scenario construction supports campus only")
    population = _positive_int(protocol.population if population is None else population,
                               "population")
    execution_days = _positive_int(
        protocol.execution_days if execution_days is None else execution_days,
        "execution_days", minimum=2,
    )
    initial_infections = _positive_int(
        protocol.initial_infections if initial_infections is None else initial_infections,
        "initial_infections", minimum=0,
    )
    if initial_infections > population:
        raise ValueError("initial_infections cannot exceed population")
    if purpose == "scientific" and beta is None:
        raise ValueError("scientific scenarios require explicit calibration beta")
    beta_source = "protocol_smoke_beta" if beta is None else "caller_explicit_beta"
    beta = engine["smoke_beta"] if beta is None else beta
    if type(beta) not in (int, float) or not isfinite(beta) or beta < 0:
        raise ValueError("beta must be a finite nonnegative number")
    resource_spec = protocol.definition["resources"]
    screening_ratio = (resource_spec["screening_main_capacity_ratio"]
                       if screening_capacity_ratio is None else screening_capacity_ratio)
    if (type(screening_ratio) not in (int, float) or not isfinite(screening_ratio)
            or not 0 <= screening_ratio <= 1):
        raise ValueError("screening_capacity_ratio must be finite within [0, 1]")
    resources = PublicResources(
        ceil(Fraction(str(resource_spec["clinical_tests_per_person_per_day"])) * population),
        ceil(Fraction(str(screening_ratio)) * population),
        ceil(Fraction(str(resource_spec["tracing_index_cases_per_person_per_day"])) * population),
    )

    # Local imports keep action/observation contracts independent of the engine.
    import covasim as cv
    from .execution import JointActionExecutor
    from .ledger import PublicLedgerAnalyzer
    from .metrics import PrivateMetricsAnalyzer

    supported = cv.make_pars()
    pars = {key: _thaw(value) for key, value in engine.items() if key in supported}
    pars.update(pop_size=population, pop_infected=initial_infections,
                n_days=execution_days - 1, beta=beta, rand_seed=world_seed, verbose=0,
                iso_factor=dict(d=.3, clu=.1, clg=.1, of=.1, ta=.2, cm=.1),
                quar_factor=dict(d=.6, clu=.2, clg=.2, of=.2, ta=.4, cm=.2))
    executor = JointActionExecutor(protocol, resources)
    public_analyzer = PublicLedgerAnalyzer(executor)
    private_analyzer = PrivateMetricsAnalyzer(initial_infections)
    sim = cv.Sim(pars=pars, interventions=[executor],
                 analyzers=[public_analyzer, private_analyzer])
    sim.initialize()
    # Use mounted adapters so their state is the state advanced by sim.step().
    executor = sim["interventions"][0]
    public_analyzer, private_analyzer = sim["analyzers"]
    metadata = MappingProxyType({
        "world_seed": world_seed, "purpose": purpose, "beta": beta,
        "beta_provenance": beta_source, "calibration_verified": False,
        "protocol_sha256": protocol.source_sha256, "execution_days": execution_days,
        "initial_infections": initial_infections,
        "registration": MappingProxyType({
            key: tuple(int(index) for index in indices)
            for key, indices in sim.people.campus_registry_metadata.items()
        }),
    })
    return ScenarioBundle(sim, executor, public_analyzer, private_analyzer, metadata)
