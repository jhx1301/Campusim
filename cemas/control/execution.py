"""Shared action execution and private event bookkeeping for protocol v1."""

from collections import defaultdict
from dataclasses import dataclass
from fractions import Fraction
from math import ceil

import numpy as np

from covasim import Intervention

from .actions import encode_action, legal_action_mask
from .protocol import ControlProtocol
from .types import ActionResolution, ActionVector, PublicCost, PublicDailyRecord, PublicResources


@dataclass(frozen=True, slots=True)
class NotificationEvent:
    """An investigation's notification, kept private even before delivery."""

    index_case: int
    contact: int
    layer: str
    investigation_day: int
    delivery_day: int
    quarantine_end_day: int


@dataclass(frozen=True, slots=True)
class InvestigationEvent:
    day: int
    index_case: int
    notifications: tuple[NotificationEvent, ...]


@dataclass(frozen=True, slots=True)
class DayExecutionAudit:
    """Executor-private allocation evidence; never an observation payload."""

    day: int
    clinical_requested: int
    clinical_executed: int
    clinical_unmet: int
    screening_requested: int
    screening_executed: int
    screening_unmet: int
    tracing_requested: int
    tracing_executed: int
    tracing_unmet: int
    clinical_indices: tuple[int, ...]
    screening_indices: tuple[int, ...]
    tracing_indices: tuple[int, ...]
    delivered_notification_indices: tuple[int, ...]
    cancelled_notification_events: int


def _proportional_quotas(total: int, weights: tuple[int, ...]) -> list[int]:
    """Largest remainders, with registered group order resolving equal shares."""
    denominator = sum(weights)
    if denominator == 0:
        return [0] * len(weights)
    quotients = [divmod(total * weight, denominator) for weight in weights]
    result = [q for q, _ in quotients]
    order = sorted(range(len(weights)), key=lambda i: (-quotients[i][1], i))
    for index in order[:total - sum(result)]:
        result[index] += 1
    return result


