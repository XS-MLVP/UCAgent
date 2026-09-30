#!/usr/bin/env python3
"""Prepare, generate, and publish the repository's user-facing monthly report."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


COPY = json.loads(
    (Path(__file__).parents[1] / "monthly-report-copy.json").read_text(encoding="utf-8")
)
STATE_PATTERN = re.compile(
    r"<!--\s*ucagent-monthly-report-state:\s*(\{.*?\})\s*-->", re.DOTALL
)
REQUIRED_SECTIONS = tuple(COPY["required_sections"])


def parse_state(body: str) -> dict[str, str] | None:
    """Return a validated report state embedded in an issue body."""
    matches = STATE_PATTERN.findall(body or "")
    if not matches:
        return None
    try:
        state = json.loads(matches[-1])
    except (TypeError, json.JSONDecodeError):
        return None
    required = ("period", "head_sha", "generated_at")
    if not isinstance(state, dict) or any(not isinstance(state.get(key), str) for key in required):
        return None
    if not re.fullmatch(r"\d{4}-\d{2}", state["period"]):
        return None
    if not re.fullmatch(r"[0-9a-f]{40}", state["head_sha"]):
        return None
    return {key: state[key] for key in required}


def select_window(
    issues: list[dict[str, Any]], now: datetime
) -> tuple[str, str, int | None, str, bool]:
    """Select the start boundary and resumable issue for a manual run."""
    period = now.strftime("%Y-%m")
    year = now.strftime("%Y")
    valid: list[tuple[dict[str, str], dict[str, Any]]] = []
    for issue in issues:
        if "pull_request" in issue:
            continue
        state = parse_state(str(issue.get("body") or ""))
        if state:
            valid.append((state, issue))

    same_period = [(state, issue) for state, issue in valid if state["period"] == period]
    if same_period:
        state, issue = max(same_period, key=lambda item: item[0]["generated_at"])
        is_year_first = COPY["annual_title_token"] in str(issue.get("title") or "")
        return (
            state["head_sha"],
            "",
            int(issue["number"]),
            str(issue.get("body") or ""),
            is_year_first,
        )

    has_report_this_year = any(state["period"].startswith(year + "-") for state, _ in valid)
    start_date = f"{period}-01" if has_report_this_year else f"{year}-01-01"
    return "", start_date, None, "", not has_report_this_year


def write_github_output(path: Path, values: dict[str, str | int | bool]) -> None:
    """Append scalar values to a GitHub Actions output file."""
    with path.open("a", encoding="utf-8") as stream:
        for key, value in values.items():
            rendered = str(value).lower() if isinstance(value, bool) else str(value)
            stream.write(f"{key}={rendered}\n")


def git_output(*args: str) -> str:
    """Run a read-only Git command and return its trimmed standard output."""
    return subprocess.run(
        ["git", *args], check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    ).stdout.strip()


def prepare_command(args: argparse.Namespace) -> int:
    """Compute the commit window using state from earlier monthly-report issues."""
    issues = json.loads(Path(args.issues).read_text(encoding="utf-8"))
    if not isinstance(issues, list):
        raise ValueError("The issues input must be a JSON list")
    report_timezone = ZoneInfo(args.timezone)
    now = datetime.now(report_timezone) if not args.now else datetime.fromisoformat(args.now)
    if now.tzinfo is None:
        now = now.replace(tzinfo=report_timezone)
    now = now.astimezone(report_timezone)
    base_sha, start_date, issue_number, body, is_year_first = select_window(issues, now)
    head_sha = git_output("rev-parse", "HEAD")
    offset = now.strftime("%z")
    start_at = f"{start_date}T00:00:00{offset[:-2]}:{offset[-2:]}" if start_date else ""

    if base_sha:
        try:
            git_output("cat-file", "-e", f"{base_sha}^{{commit}}")
        except subprocess.CalledProcessError as exc:
            raise ValueError(
                f"Saved baseline commit {base_sha} is unavailable; rerun after fetching full history"
            ) from exc
        count = int(git_output("rev-list", "--no-merges", "--count", f"{base_sha}..{head_sha}"))
        range_label = COPY["range_after"].format(date=f"{now:%Y-%m-%d}")
        update_heading = COPY["heading_increment"].format(month=now.month, day=now.day)
        project_start_at = max(
            (state["generated_at"] for state, _ in same_period),
            default=now.isoformat(),
        )
    else:
        count = int(
            git_output(
                "rev-list", "--no-merges", "--count", head_sha, f"--since={start_at}"
            )
        )
        start = datetime.fromisoformat(start_date)
        range_label = COPY["range_dates"].format(
            start_year=start.year,
            start_month=start.month,
            start_day=start.day,
            end_year=now.year,
            end_month=now.month,
            end_day=now.day,
        )
        update_heading = (
            COPY["heading_annual"]
            if is_year_first
            else COPY["heading_month"].format(month=now.month)
        )
        project_start_at = start_at

    if is_year_first:
        issue_title = COPY["title_annual"].format(year=now.year, month=now.month)
    else:
        issue_title = COPY["title_month"].format(year=now.year, month=now.month)

    Path(args.existing_body).write_text(body, encoding="utf-8")
    write_github_output(
        Path(args.output),
        {
            "period": now.strftime("%Y-%m"),
            "base_sha": base_sha,
            "start_date": start_date,
            "start_at": start_at,
            "project_start_at": project_start_at,
            "head_sha": head_sha,
            "commit_count": count,
            "issue_number": issue_number or "",
            "issue_title": issue_title,
            "range_label": range_label,
            "update_heading": update_heading,
            "generated_at": now.isoformat().replace("+00:00", "Z"),
        },
    )
    return 0


def build_commit_batches(
    raw: str, max_entries: int = 120, max_chars: int = 16_000
) -> list[str]:
    """Split compact commit material into bounded batches for reliable LLM calls."""
    entries: list[str] = []
    for block in (part.strip() for part in raw.split("<<<END>>>") if part.strip()):
        lines = [line.rstrip() for line in block.splitlines()]
        body = [line for line in lines[1:] if line.strip()][:3]
        entry = "\n".join([lines[0], *body])[:800]
        entries.append(entry)
        if len(entries) >= 1_000:
            break
    batches: list[str] = []
    current: list[str] = []
    current_chars = 0
    separator_chars = len("\n<<<END>>>\n")
    for entry in entries:
        added_chars = len(entry) + (separator_chars if current else 0)
        if current and (len(current) >= max_entries or current_chars + added_chars > max_chars):
            batches.append("\n<<<END>>>\n".join(current))
            current = []
            current_chars = 0
            added_chars = len(entry)
        current.append(entry)
        current_chars += added_chars
    if current:
        batches.append("\n<<<END>>>\n".join(current))
    return batches


def validate_report(report: str, heading: str) -> str:
    """Validate and normalize the model's canonical Markdown fragment."""
    report = report.strip()
    if report.startswith("```") and report.endswith("```"):
        report = re.sub(r"^```(?:markdown)?\s*", "", report)
        report = re.sub(r"\s*```$", "", report).strip()
    if not report.startswith(f"## {heading}\n"):
        raise ValueError(f"AI output is missing the update heading: {heading}")
    missing = [section for section in REQUIRED_SECTIONS if section not in report]
    if missing:
        raise ValueError(f"AI output is missing required sections: {', '.join(missing)}")
    positions = [report.index(section) for section in REQUIRED_SECTIONS]
    if positions != sorted(positions):
        raise ValueError("AI output sections are not in the required order")
    return report + "\n"


