"""Collect public source experience, build revisions, audit coverage, and freeze a store.

Scientific collection retains the E0 gate and source-only seed pool. --smoke
produces fixture data only, with three simple policies and no paid model calls.
"""
import argparse
import json
from pathlib import Path


class PublicTransitionRecorder:
    """Only these exact public values cross into the episode memory."""

    def __init__(self):
        from cemas.control.memory import PublicEpisodeMemory
        self.memory = PublicEpisodeMemory()
        self.revisions = []
        self.export = []

    def __call__(self, observation, feedback):
        from cemas.control.memory_types import public_to_dict
        self.memory.stage(observation)
        self.revisions.extend(self.memory.accept(feedback))
        self.export.append({"observation": public_to_dict(observation), "feedback": public_to_dict(feedback)})


def _json(path, value):
    from cemas.control.logging import resolved_snapshot
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(resolved_snapshot(value), ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def _controller(policy, controller_seed, protocol=None, threshold_artifact=None):
    from cemas.control.controllers import MinimumController, MaximumFeasibleController, UniformLegalController
    if policy == "tuned_threshold":
        from cemas.control.controllers import load_baseline_controller
        controller, _metadata = load_baseline_controller(protocol, threshold_artifact)
        if controller.controller_type != "threshold":
            raise ValueError("tuned_threshold collection requires a Threshold artifact")
        return controller
    return {"minimum": MinimumController, "maximum_feasible": MaximumFeasibleController,
            "uniform_legal_independent_rng": lambda: UniformLegalController(controller_seed)}[policy]()


def collect(args):
    from cemas.control.artifacts import file_sha256
    from cemas.control.protocol import load_protocol
    from cemas.control.protocol import source_grid
    from cemas.control.runner import make_public_prompt_config, memory_source_compatibility, run_episode
    from cemas.control.memory import public_task_hash
    from cemas.control.memory_store import PublicCaseBuilder, SOURCE_POLICIES, freeze_public_store, coverage_report
    protocol = load_protocol(args.protocol)
    pool = protocol.definition["seeds"]["memory_collection"]
    seeds = args.seed or ([90001] if args.smoke else list(range(pool["start_inclusive"], pool["end_inclusive"] + 1)))
    if len(set(seeds)) != len(seeds) or any(type(seed) is not int or (seed not in protocol.definition["seeds"]["smoke"] if args.smoke else not pool["start_inclusive"] <= seed <= pool["end_inclusive"]) for seed in seeds):
        raise ValueError("collection seeds must be unique members of the selected smoke/source pool")
    if not args.smoke and (args.artifact is None or any(value is not None for value in (args.population, args.days, args.initial_infections))):
        raise ValueError("scientific collection requires E0 evidence and the common population/horizon")
    policies = args.policy or list(SOURCE_POLICIES[:3] if args.smoke else SOURCE_POLICIES)
    if len(set(policies)) != len(policies):
        raise ValueError("collection policies must be unique")
    threshold_artifact = getattr(args, "threshold_artifact", None)
    if "tuned_threshold" in policies and threshold_artifact is None:
        raise ValueError("tuned_threshold collection requires --threshold-artifact from source tuning")
    threshold_hash = None
    if "tuned_threshold" in policies:
        threshold_hash = file_sha256(threshold_artifact)
        # Validate the selected artifact before starting any simulation or output.
        _controller("tuned_threshold", args.controller_seed, protocol, threshold_artifact)
    days = args.days or protocol.definition["engine"]["execution_days"]
    purpose = "fixture" if args.smoke else "development"
    compat = {} if args.smoke else memory_source_compatibility(protocol, args.artifact, data_path=args.data)
    task_hash = public_task_hash(make_public_prompt_config(protocol), days)
    args.output.mkdir(parents=True, exist_ok=False)
    staging = args.output / "staging"
    builder = PublicCaseBuilder(staging, task_hash, purpose=purpose, compatibility=compat)
    statuses = {}
    try:
        for seed in seeds:
            world = None if args.smoke else source_grid(protocol, "memory_collection", seed)
            for policy in policies:
                identity = f"{seed}-{policy}"
                run_dir = args.output / "runs" / identity
                options = {key: value for key, value in (("population", args.population), ("execution_days", args.days),
                           ("initial_infections", args.initial_infections)) if value is not None} if args.smoke else {
                           "calibration_artifact": args.artifact, "calibration_data_path": args.data,
                           "beta_scale": world["beta_scale"], "screening_capacity_ratio": world["screening_capacity_ratio"]}
                recorder = PublicTransitionRecorder()
                controller = _controller(policy, args.controller_seed, protocol, threshold_artifact)
                result = run_episode(protocol, controller, run_dir, seed,
                    purpose="smoke" if args.smoke else "memory_collection", scenario_options=options,
                    public_transition_sink=recorder)
                _json(run_dir / "public_transitions.json", {"synthetic_fixture": args.smoke, "transitions": recorder.export})
                registration = {"trajectory_id": identity, "purpose": purpose, "policy": policy,
                    "seed": seed, "source_kind": "source_simulation", "split": "source" if not args.smoke else "fixture",
                    "run_purpose": "smoke" if args.smoke else "memory_collection",
                    "world": world, "compatibility": compat,
                    "controller_seed": args.controller_seed if policy == "uniform_legal_independent_rng" else None}
                if not args.smoke:
                    registration.update(run_dir=str(run_dir.resolve()),
                        run_manifest_sha256=file_sha256(run_dir / "manifest.json"),
                        run_summary_sha256=file_sha256(run_dir / "summary.json"),
                        public_transitions_sha256=file_sha256(run_dir / "public_transitions.json"))
                if policy == "tuned_threshold":
                    registration["baseline_artifact_sha256"] = threshold_hash
                builder.append(tuple(recorder.revisions), registration)
                statuses[identity] = result.status
        report = builder.finalize(statuses)
    except BaseException as error:
        _json(args.output / "collection_failure.json", {"status": "failed", "error_type": type(error).__name__,
                                                        "completed_identities": list(statuses)})
        raise
    finally:
        builder.close()
    manifest = freeze_public_store(staging, report.private_manifest_path, args.output / "frozen")
    _json(args.output / "coverage.json", coverage_report(report.private_manifest_path))
    print(f"completed {len(statuses)} {purpose} trajectories; immutable library: {args.output / 'frozen'}")
    return manifest


def import_public(args):
    from cemas.control.memory_types import observation_from_dict, feedback_from_dict, strict_json_loads
    from cemas.control.memory_store import PublicCaseBuilder
    from cemas.control.memory import public_task_hash
    from cemas.control.protocol import load_protocol
    from cemas.control.runner import make_public_prompt_config
    payload = strict_json_loads(args.input.read_text(encoding="utf-8"))
    if type(payload) is not dict or set(payload) != {"synthetic_fixture", "transitions"} or payload["synthetic_fixture"] is not True:
        raise ValueError("manual import is fixture-only; source collection must use audited runner records")
    recorder = PublicTransitionRecorder()
    for item in payload["transitions"]:
        if type(item) is not dict or set(item) != {"observation", "feedback"}:
            raise ValueError("public transitions must contain only exact observation and feedback")
        recorder(observation_from_dict(item["observation"]), feedback_from_dict(item["feedback"]))
    if not recorder.revisions or recorder.memory.pending_observation is not None:
        raise ValueError("import requires completed public transitions")
    last = recorder.revisions[-1]
    if last.available_through_day != last.pre_observation.execution_days - 1:
        raise ValueError("fixture export did not complete its announced horizon")
    config = make_public_prompt_config(load_protocol(args.protocol))
    task_hash = public_task_hash(config, last.pre_observation.execution_days)
    with PublicCaseBuilder(args.output, task_hash) as builder:
        builder.append(tuple(recorder.revisions), {"trajectory_id": "manual-fixture", "purpose": "fixture"})
        builder.finalize("completed")
    print(f"fixture import complete: {args.output}")


def main(argv=None):
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="operation", required=True)
    c = subs.add_parser("collect", help="Collect four source policies, or three fixture smoke policies")
    c.add_argument("--protocol", type=Path, default=root / "docs/control_protocol_v1.json")
    c.add_argument("--output", type=Path, required=True)
    c.add_argument("--artifact", type=Path)
    c.add_argument("--threshold-artifact", type=Path)
    c.add_argument("--data", type=Path)
    c.add_argument("--seed", type=int, action="append")
    from cemas.control.memory_store import SOURCE_POLICIES
    c.add_argument("--policy", choices=SOURCE_POLICIES, action="append")
    c.add_argument("--controller-seed", type=int, default=0)
    c.add_argument("--smoke", action="store_true")
    c.add_argument("--population", type=int)
    c.add_argument("--days", type=int)
    c.add_argument("--initial-infections", type=int)
    i = subs.add_parser("import-fixture", help="Build only fixture staging from a complete synthetic public export")
    i.add_argument("--protocol", type=Path, default=root / "docs/control_protocol_v1.json")
    i.add_argument("--input", type=Path, required=True)
    i.add_argument("--output", type=Path, required=True)
    f = subs.add_parser("freeze")
    f.add_argument("--staging", type=Path, required=True)
    f.add_argument("--private-manifest", type=Path, required=True)
    f.add_argument("--output", type=Path, required=True)
    f.add_argument("--purpose", choices=("fixture", "development", "evaluation_ready"))
    promote = subs.add_parser("promote", help="Publish development data after complete Phase 6 release verification")
    promote.add_argument("--development", type=Path, required=True)
    promote.add_argument("--release", type=Path, required=True)
    promote.add_argument("--output", type=Path, required=True)
    audit = subs.add_parser("coverage")
    audit.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.operation == "collect":
        collect(args)
    elif args.operation == "import-fixture":
        import_public(args)
    elif args.operation == "freeze":
        from cemas.control.memory_store import freeze_public_store
        freeze_public_store(args.staging, args.private_manifest, args.output, args.purpose)
    elif args.operation == "promote":
        from cemas.control.memory_store import promote_public_store
        promote_public_store(args.development, args.release, args.output)
    else:
        from cemas.control.memory_store import coverage_report
        print(json.dumps(coverage_report(args.manifest), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
