"""Train a persistent public library, freeze it, or evaluate a frozen snapshot."""

import argparse
import json
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=Path("docs/baseline_snapshot_training_v1.json"))
    commands = parser.add_subparsers(dest="command", required=True)
    freeze = commands.add_parser("freeze")
    freeze.add_argument("--library", type=Path, required=True)
    freeze.add_argument("--output", type=Path, required=True)
    for name in ("train", "evaluate"):
        command = commands.add_parser(name)
        command.add_argument("--library", type=Path, required=True)
        command.add_argument("--settings", type=Path, required=True, help="Model endpoint and tokenizer settings JSON")
        command.add_argument("--output", type=Path, required=True)
        command.add_argument("--artifact", type=Path, required=True)
        command.add_argument("--data", type=Path)
        if name == "train":
            command.add_argument("--episodes", type=Path, required=True)
        else:
            command.add_argument("--split", choices=("val", "test"), default="val")
            command.add_argument("--workers", type=int, default=1)
    args = parser.parse_args(argv)
    from cemas.control.learning_store import LearningMemoryStore
    if args.command == "freeze":
        store = LearningMemoryStore(args.library)
        try:
            store.freeze(args.output)
        finally:
            store.close()
        return 0
    from cemas.control.snapshot_protocol import load_training_protocol
    protocol = load_training_protocol(args.protocol)
    settings = {"memory_mode": "both", "feedback_backend": "llm", "rule_memory": "adaptive",
                **json.loads(args.settings.read_text(encoding="utf-8"))}
    if args.command == "train":
        from cemas.control.learning import train_memory
        train_memory(protocol, json.loads(args.episodes.read_text(encoding="utf-8")), args.library,
                     args.output, settings, args.artifact, calibration_data_path=args.data)
    else:
        from cemas.control.training import evaluate_source
        settings["learning_store_path"] = str(args.library)
        evaluate_source(protocol, {"method": "llm", "settings": settings}, args.output,
                        args.artifact, pool=args.split, calibration_data_path=args.data, workers=args.workers)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