class JointActionExecutor(Intervention):
    """Execute selected effective levels without resolving or rewriting them.

    Random draws use the simulator's already seeded world stream. Population
    rosters, request counts, investigations and future events remain private.
    A public analyzer calls finish_day after the existing simulator day step.
    """

    def __init__(self, protocol: ControlProtocol, resources: PublicResources):
        if type(protocol) is not ControlProtocol or type(resources) is not PublicResources:
            raise TypeError("executor requires ControlProtocol and PublicResources")
        super().__init__(do_plot=False)
        self.protocol = protocol
        self._initial_resources = resources
        self.resources = resources
        self.registry = None
        self.current_action = ActionVector(tuple(protocol.definition["actions"]["initial"]))
        self.action_duration_days = (0,) * 5
        self.day_audits: list[DayExecutionAudit] = []
        self.investigations: list[InvestigationEvent] = []
        self._sim = None
        self._base_beta = None

    def __deepcopy__(self, memo):
        """Keep the frozen protocol shareable when Covasim copies interventions.

        ``ControlProtocol.definition`` contains mapping proxies, which are
        intentionally immutable but are not pickleable. Covasim deep-copies
        interventions during ``Sim.initialize``; a fresh executor is therefore
        required while the immutable protocol/resources are shared.
        """
        clone = type(self)(self.protocol, self._initial_resources)
        memo[id(self)] = clone
        return clone

    def initialize(self, sim):
        from .scenarios import build_population_registry

        # Re-initialization must not capture a previously restricted coefficient.
        if self._sim is sim and self._base_beta is not None:
            sim["beta_layer"].update(self._base_beta)
        super().initialize(sim)
        self._sim = sim
        self.registry = build_population_registry(sim.people, activity_config=self.protocol.definition["activity"])
        self.resources = self._initial_resources
        self.current_action = ActionVector(tuple(self.protocol.definition["actions"]["initial"]))
        self.action_duration_days = (0,) * 5
        self._base_beta = dict(sim["beta_layer"])
        self._pending_notifications: dict[int, list[NotificationEvent]] = defaultdict(list)
        self._last_test_day = np.nan_to_num(sim.people.date_tested, nan=-np.inf).copy()
        self._last_screen_day = np.full(len(sim.people), -np.inf)
        self.day_audits = []
        self.investigations = []
        self._records: dict[int, PublicDailyRecord] = {}
        self._diagnoses = ()
        self.start_day = int(sim.t)
        self._applied_day = self._completed_day = self.start_day - 1
        self._ensure_screening_legal(self.current_action)

    def _decision_boundary(self):
        if not self.initialized:
            raise RuntimeError("initialize executor before selecting resources or actions")
        day = int(self._sim.t)
        if (day - self.start_day) % self.protocol.decision_interval_days or self._applied_day == day:
            raise ValueError("resources and actions can change only before a decision-day step")

    def _ensure_screening_legal(self, action):
        mask = legal_action_mask(self.resources, self.registry.public_population.population,
                                 self.protocol.definition["actions"])
        if not mask[encode_action(action)]:
            raise ValueError("executed screening level exceeds public capacity; resolve it first")

    def set_resources(self, resources: PublicResources):
        if type(resources) is not PublicResources:
            raise TypeError("resources must be PublicResources")
        self._decision_boundary()
        # A capacity drop may temporarily invalidate the old action. The runner
        # must supply its new resolution before the next apply call.
        self.resources = resources

    def set_action(self, resolution: ActionResolution):
        if type(resolution) is not ActionResolution:
            raise TypeError("resolution must be ActionResolution")
        self._decision_boundary()
        self._ensure_screening_legal(resolution.executed_action)
        self.action_duration_days = tuple(
            duration if old == new else 0
            for old, new, duration in zip(self.current_action.values,
                                          resolution.executed_action.values,
                                          self.action_duration_days))
        self.current_action = resolution.executed_action

    @staticmethod
    def _clear_invalid_isolation(people):
        invalid = people.isolated & (people.dead | people.recovered)
        people.isolated[invalid] = False
        people.date_end_isolation[invalid] = people.t
        people.quarantined[people.dead] = False

    def _clinical_requests(self, people, day, parameters):
        eligible = ~(people.dead | people.diagnosed | (people.date_diagnosed == day))
        entry = (people.date_quarantined == day - 1) & people.quarantined
        masks = (
            eligible & people.symptomatic & entry,
            eligible & people.symptomatic & ~entry,
            eligible & ~people.symptomatic & entry,
        )
        probabilities = (
            parameters["symptomatic_quarantine_entry_probability"],
            parameters["symptomatic_daily_probability"],
            parameters["asymptomatic_quarantine_entry_probability"],
        )
        requested = []
        executed = []
        remaining = self.resources.clinical_daily_capacity
        for mask, probability in zip(masks, probabilities):
            candidates = np.flatnonzero(mask)
            selected = candidates[np.random.random(len(candidates)) < probability]
            requested.extend(int(i) for i in selected)
            selected = np.random.permutation(selected)
            allocated = selected[:remaining]
            executed.extend(int(i) for i in allocated)
            remaining -= len(allocated)
        return requested, executed

    def _screening_requests(self, people, day, clinical, ratio):
        requested = ceil(Fraction(str(ratio)) * self.registry.public_population.population)
        eligible = ~(people.dead | people.diagnosed | (people.date_diagnosed == day))
        exclusion_days = self.protocol.definition["resources"]["recent_screening_exclusion_days"]
        # Merge the executor's immutable path ledger with the engine's latest
        # actual test date so an upstream clinical intervention cannot silently
        # create a second same-day or recent test.
        engine_test_day = np.nan_to_num(people.date_tested, nan=-np.inf)
        last_test_day = np.maximum(self._last_test_day, engine_test_day)
        eligible &= last_test_day < day - exclusion_days
        eligible[np.asarray(clinical, dtype=int)] = False
        groups = self.registry.screening_groups
        quotas = _proportional_quotas(requested, tuple(len(group) for group in groups))
        candidates = []
        for group in groups:
            indices = np.asarray(group, dtype=int)
            indices = np.random.permutation(indices[eligible[indices]])
            # Stable sorting retains world-random order only among equal dates.
            indices = indices[np.argsort(self._last_screen_day[indices], kind="stable")]
            candidates.append(indices)
        allocations = [min(quota, len(group)) for quota, group in zip(quotas, candidates)]
        remaining = requested - sum(allocations)
        while remaining:
            available = tuple(len(group) - allocated for group, allocated in zip(candidates, allocations))
            if not sum(available):
                break
            extra = _proportional_quotas(remaining, available)
            for index, amount in enumerate(extra):
                granted = min(amount, available[index])
                allocations[index] += granted
                remaining -= granted
        executed = [int(i) for group, allocated in zip(candidates, allocations)
                    for i in group[:allocated]]
        return requested, executed

    def _test(self, sim, indices, *, screening):
        if not indices:
            return
        test = self.protocol.definition["resources"]["tests"]
        sim.people.test(np.asarray(indices, dtype=int), test_sensitivity=test["sensitivity"],
                        loss_prob=test["loss_prob"], test_delay=test["report_delay_days"])
        self._last_test_day[indices] = sim.t
        if screening:
            self._last_screen_day[indices] = sim.t
        # People.test updates individual states, while interventions own the
        # simulator's actual test counter (the same contract as cv.test_prob).
        sim.results["new_tests"][sim.t] += len(indices)

    def _investigate(self, sim, cases, parameters):
        selected = np.random.permutation(cases)[:self.resources.tracing_daily_index_capacity]
        for index_case in selected:
            events = []
            for scope, layers in self.registry.layer_groups.items():
                probability = parameters["coverage_probability"][scope]
                delay = parameters["notification_delay_days"][scope]
                for layer_name in layers:
                    if probability == 0:
                        continue
                    contacts = sim.people.contacts[layer_name].find_contacts(
                        np.asarray([index_case], dtype=int))
                    contacts = contacts[np.random.random(len(contacts)) < probability]
                    for contact in contacts:
                        event = NotificationEvent(int(index_case), int(contact), layer_name,
                                                  int(sim.t), int(sim.t + delay),
                                                  int(sim.t + self.protocol.definition["engine"]["quar_period"]))
                        events.append(event)
                        self._pending_notifications[event.delivery_day].append(event)
            self.investigations.append(InvestigationEvent(int(sim.t), int(index_case), tuple(events)))
        return tuple(int(i) for i in selected)

    def _deliver_notifications(self, sim):
        people, day = sim.people, int(sim.t)
        events = self._pending_notifications.pop(day, [])
        endpoints = {}
        cancelled = 0
        for event in events:
            if people.dead[event.contact]:
                cancelled += 1
                continue
            endpoints[event.contact] = max(endpoints.get(event.contact, -1), event.quarantine_end_day)
        for contact, end_day in endpoints.items():
            people.known_contact[contact] = True
            people.date_known_contact[contact] = np.fmin(people.date_known_contact[contact], day)
            if (end_day <= day or people.isolated[contact] or people.date_diagnosed[contact] == day
                    or (people.diagnosed[contact] and not people.recovered[contact])):
                continue
            if people.quarantined[contact]:
                people.date_end_quarantine[contact] = max(people.date_end_quarantine[contact], end_day)
            elif people.recovered[contact]:
                # The native checker excludes recovered people. The protocol
                # permits their operational quarantine after delivered notice.
                people.quarantined[contact] = True
                people.date_quarantined[contact] = day
                people.date_end_quarantine[contact] = end_day
                people.flows["new_quarantined"] += 1
            else:
                people.schedule_quarantine(np.asarray([contact], dtype=int),
                                            start_date=day, period=end_day - day)
        return tuple(sorted(endpoints)), cancelled

    def _apply_activity(self, sim):
        actions = self.protocol.definition["actions"]
        e, a = self.current_action.values[3:]
        for scope, level in (("school", actions["E"][e]), ("work", actions["A"][a]),
                             ("community", actions["A"][a])):
            multiplier = level["effective_parameters"]["transmission_multiplier"]
            for layer in self.registry.layer_groups[scope]:
                sim["beta_layer"][layer] = self._base_beta[layer] * multiplier

    def apply(self, sim):
        if not self.initialized or sim is not self._sim:
            raise RuntimeError("executor must be initialized for this simulator")
        day = int(sim.t)
        if day != self._applied_day + 1 or self._completed_day != self._applied_day:
            raise RuntimeError("each executor day must be applied and finished exactly once in order")
        self._ensure_screening_legal(self.current_action)
        self._clear_invalid_isolation(sim.people)
        self._diagnoses = tuple(int(i) for i in np.flatnonzero(sim.people.date_diagnosed == day))
        actions = self.protocol.definition["actions"]
        t, s, c, _, _ = self.current_action.values
        requested, clinical = self._clinical_requests(sim.people, day, actions["T"][t]["effective_parameters"])
        self._test(sim, clinical, screening=False)
        screening_requested, screening = self._screening_requests(
            sim.people, day, clinical, actions["S"][s]["effective_parameters"]["request_ratio"])
        self._test(sim, screening, screening=True)
        traced = self._investigate(sim, np.asarray(self._diagnoses, dtype=int),
                                   actions["C"][c]["effective_parameters"])
        delivered, cancelled = self._deliver_notifications(sim)
        self._apply_activity(sim)
        self.day_audits.append(DayExecutionAudit(
            day, len(requested), len(clinical), len(requested) - len(clinical),
            screening_requested, len(screening), screening_requested - len(screening),
            len(self._diagnoses), len(traced), len(self._diagnoses) - len(traced),
            tuple(clinical), tuple(screening), traced, delivered, cancelled))
        self._applied_day = day

    def finish_day(self, sim) -> PublicDailyRecord:
        """Freeze delivered public counts after the native day state updates."""
        day = int(sim.t)
        if sim is not self._sim or self._applied_day != day:
            raise RuntimeError("apply executor before finishing its day")
        if day in self._records:
            return self._records[day]
        self._clear_invalid_isolation(sim.people)
        isolated = sim.people.isolated & ~sim.people.dead
        quarantined = sim.people.quarantined & ~sim.people.dead
        n_isolated, n_quarantined, n_union = (int(np.count_nonzero(values))
                                             for values in (isolated, quarantined, isolated | quarantined))
        # Covasim has already copied stocks/flows before analyzers run. Keep
        # those engine diagnostics aligned with the adapter's post-cleanup
        # public disposition without changing the disease core.
        for key, value in (("n_isolated", n_isolated), ("n_quarantined", n_quarantined)):
            if key in sim.results:
                sim.results[key][day] = value
        actions = self.protocol.definition["actions"]
        e, a = self.current_action.values[3:]
        school_fraction = actions["E"][e]["effective_parameters"]["restriction_time_fraction"]
        activity_fraction = actions["A"][a]["effective_parameters"]["restriction_time_fraction"]
        audit = self.day_audits[-1]
        cost = PublicCost(
            clinical_tests=audit.clinical_executed, screening_tests=audit.screening_executed,
            delivered_notifications=len(audit.delivered_notification_indices),
            isolation_person_days=n_isolated, quarantine_person_days=n_quarantined,
            union_person_days=n_union,
            school_restriction_person_days=float(self.registry.school_weights.sum()) * school_fraction,
            work_restriction_person_days=float(self.registry.work_weights.sum()) * activity_fraction,
            community_restriction_person_days=float(self.registry.community_weights.sum()) * activity_fraction)
        record = PublicDailyRecord(day - self.start_day, len(self._diagnoses), cost, self.current_action,
                                   self.resources, n_isolated, n_quarantined, n_union)
        self._records[day] = record
        self._completed_day = day
        self.action_duration_days = tuple(value + 1 for value in self.action_duration_days)
        return record
