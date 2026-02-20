#!/usr/bin/env python3
"""Setup wizard — interactive CLI to generate config/preferences.yaml."""

import sys
from pathlib import Path

import yaml

PREFS_PATH = Path(__file__).parent / "config" / "preferences.yaml"


def ask(prompt: str, default: str = "") -> str:
    """Prompt user for input with a default value shown in brackets."""
    suffix = f" [{default}]" if default else ""
    answer = input(f"{prompt}{suffix}: ").strip()
    return answer if answer else default


def ask_yn(prompt: str, default: bool = True) -> bool:
    """Prompt user for yes/no with a default."""
    hint = "Y/n" if default else "y/N"
    answer = input(f"{prompt} [{hint}]: ").strip().lower()
    if not answer:
        return default
    return answer in ("y", "yes")


def ask_choice(prompt: str, choices: list[str], default: str = "") -> str:
    """Prompt user to pick from a list of choices."""
    for i, c in enumerate(choices, 1):
        marker = " (default)" if c == default else ""
        print(f"  {i}. {c}{marker}")
    answer = input(f"{prompt} [1-{len(choices)}]: ").strip()
    if not answer and default:
        return default
    try:
        idx = int(answer) - 1
        return choices[idx]
    except (ValueError, IndexError):
        return default or choices[0]


def load_existing() -> dict:
    """Load existing preferences if present."""
    if PREFS_PATH.exists():
        try:
            return yaml.safe_load(PREFS_PATH.read_text()) or {}
        except Exception:
            pass
    return {}


def run_wizard() -> dict:
    """Run the interactive setup wizard."""
    existing = load_existing()
    modules = existing.get("modules", {})
    deployment = existing.get("deployment", {})
    schedule = existing.get("schedule", {})

    print()
    print("=" * 50)
    print("  Joe AI — Setup Wizard")
    print("=" * 50)
    print()

    if existing:
        print("  (Current values shown in brackets)\n")

    # ── Modules ──────────────────────────────────────────────

    print("── Module Selection ──\n")

    stocks = ask_yn(
        "Enable stocks module?",
        default=modules.get("stocks", True),
    )
    crypto = ask_yn(
        "Enable crypto module?",
        default=modules.get("crypto", False),
    )
    after_hours = ask_yn(
        "Enable after-hours analysis?",
        default=modules.get("after_hours", True),
    )

    # ── Deployment ───────────────────────────────────────────

    print("\n── Deployment ──\n")

    mode = ask_choice(
        "Deployment mode",
        ["local", "cloud"],
        default=deployment.get("mode", "local"),
    )

    github_repo = ""
    gcp_project = ""
    gcp_region = "us-central1"
    push_data = False

    if mode == "cloud":
        github_repo = ask(
            "GitHub repo URL (e.g. https://github.com/user/repo)",
            default=deployment.get("github_repo", ""),
        )
        gcp_project = ask(
            "GCP project ID",
            default=deployment.get("gcp_project", ""),
        )
        gcp_region = ask(
            "GCP region",
            default=deployment.get("gcp_region", "us-central1"),
        )
        push_data = ask_yn(
            "Push data to GitHub after pipeline runs?",
            default=deployment.get("push_data_after_run", True),
        )
    else:
        push_data = ask_yn(
            "Push data to GitHub after pipeline runs?",
            default=deployment.get("push_data_after_run", False),
        )
        if push_data:
            github_repo = ask(
                "GitHub repo URL",
                default=deployment.get("github_repo", ""),
            )

    # ── Schedule ─────────────────────────────────────────────

    print("\n── Schedule ──\n")

    timezone = ask(
        "Timezone",
        default=schedule.get("timezone", "US/Eastern"),
    )
    morning_run = ask(
        "Morning pipeline run time",
        default=schedule.get("morning_run", "09:00"),
    )
    afternoon_run = ask(
        "Afternoon pipeline run time",
        default=schedule.get("afternoon_run", "15:00"),
    )

    crypto_morning = "08:00"
    crypto_evening = "20:00"
    if crypto:
        crypto_morning = ask(
            "Crypto morning run time",
            default=schedule.get("crypto_morning", "08:00"),
        )
        crypto_evening = ask(
            "Crypto evening run time",
            default=schedule.get("crypto_evening", "20:00"),
        )

    # ── Build config ─────────────────────────────────────────

    prefs = {
        "modules": {
            "stocks": stocks,
            "crypto": crypto,
            "after_hours": after_hours,
        },
        "deployment": {
            "mode": mode,
            "push_data_after_run": push_data,
            "github_repo": github_repo,
            "gcp_project": gcp_project,
            "gcp_region": gcp_region,
        },
        "telegram": {
            "mode": "webhook" if mode == "cloud" else "polling",
        },
        "schedule": {
            "timezone": timezone,
            "morning_run": morning_run,
            "afternoon_run": afternoon_run,
            "crypto_morning": crypto_morning,
            "crypto_evening": crypto_evening,
        },
    }

    # ── Summary ──────────────────────────────────────────────

    print("\n── Summary ──\n")
    print(yaml.dump(prefs, default_flow_style=False, sort_keys=False))

    if not ask_yn("Save this configuration?", default=True):
        print("Aborted — no changes made.")
        return prefs

    # ── Write file ───────────────────────────────────────────

    PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
    PREFS_PATH.write_text(yaml.dump(prefs, default_flow_style=False, sort_keys=False))
    print(f"\nSaved to {PREFS_PATH}")
    print("Run the pipeline with:  python main.py --once --broker capital")
    return prefs


if __name__ == "__main__":
    try:
        run_wizard()
    except KeyboardInterrupt:
        print("\n\nAborted.")
        sys.exit(1)
