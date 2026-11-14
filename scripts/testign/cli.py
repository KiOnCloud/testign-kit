"""Command line entry for the testign skills. Every subcommand prints JSON on stdout."""

from __future__ import annotations

import argparse
import json
import sys

from . import __version__, config


def _cmd_config(_args: argparse.Namespace) -> int:
    print(json.dumps(config.load(), ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="testign")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)
    cfg = sub.add_parser("config", help="print the effective tester config, creating it on first run")
    cfg.set_defaults(func=_cmd_config)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except config.ConfigError as exc:
        print(f"testign: {exc}", file=sys.stderr)
        return 2
