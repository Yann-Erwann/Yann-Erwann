#!/usr/bin/env python3
"""Generate a local GitHub streak SVG for the profile README."""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
from pathlib import Path
import sys
from typing import Any
from urllib import request


GRAPHQL_ENDPOINT = "https://api.github.com/graphql"
ONE_YEAR_DAYS = 365


QUERY = """
query($user: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $user) {
    contributionsCollection(from: $from, to: $to) {
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays {
            date
            contributionCount
          }
        }
      }
    }
  }
}
"""


def request_contributions(user: str, token: str) -> tuple[int, list[dict[str, Any]]]:
    today = dt.datetime.now(dt.timezone.utc).date()
    start = today - dt.timedelta(days=ONE_YEAR_DAYS)
    variables = {
        "user": user,
        "from": f"{start.isoformat()}T00:00:00Z",
        "to": f"{today.isoformat()}T23:59:59Z",
    }
    payload = json.dumps({"query": QUERY, "variables": variables}).encode("utf-8")
    http_request = request.Request(
        GRAPHQL_ENDPOINT,
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "github-streak-profile-card",
        },
        method="POST",
    )

    with request.urlopen(http_request, timeout=30) as response:
        body = json.loads(response.read().decode("utf-8"))

    if body.get("errors"):
        messages = "; ".join(error.get("message", "Unknown GraphQL error") for error in body["errors"])
        raise RuntimeError(messages)

    user_data = body.get("data", {}).get("user")
    if user_data is None:
        raise RuntimeError(f"GitHub user not found: {user}")

    calendar = user_data["contributionsCollection"]["contributionCalendar"]
    days = [day for week in calendar["weeks"] for day in week["contributionDays"]]
    days.sort(key=lambda day: day["date"])
    return calendar["totalContributions"], days


def compute_streaks(days: list[dict[str, Any]]) -> tuple[int, int, str]:
    current = 0
    for day in reversed(days):
        if int(day["contributionCount"]) <= 0:
            break
        current += 1

    longest = 0
    running = 0
    last_active = "n/a"
    for day in days:
        if int(day["contributionCount"]) > 0:
            running += 1
            last_active = day["date"]
        else:
            longest = max(longest, running)
            running = 0
    longest = max(longest, running)
    return current, longest, last_active


def activity_color(count: int) -> str:
    if count == 0:
        return "#21262d"
    if count <= 2:
        return "#0e4429"
    if count <= 5:
        return "#006d32"
    if count <= 10:
        return "#26a641"
    return "#39d353"


def render_heatmap(days: list[dict[str, Any]]) -> str:
    recent_days = days[-91:]
    cell = 8
    gap = 4
    start_x = 440
    start_y = 84
    rects: list[str] = []

    for index, day in enumerate(recent_days):
        x = start_x + (index // 7) * (cell + gap)
        y = start_y + (index % 7) * (cell + gap)
        count = int(day["contributionCount"])
        date = html.escape(day["date"])
        rects.append(
            f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" rx="2" '
            f'fill="{activity_color(count)}"><title>{date}: {count} contribution(s)</title></rect>'
        )

    return "\n  ".join(rects)


def render_svg(user: str, total: int, days: list[dict[str, Any]]) -> str:
    current, longest, last_active = compute_streaks(days)
    updated_at = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    heatmap = render_heatmap(days)

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="620" height="220" viewBox="0 0 620 220" role="img" aria-labelledby="title desc">
  <title id="title">GitHub Streak de {html.escape(user)}</title>
  <desc id="desc">Serie actuelle, meilleure serie et contributions publiques sur les 12 derniers mois.</desc>
  <defs>
    <linearGradient id="border" x1="0" x2="1" y1="0" y2="1">
      <stop offset="0%" stop-color="#1f6feb" />
      <stop offset="55%" stop-color="#2da44e" />
      <stop offset="100%" stop-color="#06b6d4" />
    </linearGradient>
  </defs>
  <rect width="620" height="220" rx="12" fill="#0d1117" />
  <rect x="1" y="1" width="618" height="218" rx="11" fill="none" stroke="url(#border)" stroke-width="2" opacity="0.8" />
  <text x="32" y="42" fill="#f0f6fc" font-family="Segoe UI, Ubuntu, Arial, sans-serif" font-size="24" font-weight="700">GitHub Streak</text>
  <text x="32" y="68" fill="#8b949e" font-family="Segoe UI, Ubuntu, Arial, sans-serif" font-size="13">{html.escape(user)} · 12 derniers mois · contributions publiques</text>

  <g font-family="Segoe UI, Ubuntu, Arial, sans-serif">
    <text x="70" y="114" text-anchor="middle" fill="#39d353" font-size="30" font-weight="700">{current}</text>
    <text x="70" y="134" text-anchor="middle" fill="#8b949e" font-size="12">serie actuelle</text>

    <text x="230" y="114" text-anchor="middle" fill="#58a6ff" font-size="30" font-weight="700">{longest}</text>
    <text x="230" y="134" text-anchor="middle" fill="#8b949e" font-size="12">meilleure serie</text>

    <text x="390" y="114" text-anchor="middle" fill="#f2cc60" font-size="30" font-weight="700">{total}</text>
    <text x="390" y="134" text-anchor="middle" fill="#8b949e" font-size="12">contributions</text>
  </g>

  <text x="32" y="196" fill="#8b949e" font-family="Segoe UI, Ubuntu, Arial, sans-serif" font-size="12">Derniere activite: {html.escape(last_active)} · MAJ: {html.escape(updated_at)}</text>
  <text x="588" y="196" text-anchor="end" fill="#8b949e" font-family="Segoe UI, Ubuntu, Arial, sans-serif" font-size="12">GitHub API</text>

  {heatmap}
</svg>
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--user", default="Yann-Erwann")
    parser.add_argument("--output", default="assets/github-streak.svg")
    args = parser.parse_args()

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN is required")

    total, days = request_contributions(args.user, token)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_svg(args.user, total, days), encoding="utf-8")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
