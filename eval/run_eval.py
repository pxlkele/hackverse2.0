"""
Eligibility evaluation harness.

    .venv/bin/python eval/run_eval.py
    .venv/bin/python eval/run_eval.py --fairness
    .venv/bin/python eval/run_eval.py --json

Measures the engine against eval/personas.yaml. No LLM involved, so this runs
in milliseconds and can be run on every change.

The numbers this prints are the ones that go on a slide. Report them as they
come out. A modest honest figure survives a judge's follow-up question; an
inflated one does not.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.api.core import eligibility as el  # noqa: E402
from services.api.core import pathfinder as pf  # noqa: E402
from services.api.core.schemas import EligibilityStatus, Profile  # noqa: E402

PERSONAS = Path(__file__).resolve().parent / "personas.yaml"


def load_personas() -> list[dict]:
    with open(PERSONAS) as fh:
        return yaml.safe_load(fh)["personas"]


def classify(decision) -> str:
    """Collapse a decision into one of the four buckets personas assert on."""
    if decision.status is EligibilityStatus.ELIGIBLE:
        return "eligible"
    if decision.status is EligibilityStatus.NEED_INFO:
        return "need_info"
    return "ladder" if decision.ladder else "blocked"


def evaluate_persona(persona: dict) -> dict:
    profile = Profile(**persona["profile"])

    start = time.perf_counter()
    decisions = pf.build_all(profile, el.evaluate_all(profile))
    elapsed_ms = (time.perf_counter() - start) * 1000

    actual = {d.scheme_id: classify(d) for d in decisions}

    expected: dict[str, str] = {}
    for bucket, scheme_ids in persona.get("expect", {}).items():
        for scheme_id in scheme_ids:
            expected[scheme_id] = bucket

    mismatches = [
        {"scheme": s, "expected": expected[s], "actual": actual.get(s, "MISSING")}
        for s in expected
        if actual.get(s) != expected[s]
    ]

    # Ladders must actually work — a path that doesn't reach eligibility is
    # worse than no path, because a real person spends real days on it.
    bad_ladders = [
        d.scheme_id
        for d in decisions
        if d.ladder and not pf.verify_ladder(profile, d)
    ]

    return {
        "id": persona["id"],
        "slice": persona.get("slice", {}),
        "expected": expected,
        "actual": actual,
        "mismatches": mismatches,
        "bad_ladders": bad_ladders,
        "passed": not mismatches and not bad_ladders,
        "latency_ms": elapsed_ms,
    }


def score(results: list[dict]) -> dict:
    """
    Per-scheme precision and recall on the ELIGIBLE call.

    Precision matters more than recall here: telling someone they qualify when
    they don't sends them to a bank to be turned away. Recall failures are
    caught by the ladder, which still gives them a route.
    """
    stats: dict[str, dict[str, int]] = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})

    for result in results:
        schemes = set(result["expected"]) | set(result["actual"])
        for scheme in schemes:
            want = result["expected"].get(scheme) == "eligible"
            got = result["actual"].get(scheme) == "eligible"
            if want and got:
                stats[scheme]["tp"] += 1
            elif got and not want:
                stats[scheme]["fp"] += 1
            elif want and not got:
                stats[scheme]["fn"] += 1

    out = {}
    for scheme, s in stats.items():
        precision = s["tp"] / (s["tp"] + s["fp"]) if (s["tp"] + s["fp"]) else 1.0
        recall = s["tp"] / (s["tp"] + s["fn"]) if (s["tp"] + s["fn"]) else 1.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        out[scheme] = {"precision": precision, "recall": recall, "f1": f1, **s}
    return out


def fairness(results: list[dict]) -> dict:
    """
    Outcome rates sliced by demographic attributes the engine never sees.

    Any gap here is a bug, not a finding: gender and state are not inputs to a
    single rule, so identical facts must produce identical decisions.
    """
    buckets: dict[str, dict[str, list[bool]]] = defaultdict(lambda: defaultdict(list))

    for result in results:
        matched = any(v in ("eligible", "ladder") for v in result["actual"].values())
        for attribute, value in result["slice"].items():
            buckets[attribute][str(value)].append(matched)

    return {
        attribute: {
            value: {"n": len(flags), "match_rate": round(sum(flags) / len(flags), 3)}
            for value, flags in values.items()
        }
        for attribute, values in buckets.items()
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fairness", action="store_true", help="show demographic slices")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--verbose", action="store_true", help="list every persona")
    args = parser.parse_args()

    personas = load_personas()
    results = [evaluate_persona(p) for p in personas]

    passed = sum(r["passed"] for r in results)
    total = len(results)
    scores = score(results)
    latencies = sorted(r["latency_ms"] for r in results)

    macro_p = sum(s["precision"] for s in scores.values()) / len(scores)
    macro_r = sum(s["recall"] for s in scores.values()) / len(scores)

    if args.json:
        print(json.dumps(
            {"passed": passed, "total": total, "scores": scores,
             "fairness": fairness(results), "results": results},
            indent=2, default=str,
        ))
        return 0 if passed == total else 1

    print()
    print("=" * 68)
    print(f"  SETU ELIGIBILITY EVAL — {total} personas, schemes v{el.schemes_version()}")
    print("=" * 68)
    print(f"\n  Personas passed:  {passed}/{total}  ({passed/total*100:.0f}%)")

    print("\n  Per scheme (on the ELIGIBLE call):")
    print(f"    {'scheme':<18} {'precision':>10} {'recall':>8} {'F1':>7}")
    for scheme, s in sorted(scores.items()):
        print(f"    {scheme:<18} {s['precision']:>10.2f} {s['recall']:>8.2f} {s['f1']:>7.2f}")
    print(f"    {'MACRO AVG':<18} {macro_p:>10.2f} {macro_r:>8.2f}")

    print(f"\n  Latency: median {latencies[len(latencies)//2]:.1f}ms  "
          f"p95 {latencies[int(len(latencies)*0.95)]:.1f}ms  (no LLM in this path)")

    failures = [r for r in results if not r["passed"]]
    if failures:
        print(f"\n  {len(failures)} FAILING PERSONA(S):")
        for r in failures:
            print(f"\n    ✗ {r['id']}")
            for m in r["mismatches"]:
                print(f"        {m['scheme']}: expected {m['expected']}, got {m['actual']}")
            for scheme in r["bad_ladders"]:
                print(f"        {scheme}: LADDER DOES NOT LEAD TO ELIGIBILITY")
    else:
        print("\n  All personas passed.")

    if args.verbose:
        print("\n  Every persona:")
        for r in results:
            mark = "✓" if r["passed"] else "✗"
            print(f"    {mark} {r['id']:<32} {r['actual']}")

    if args.fairness:
        print("\n" + "=" * 68)
        print("  FAIRNESS AUDIT")
        print("=" * 68)
        print("\n  Match rate by slice. Gender and state are not inputs to any")
        print("  rule, so any gap below is a bug rather than a finding.\n")
        for attribute, values in fairness(results).items():
            print(f"    {attribute}:")
            for value, s in sorted(values.items()):
                print(f"      {value:<18} n={s['n']:<3} match rate {s['match_rate']:.2f}")
            rates = [s["match_rate"] for s in values.values()]
            spread = max(rates) - min(rates)
            print(f"      {'spread':<18} {spread:.2f}"
                  + ("  <- investigate" if spread > 0.15 else "  (explained by persona mix)"))
            print()

    print()
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
