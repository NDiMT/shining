"""Command line entry point.

    python -m hollowasset budgets
    python -m hollowasset prompt Tools/catalog/greenvale_props.json
    python -m hollowasset generate Tools/catalog/greenvale_props.json --dry-run
    python -m hollowasset generate Tools/catalog/greenvale_props.json --id prop_barrel_a
    python -m hollowasset validate Content/Models/Props/prop_barrel_a.glb --class prop
    python -m hollowasset validate --catalog Tools/catalog/greenvale_props.json
    python -m hollowasset provenance --report --out docs/ASSET_PROVENANCE.md

Run from the repository root, or set PYTHONPATH=Tools.
"""

from __future__ import annotations

import argparse
import os
import sys

from . import budgets, content, meshy, pipeline, provenance, style, validate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="hollowasset",
        description="Hollow Crown asset generation, validation and provenance.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("budgets", help="print the polygon and texture budget table")
    subparsers.add_parser("balance", help="print the remaining Meshy credit balance")

    prompt_parser = subparsers.add_parser(
        "prompt", help="resolve catalog entries to prompts without spending credits"
    )
    prompt_parser.add_argument("catalog")
    prompt_parser.add_argument("--id", help="only this asset id")

    generate_parser = subparsers.add_parser("generate", help="generate assets from a catalog")
    generate_parser.add_argument("catalog")
    generate_parser.add_argument("--id", help="only this asset id")
    generate_parser.add_argument(
        "--dry-run", action="store_true", help="plan and cost the batch, spend nothing"
    )
    generate_parser.add_argument(
        "--stop-on-error", action="store_true", help="halt the batch on the first failure"
    )
    generate_parser.add_argument("--poll-seconds", type=float, default=10.0)
    generate_parser.add_argument("--provenance", default=provenance.DEFAULT_PATH)

    validate_parser = subparsers.add_parser("validate", help="validate GLB files against budgets")
    validate_parser.add_argument("paths", nargs="*", help="GLB files to check")
    validate_parser.add_argument("--class", dest="asset_class", help="asset class for bare paths")
    validate_parser.add_argument("--catalog", help="validate every asset in this catalog")
    validate_parser.add_argument("--verbose", action="store_true", help="show INFO findings too")

    content_parser = subparsers.add_parser(
        "validate-content", help="validate game data: characters, battles, dialogue, flags"
    )
    content_parser.add_argument("--data", default="Content/Data")
    content_parser.add_argument("--catalogs", default="Tools/catalog")
    content_parser.add_argument("--verbose", action="store_true", help="show INFO findings too")

    provenance_parser = subparsers.add_parser("provenance", help="inspect the asset database")
    provenance_parser.add_argument("--report", action="store_true", help="render markdown")
    provenance_parser.add_argument("--out", help="write the report here instead of stdout")
    provenance_parser.add_argument("--history", help="show every generation of one asset id")
    provenance_parser.add_argument("--path", default=provenance.DEFAULT_PATH)

    args = parser.parse_args(argv)

    try:
        return _dispatch(args)
    except (meshy.MeshyError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _dispatch(args: argparse.Namespace) -> int:
    if args.command == "budgets":
        print(budgets.table())
        return 0

    if args.command == "balance":
        print(f"{meshy.Client().balance()} credits")
        return 0

    if args.command == "prompt":
        return _cmd_prompt(args)

    if args.command == "generate":
        return _cmd_generate(args)

    if args.command == "validate":
        return _cmd_validate(args)

    if args.command == "validate-content":
        return _cmd_validate_content(args)

    if args.command == "provenance":
        return _cmd_provenance(args)

    raise ValueError(f"unhandled command {args.command}")


def _select(jobs: list[pipeline.Job], asset_id: str | None) -> list[pipeline.Job]:
    if not asset_id:
        return jobs
    chosen = [job for job in jobs if job.asset_id == asset_id]
    if not chosen:
        known = ", ".join(job.asset_id for job in jobs)
        raise ValueError(f"no asset {asset_id!r} in catalog; available: {known}")
    return chosen


def _cmd_prompt(args: argparse.Namespace) -> int:
    jobs = _select(pipeline.load_catalog(args.catalog), args.id)
    for job in jobs:
        print(f"=== {job.asset_id}  [{job.asset_class}] -> {job.output_path}")
        print(f"    budget: {job.budget.tri_soft[0]:,}-{job.budget.tri_soft[1]:,} tris, "
              f"target {job.budget.tri_target:,}, texture <= {job.budget.texture_max}px")
        print(f"    region: {job.region}   rig: {job.rig}   animations: {job.animations or '-'}")
        print(f"    estimated credits: {job.estimate_credits()}")
        print(f"    geometry ({len(job.prompt.geometry)} chars):\n      {job.prompt.geometry}")
        print(f"    texture  ({len(job.prompt.texture)} chars):\n      {job.prompt.texture}")
        if job.prompt.dropped:
            print(f"    dropped to fit the {style.PROMPT_LIMIT}-char limit: "
                  f"{', '.join(job.prompt.dropped)}")
            print("      shorten 'subject' or 'extra' in the catalog if these matter")
        print()
    print(f"{len(jobs)} job(s), {sum(j.estimate_credits() for j in jobs)} estimated credits")
    return 0


def _cmd_generate(args: argparse.Namespace) -> int:
    jobs = _select(pipeline.load_catalog(args.catalog), args.id)

    if args.dry_run:
        for job in jobs:
            print(f"would generate {job.asset_id:24} -> {job.output_path}"
                  f"  ({job.estimate_credits()} credits)")
        print(f"{len(jobs)} job(s), {sum(j.estimate_credits() for j in jobs)} estimated credits")
        print("dry run: nothing generated, no credits spent")
        return 0

    client = meshy.Client()
    results = pipeline.run_batch(
        jobs,
        client,
        log=print,
        provenance_path=args.provenance,
        poll_seconds=args.poll_seconds,
        stop_on_error=args.stop_on_error,
    )

    print()
    passed = sum(1 for r in results if r.ok)
    for result in results:
        state = "ok  " if result.ok else "FAIL"
        detail = result.error or (result.report.summary() if result.report else "")
        print(f"{state} {result.job.asset_id:24} {detail}")
    print(f"\n{passed}/{len(results)} passed, {client.credits_spent} credits spent, "
          f"{client.balance()} remaining")
    return 0 if passed == len(results) else 1


def _cmd_validate(args: argparse.Namespace) -> int:
    targets: list[tuple[str, str, bool]] = []

    if args.catalog:
        for job in pipeline.load_catalog(args.catalog):
            if os.path.exists(job.output_path):
                targets.append((job.output_path, job.asset_class, bool(job.animations)))
            else:
                print(f"skip {job.output_path}: not generated yet")
    for path in args.paths:
        if not args.asset_class:
            raise ValueError("--class is required when validating bare paths")
        targets.append((path, args.asset_class, False))

    if not targets:
        raise ValueError("nothing to validate; pass paths with --class, or --catalog")

    failures = 0
    for path, asset_class, expect_animations in targets:
        report = validate.validate(path, asset_class, expect_animations=expect_animations)
        print(report.summary())
        for finding in report.findings:
            if args.verbose or finding.severity >= validate.Severity.WARN:
                print(f"  {finding}")
        if not report.ok:
            failures += 1
    print(f"\n{len(targets) - failures}/{len(targets)} passed")
    return 1 if failures else 0


def _cmd_validate_content(args: argparse.Namespace) -> int:
    data = content.load(args.data, args.catalogs)
    report = content.validate(data)
    print(report.summary())
    for finding in report.findings:
        if args.verbose or finding.severity >= validate.Severity.WARN:
            print(f"  {finding}")
    return 0 if report.ok else 1


def _cmd_provenance(args: argparse.Namespace) -> int:
    if args.history:
        records = provenance.history(args.history, args.path)
        if not records:
            print(f"no records for {args.history!r}")
            return 1
        for index, record in enumerate(records, start=1):
            print(f"{index}. {record.generation_date}  {record.validation}  "
                  f"tris={record.triangles:,}  tasks={','.join(record.task_ids)}")
        return 0

    text = provenance.report(args.path)
    if args.out and args.report:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(text)
        print(f"wrote {args.out}")
        return 0
    if args.report:
        print(text, end="")
        return 0

    records = provenance.load(args.path)
    print(f"{len(records)} asset(s), {sum(r.consumed_credits for r in records):,} credits")
    for record in sorted(records, key=lambda r: r.asset_id):
        print(f"  {record.asset_id:24} {record.asset_type:16} {record.triangles:>7,} tris  "
              f"{record.validation}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
