"""Command line interface, and the entry point the Colab notebook calls.

Two commands:

``check``
    Run every validation check against a config and print the result. Draws
    nothing. Useful for confirming names and coordinates before rendering.

``render``
    Validate, then draw the map and write the output files.

Both take the path to a YAML config in ``maps/``. ``render`` also accepts
``--force``, which lets warnings through but never missing data.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

import yaml

from . import data as data_module
from .names import load_aliases
from .render import render_map
from .style import load_brand
from .validate import ValidationReport, validate_request

__all__ = ["main", "run_from_config", "load_config"]


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def load_config(path: str | Path) -> dict:
    """Read a map config, with a clear message if it is malformed."""
    path = Path(path)
    if not path.exists():
        raise SystemExit(
            f"No config file at {path}.\n"
            f"Configs live in the maps folder. Copy maps/madurai.yaml and edit it."
        )
    with path.open(encoding="utf-8") as handle:
        config = yaml.safe_load(handle)

    if not isinstance(config, dict):
        raise SystemExit(f"{path} is not a valid map config. Compare it with maps/madurai.yaml.")

    for required in ("state", "district"):
        if not config.get(required):
            raise SystemExit(f"{path} is missing the {required!r} setting.")

    config.setdefault("blocks", [])
    config.setdefault("sites", [])
    config.setdefault("output_name", path.stem)
    if config.get("blocks") is None:
        config["blocks"] = []
    if config.get("sites") is None:
        config["sites"] = []
    return config


def run_from_config(
    config: dict,
    *,
    force: bool = False,
    output_root: Path | None = None,
    log=print,
) -> dict:
    """Validate and render one map. Returns a dict describing what happened.

    This is the single entry point used by both the CLI and the Colab
    notebook, so the two cannot drift apart.
    """
    root = project_root()
    aliases = load_aliases(root / "data" / "aliases.csv")

    report = ValidationReport()
    report, target = validate_request(
        state=config["state"],
        district=config["district"],
        blocks=list(config.get("blocks") or []),
        sites=list(config.get("sites") or []),
        aliases=aliases,
        report=report,
    )

    outcome = {"report": report, "target": target, "files": [], "rendered": False}

    if target is None or report.blocks_render(force=force):
        return outcome

    brand = load_brand(root / "style" / "brand.yaml")
    output_root = Path(output_root or (root / "output"))
    output_dir = output_root / config["output_name"]

    result = render_map(
        target=target,
        config=config,
        brand=brand,
        report=report,
        output_dir=output_dir,
    )

    log_path = output_dir / "render_log.txt"
    log_path.write_text(
        _render_log(config=config, report=report, target=target, result=result),
        encoding="utf-8",
    )

    outcome["files"] = result.files + [log_path]
    outcome["rendered"] = True
    outcome["output_dir"] = output_dir
    return outcome


def _render_log(*, config, report, target, result) -> str:
    lines = [
        "Locator map render log",
        "=" * 60,
        f"Generated: {datetime.now().isoformat(timespec='seconds')}",
        "",
        "Inputs",
        "-" * 60,
        f"State:    {config['state']}  ->  {target.state_name}",
        f"District: {config['district']}  ->  {target.district_name} (LGD {target.district_lgd})",
        f"Blocks:   {', '.join(config.get('blocks') or []) or '(none)'}",
    ]
    for site in target.sites:
        lines.append(
            f"Site:     {site.get('name')} at ({site.get('lat')}, {site.get('lon')}) "
            f"- falls in {site.get('actual_block') or 'no block'}"
        )

    lines += [
        "",
        "Validation",
        "-" * 60,
        report.render_text(),
        "",
        f"Result: {report.summary()}",
        "",
        "Data",
        "-" * 60,
    ]
    lines += data_module.dataset_versions()
    lines += [
        f"Districts drawn: {len(target.districts)}",
        f"Blocks drawn:    {len(target.blocks)}",
        "",
        "Rendering",
        "-" * 60,
        f"Figure size: {result.figure_size[0]} x {result.figure_size[1]} inches",
    ]
    lines += result.notes
    lines += ["", "Files", "-" * 60]
    lines += [f.name for f in result.files]
    return "\n".join(lines) + "\n"


def _print_report(report) -> None:
    if not report.issues:
        print("All checks passed.")
        return
    print(report.render_text())
    print()
    print(f"Result: {report.summary()}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="locator",
        description="Make a three-panel locator map from a config file.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser("check", help="run the validation checks only")
    check.add_argument("config", help="path to a YAML config in the maps folder")

    render = subparsers.add_parser("render", help="validate, then draw the map")
    render.add_argument("config", help="path to a YAML config in the maps folder")
    render.add_argument(
        "--force",
        action="store_true",
        help="draw the map even if there are warnings (missing data still stops it)",
    )
    render.add_argument("--output-dir", default=None, help="where to write the output folder")

    fetch = subparsers.add_parser("fetch", help="download the boundary data ahead of time")
    fetch.parse_args  # no options

    args = parser.parse_args(argv)

    if args.command == "fetch":
        for key in data_module.DATASETS:
            data_module.ensure_dataset(key, log=print)
        print("All boundary data present.")
        return 0

    config = load_config(args.config)

    if args.command == "check":
        aliases = load_aliases(project_root() / "data" / "aliases.csv")
        report, _ = validate_request(
            state=config["state"],
            district=config["district"],
            blocks=list(config.get("blocks") or []),
            sites=list(config.get("sites") or []),
            aliases=aliases,
        )
        _print_report(report)
        return 1 if report.errors else 0

    outcome = run_from_config(config, force=args.force, output_root=args.output_dir)
    _print_report(outcome["report"])
    print()

    if not outcome["rendered"]:
        if outcome["report"].errors:
            print("Nothing was drawn. Fix the errors above and run again.")
        else:
            print(
                "Nothing was drawn because of the warnings above.\n"
                "If they are expected, run the same command again with --force."
            )
        return 1

    print(f"Map written to {outcome['output_dir']}")
    for path in outcome["files"]:
        print(f"  {path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
