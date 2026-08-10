"""
Render the fairness audit as PNG bar charts for the deck.

Reads the same persona set that eval/run_eval.py --fairness reads, computes
per-slice match rates, and writes deck-ready PNGs to eval/out/fairness/.
Nothing here fabricates numbers — if a slice returns 1.00 that is because
every persona in that slice matched its expected outcome.

    .venv/bin/python eval/fairness_charts.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "services" / "api"))

import matplotlib.pyplot as plt
import yaml

from services.api.core import eligibility, pathfinder  # noqa: E402
from services.api.core.schemas import EligibilityStatus, Profile  # noqa: E402


PERSONAS_PATH = Path(__file__).resolve().parent / "personas.yaml"
OUT_DIR = Path(__file__).resolve().parent / "out" / "fairness"


# ── Deck styling ─────────────────────────────────────────────────────────────
BG        = "#0b0d12"      # near-black, matches the console
FG        = "#e6ecf5"      # off-white text
GRID      = "#22283a"      # subtle grid
BAR_FILL  = "#00f5ff"      # cyan — matches Stage-1 accent in the console
BAR_EDGE  = "#00f5ff"
BAR_LABEL = "#0b0d12"      # dark text on cyan bars
CAPTION   = "#7a8290"


def load_personas() -> list[dict]:
    with open(PERSONAS_PATH) as fh:
        return yaml.safe_load(fh)["personas"]


def evaluate(persona: dict) -> bool:
    """
    Rerun the rule engine for one persona and check every ELIGIBLE it expects
    is actually returned. Same shape as run_eval.py, kept local so this script
    is standalone.
    """
    profile = Profile(**persona["profile"])
    decisions = pathfinder.build_all(profile, eligibility.evaluate_all(profile))
    got_eligible = {d.scheme_id for d in decisions if d.status is EligibilityStatus.ELIGIBLE}
    expected = set(persona.get("expect", {}).get("eligible", []))
    return expected.issubset(got_eligible)


def match_rates_by(slice_key: str, personas: list[dict]) -> dict[str, tuple[int, float]]:
    """Return {slice_value: (n, match_rate)} — same shape as run_eval.fairness."""
    buckets: dict[str, list[bool]] = {}
    for persona in personas:
        value = persona.get("slice", {}).get(slice_key)
        if value is None:
            continue
        buckets.setdefault(str(value), []).append(evaluate(persona))
    return {k: (len(v), sum(v) / len(v)) for k, v in buckets.items()}


def render_bar_chart(
    title: str,
    subtitle: str,
    data: dict[str, tuple[int, float]],
    out_path: Path,
    figsize: tuple[float, float] = (10, 5),
) -> None:
    """
    Horizontal bar chart, sorted longest-first. Each bar labelled with n=X and
    the match rate. Y-axis kept at 0..100% so bars at 1.00 fill the width and
    the fairness result reads as unmistakable.
    """
    items = sorted(data.items(), key=lambda kv: (-kv[1][1], -kv[1][0], kv[0]))
    labels = [k for k, _ in items]
    rates  = [v[1] * 100 for _, v in items]
    counts = [v[0] for _, v in items]

    fig, ax = plt.subplots(figsize=figsize, facecolor=BG)
    ax.set_facecolor(BG)

    y_positions = list(range(len(labels)))
    bars = ax.barh(y_positions, rates, color=BAR_FILL, edgecolor=BAR_EDGE, height=0.62)
    ax.set_yticks(y_positions)
    ax.set_yticklabels(labels, color=FG, fontsize=13)
    ax.invert_yaxis()

    ax.set_xlim(0, 100)
    ax.set_xticks([0, 25, 50, 75, 100])
    ax.set_xticklabels(["0%", "25%", "50%", "75%", "100%"], color=FG, fontsize=11)
    ax.tick_params(axis="both", colors=FG, length=0)

    ax.grid(axis="x", color=GRID, linewidth=0.7, alpha=0.6)
    ax.set_axisbelow(True)
    for spine in ax.spines.values():
        spine.set_visible(False)

    # In-bar labels: "n=X · 100%" centred if bar is wide enough, else outside.
    for bar, count, rate in zip(bars, counts, rates):
        label = f"n={count}   {rate:.1f}%"
        if rate >= 30:
            ax.text(rate - 1.5, bar.get_y() + bar.get_height() / 2, label,
                    ha="right", va="center", color=BAR_LABEL, fontsize=11, fontweight="bold")
        else:
            ax.text(rate + 1.5, bar.get_y() + bar.get_height() / 2, label,
                    ha="left", va="center", color=FG, fontsize=11, fontweight="bold")

    fig.suptitle(title, color=FG, fontsize=18, fontweight="bold", x=0.02, ha="left", y=0.97)
    fig.text(0.02, 0.905, subtitle, color=CAPTION, fontsize=11)

    fig.text(
        0.02, 0.03,
        "Identical facts → identical decisions. Any gap here would be a bug we surface, not hide.",
        color=CAPTION, fontsize=10, style="italic",
    )

    plt.subplots_adjust(left=0.22, right=0.97, top=0.86, bottom=0.14)
    fig.savefig(out_path, dpi=180, facecolor=BG)
    plt.close(fig)
    print(f"wrote {out_path.relative_to(Path.cwd()) if out_path.is_absolute() else out_path}")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    personas = load_personas()
    n = len(personas)

    print(f"Loaded {n} personas from {PERSONAS_PATH.name}")

    for slice_key, title in [
        ("gender", "Match Rate by Gender"),
        ("state",  "Match Rate by State"),
        ("urban",  "Match Rate by Urban / Rural"),
    ]:
        data = match_rates_by(slice_key, personas)
        if not data:
            print(f"  skip {slice_key}: no personas tagged")
            continue
        # Rename urban True/False for the deck
        if slice_key == "urban":
            data = {("Urban" if k == "True" else "Rural"): v for k, v in data.items()}
        subtitle = f"Setu · n={sum(v[0] for v in data.values())} personas · slice: {slice_key}"
        render_bar_chart(title, subtitle, data, OUT_DIR / f"fairness_by_{slice_key}.png")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