def request_ai(prompt: str, commits: str, heading: str) -> str:
    """Request a report through the same OpenAI-compatible Chat Completions API as release notes."""
    api_key = os.environ.get("AI_API_KEY", "").strip()
    if not api_key:
        raise ValueError("AI_API_KEY is not configured")
    api_base = (
        os.environ.get("AI_API_BASE")
        or os.environ.get("AI_API_BASE_SECRET")
        or "https://api.openai.com/v1"
    ).strip().rstrip("/")
    model = (os.environ.get("AI_MODEL") or os.environ.get("AI_MODEL_SECRET") or "gpt-5.3-codex").strip()
    chat_path = (os.environ.get("AI_CHAT_PATH") or "/chat/completions").strip()
    if not chat_path.startswith("/"):
        chat_path = "/" + chat_path
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": COPY["system_prompt"]},
            {
                "role": "user",
                "content": (
                    prompt.replace("{{UPDATE_HEADING}}", heading)
                    + f"\n\n# {COPY['commit_data_heading']}\n\n"
                    + commits
                ),
            },
        ],
        "temperature": 0.2,
    }
    retryable = {408, 429, 500, 502, 503, 504, 529}
    last_error = "AI request failed"
    for attempt, delay in enumerate((2, 5, 10, 0)):
        request = urllib.request.Request(
            f"{api_base}{chat_path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                data = json.loads(response.read().decode("utf-8"))
            return str(data["choices"][0]["message"]["content"])
        except urllib.error.HTTPError as exc:
            last_error = f"AI API returned HTTP {exc.code}"
            if exc.code not in retryable or attempt == 3:
                break
        except Exception as exc:  # Network and provider payload errors share retry behavior.
            last_error = str(exc)
            if attempt == 3:
                break
        time.sleep(delay)
    raise RuntimeError(last_error)


def generate_command(args: argparse.Namespace) -> int:
    """Generate a publishable report through bounded extraction and synthesis calls."""
    raw = Path(args.commits).read_text(encoding="utf-8", errors="replace")
    prompt = Path(args.prompt).read_text(encoding="utf-8")
    publish_ready = False
    error = ""
    try:
        batches = build_commit_batches(raw)
        if not batches:
            raise ValueError("No commit material was provided")
        if len(batches) == 1:
            print("Generating report from one commit batch...", flush=True)
            report = validate_report(request_ai(prompt, batches[0], args.heading), args.heading)
        else:
            summaries: list[str] = []
            for index, batch in enumerate(batches, start=1):
                print(f"Summarizing commit batch {index}/{len(batches)}...", flush=True)
                batch_heading = COPY["batch_heading"].format(index=index)
                summaries.append(
                    validate_report(request_ai(prompt, batch, batch_heading), batch_heading)
                )
            synthesis_material = (
                COPY["synthesis_notice"]
                + "\n\n"
                + "\n<<<SUMMARY>>>\n".join(summaries)
            )
            print("Synthesizing the final report...", flush=True)
            report = validate_report(
                request_ai(prompt, synthesis_material, args.heading), args.heading
            )
        publish_ready = True
    except Exception as exc:
        error = str(exc)
        report = f"## {args.heading}\n\n{COPY['generation_failed']}\n"
    first_line, remainder = report.split("\n", 1)
    report = (
        f"{first_line}\n\n{COPY['range_line'].format(range=args.range_label)}\n\n"
        + remainder.lstrip()
    )
    Path(args.report).write_text(report, encoding="utf-8")
    Path(args.metadata).write_text(
        json.dumps({"publish_ready": publish_ready, "error": error}, ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    if args.output:
        write_github_output(Path(args.output), {"publish_ready": publish_ready})
    return 0


def merge_issue_body(existing: str, report: str, state: dict[str, str]) -> str:
    """Append an incremental report while replacing the single resume marker."""
    clean = STATE_PATTERN.sub("", existing).rstrip()
    parts = [part for part in (clean, report.strip()) if part]
    body = "\n\n---\n\n".join(parts)
    marker = "<!-- ucagent-monthly-report-state: " + json.dumps(state, separators=(",", ":")) + " -->"
    merged = body + "\n\n" + marker + "\n"
    if len(merged.encode("utf-8")) > 64_000:
        raise ValueError("Monthly report issue is near GitHub's body limit; start a new report issue")
    return merged


def github_request(url: str, token: str, method: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Send an authenticated JSON request to the GitHub REST API."""
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
        method=method,
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def publish_command(args: argparse.Namespace) -> int:
    """Create or update the period's GitHub issue after successful AI generation."""
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    repository = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if not token or not repository:
        raise ValueError("GITHUB_TOKEN and GITHUB_REPOSITORY are required")
    state = {"period": args.period, "head_sha": args.head_sha, "generated_at": args.generated_at}
    body = merge_issue_body(
        Path(args.existing_body).read_text(encoding="utf-8"),
        Path(args.report).read_text(encoding="utf-8"),
        state,
    )
    base_url = f"https://api.github.com/repos/{repository}"
    label_payload = {
        "name": "monthly-report",
        "color": "1f6feb",
        "description": COPY["label_description"],
    }
    try:
        github_request(f"{base_url}/labels", token, "POST", label_payload)
    except urllib.error.HTTPError as exc:
        if exc.code != 422:  # The label already exists.
            raise
    payload = {"title": args.title, "body": body, "labels": ["monthly-report"]}
    if args.issue_number:
        result = github_request(f"{base_url}/issues/{args.issue_number}", token, "PATCH", payload)
    else:
        result = github_request(f"{base_url}/issues", token, "POST", payload)
    print(result.get("html_url", "Monthly report published"))
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line interface used by the workflow and focused tests."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    prepare = commands.add_parser("prepare", help="select the incremental commit window")
    prepare.add_argument("--issues", required=True)
    prepare.add_argument("--existing-body", required=True)
    prepare.add_argument("--output", required=True)
    prepare.add_argument("--now")
    prepare.add_argument("--timezone", default="Asia/Shanghai")
    prepare.set_defaults(handler=prepare_command)

    generate = commands.add_parser("generate", help="generate the report fragment")
    generate.add_argument("--commits", required=True)
    generate.add_argument("--prompt", required=True)
    generate.add_argument("--heading", required=True)
    generate.add_argument("--range-label", required=True)
    generate.add_argument("--report", required=True)
    generate.add_argument("--metadata", required=True)
    generate.add_argument("--output")
    generate.set_defaults(handler=generate_command)

    publish = commands.add_parser("publish", help="publish the report to a GitHub issue")
    publish.add_argument("--existing-body", required=True)
    publish.add_argument("--report", required=True)
    publish.add_argument("--period", required=True)
    publish.add_argument("--head-sha", required=True)
    publish.add_argument("--generated-at", required=True)
    publish.add_argument("--title", required=True)
    publish.add_argument("--issue-number")
    publish.set_defaults(handler=publish_command)
    return parser


def main() -> int:
    """Dispatch the selected monthly-report workflow command."""
    args = build_parser().parse_args()
    return int(args.handler(args))


if __name__ == "__main__":
    sys.exit(main())
