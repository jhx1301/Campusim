"""Frozen, reviewed knowledge for the public synthetic control task.

Review status records source inspection during the research pass. It is neither
human approval nor evidence that a guideline improves this simulator's policy.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .llm import LLMConfigurationError
from .logging import snapshot_sha256
from .memory_types import KnowledgeCard, knowledge_card_from_dict, public_to_dict, strict_json_loads


CORE_IDS = tuple(f"SIM-{index:02d}" for index in range(1, 7))
EXTERNAL_IDS = ("PH-01", "PH-02", "PH-03")
BUNDLE_VERSION = "cemas-knowledge-bundle-v1"
DEFAULT_KNOWLEDGE_PATH = Path(__file__).with_name("knowledge") / "public_knowledge_v1.json"
_CARD_FIELDS = {"id", "version", "kind", "source", "statement", "preconditions", "limitations",
                "public_fields", "action_dimensions", "trigger", "priority", "conflict_group",
                "supersedes", "review_status"}
_SOURCE_FIELDS = {"publisher", "title", "url", "issued_on", "revision", "retrieved_on", "section", "evidence_type"}
_PUBLIC_FIELDS = {"history", "week_valid", "feedback.week", "resources", "history.cost",
                  "history.diagnosis_test_proxy", "history.proxy_valid", "current_action",
                  "action_duration_days", "legal_action_mask"}
_TRIGGERS = {"always", "has_history", "testing_changed", "capacity_changed"}


def _invalid(description):
    raise LLMConfigurationError("invalid_knowledge_bundle", description)


def _text(value):
    return type(value) is str and bool(value.strip())


def _text_list(value, *, allowed=None, empty=False):
    return (type(value) in (list, tuple) and (empty or bool(value))
            and all(_text(item) for item in value) and len(set(value)) == len(value)
            and (allowed is None or set(value).issubset(allowed)))


def observation_flags(observation):
    """Deterministic O-only flags, independent of memory mode and retrieval."""
    from .memory import recent_summary

    return recent_summary(observation).flags


def _checked_card(value):
    if not isinstance(value, Mapping) or set(value) != _CARD_FIELDS:
        _invalid("Knowledge cards require the exact public card schema")
    if value["id"] not in CORE_IDS + EXTERNAL_IDS or not _text(value["version"]):
        _invalid("Unknown knowledge card identity or version")
    if (value["kind"] not in ("simulation_rule", "real_guideline", "research_finding")
            or value["review_status"] != "reviewed" or value["trigger"] not in _TRIGGERS):
        _invalid("Only reviewed cards with O-only supported triggers may be loaded")
    if (value["id"] in CORE_IDS and (value["kind"] != "simulation_rule"
            or value["trigger"] != "always" or value["version"] != "1")):
        _invalid("Core knowledge must retain the fixed simulation-rule version and trigger")
    if (type(value["priority"]) is not int or value["priority"] < 0
            or not _text(value["statement"]) or value["conflict_group"] is not None and not _text(value["conflict_group"])):
        _invalid("Invalid statement, priority or conflict group")
    for name in ("preconditions", "limitations"):
        if not _text_list(value[name]):
            _invalid("Knowledge preconditions and limitations must be explicit")
    if (not _text_list(value["public_fields"], allowed=_PUBLIC_FIELDS)
            or not _text_list(value["action_dimensions"], allowed=set("TSCEA"))
            or not _text_list(value["supersedes"], allowed=set(CORE_IDS + EXTERNAL_IDS), empty=True)):
        _invalid("Unknown knowledge public field, action dimension or supersession")
    source = value["source"]
    if not isinstance(source, Mapping) or set(source) != _SOURCE_FIELDS or not all(_text(item) for item in source.values()):
        _invalid("Knowledge source provenance must use the exact source schema")
    try:
        issued, retrieved = date.fromisoformat(source["issued_on"]), date.fromisoformat(source["retrieved_on"])
    except ValueError:
        _invalid("Knowledge source dates must be ISO dates")
    if issued > retrieved:
        _invalid("Knowledge cannot be reviewed before its source issue date")
    if value["id"] in EXTERNAL_IDS and not source["url"].startswith("https://"):
        _invalid("External knowledge must retain its HTTPS primary source")
    if value["id"] in CORE_IDS and source["url"].startswith(("http:", "https:")):
        _invalid("Core simulation rules must cite a project contract")
    return knowledge_card_from_dict(value)


@dataclass(frozen=True, slots=True)
class KnowledgeBundle:
    schema_version: str
    bundle_id: str
    cards: tuple
    conflict_pairs: tuple = ()

    def __post_init__(self):
        if self.schema_version != BUNDLE_VERSION or not _text(self.bundle_id):
            _invalid("Unknown knowledge bundle version")
        cards = tuple(self.cards)
        if any(type(card) is not KnowledgeCard for card in cards):
            raise TypeError("KnowledgeBundle requires checked KnowledgeCard values")
        for card in cards:
            _checked_card(public_to_dict(card))
        ids = tuple(card.id for card in cards)
        if len(ids) != len(set(ids)) or set(ids) != set(CORE_IDS + EXTERNAL_IDS):
            _invalid("Knowledge bundle requires six unique core rules and the three researched warnings")
        if self.conflict_pairs:
            _invalid("Unresolved knowledge conflict pairs cannot be published")
        by_id = {card.id: card for card in cards}
        expected = {
            "PH-01": ("US CDC", "2021-01-29", "https://www.cdc.gov/mmwr/volumes/70/wr/mm7004a3.htm"),
            "PH-02": ("UK Health Security Agency", "2026-06-04", "https://www.gov.uk/government/publications/sources-of-surveillance-data-for-influenza-covid-19-and-other-respiratory-viruses/data-quality-report-national-flu-and-covid-19-surveillance-report"),
            "PH-03": ("World Health Organization", "2023.1", "https://www.who.int/publications/i/item/considerations-in-adjusting-public-health-and-social-measures-in-the-context-of-COVID-19-interim-guidance"),
        }
        for identity, (publisher, version, url) in expected.items():
            card = by_id[identity]
            if card.source["publisher"] != publisher or card.version != version or card.source["url"] != url:
                _invalid("External knowledge identity, source and version must retain their reviewed mapping")
        object.__setattr__(self, "cards", tuple(sorted(cards, key=lambda card: card.id)))
        object.__setattr__(self, "conflict_pairs", ())

    @property
    def sha256(self):
        return snapshot_sha256(self.as_dict())

    def as_dict(self):
        return {"schema_version": self.schema_version, "bundle_id": self.bundle_id,
                "cards": [public_to_dict(card) for card in self.cards], "conflict_pairs": []}

    def select(self, observation):
        flags = observation_flags(observation)
        has_history = "no_history" not in flags
        return tuple(card for card in self.cards if card.trigger == "always"
                     or card.trigger == "has_history" and has_history
                     or card.trigger in flags)


def load_knowledge_bundle(path=None):
    location = Path(path) if path is not None else DEFAULT_KNOWLEDGE_PATH
    try:
        value = strict_json_loads(location.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        _invalid("Cannot read the frozen knowledge resource")
    if type(value) is not dict or set(value) != {"schema_version", "bundle_id", "cards", "conflict_pairs"}:
        _invalid("Knowledge bundle must contain only the public bundle schema")
    if type(value["cards"]) is not list or type(value["conflict_pairs"]) is not list:
        _invalid("Knowledge cards and conflict pairs must be arrays")
    bundle = KnowledgeBundle(value["schema_version"], value["bundle_id"],
                             tuple(_checked_card(card) for card in value["cards"]), tuple(value["conflict_pairs"]))
    root = Path(__file__).resolve().parents[2]
    for card in bundle.cards:
        if card.id in CORE_IDS:
            referenced = (root / card.source["url"]).resolve()
            if not referenced.is_relative_to(root) or not referenced.is_file():
                _invalid("Core knowledge source path must resolve to a project contract")
    return bundle
