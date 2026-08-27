"""Daily LeetCode problem selection + attempt logging, one Markdown file
per day under <VAULT_PATH>/hi/tasks/leetcode/ (frontmatter: slug/topic/
difficulty/solved/time_spent_minutes) so streak/weak-topic stats are
computed from real logged data, not a running counter that can drift out
of sync with reality.

Opens the picked problem via hi/browser.py's open_url() — the user's
actual default browser, a real persistent tab. An earlier version used
the Playwright MCP server's `browser_navigate` instead; that was the
wrong tool for this specific job, caught live: Playwright drives its own
separate, automation-managed browser instance (started fresh per call,
not left running afterward), not the user's regular browser — so nothing
ever visibly opened where the user could actually see or solve the
problem, even though the tool call itself reported success. Playwright
stays the right tool for `term`'s own page-reading/navigation needs; this
is a different job, "open a link where a human can see it" — the same
job hi/browser.py's open_url() now handles generally, not just here.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from langchain_core.tools import tool

from hi.browser import open_url
from hi.config import VAULT_PATH
from hi.frontmatter import dump_frontmatter, parse_frontmatter

LEETCODE_DIR = VAULT_PATH / "hi" / "tasks" / "leetcode"


@dataclass(frozen=True)
class Problem:
    slug: str
    title: str
    topic: str
    difficulty: str  # Easy/Medium/Hard

    @property
    def url(self) -> str:
        return f"https://leetcode.com/problems/{self.slug}/"


# A small, fixed curated set — "start simple: rotate/random; later weight
# toward weak topics once there's history" (TODO.md). No LeetCode API
# integration: this is enough breadth (9 topics, all 3 difficulties) for a
# real daily rotation without depending on a network-fetched problem list.
PROBLEM_BANK: tuple[Problem, ...] = (
    Problem("two-sum", "Two Sum", "array", "Easy"),
    Problem("valid-parentheses", "Valid Parentheses", "stack", "Easy"),
    Problem("merge-two-sorted-lists", "Merge Two Sorted Lists", "linked-list", "Easy"),
    Problem("best-time-to-buy-and-sell-stock", "Best Time to Buy and Sell Stock", "array", "Easy"),
    Problem("climbing-stairs", "Climbing Stairs", "dp", "Easy"),
    Problem("valid-anagram", "Valid Anagram", "hash-table", "Easy"),
    Problem("linked-list-cycle", "Linked List Cycle", "linked-list", "Easy"),
    Problem("invert-binary-tree", "Invert Binary Tree", "tree", "Easy"),
    Problem("maximum-subarray", "Maximum Subarray", "dp", "Medium"),
    Problem("group-anagrams", "Group Anagrams", "hash-table", "Medium"),
    Problem("binary-tree-level-order-traversal", "Binary Tree Level Order Traversal", "tree", "Medium"),
    Problem("number-of-islands", "Number of Islands", "graph", "Medium"),
    Problem(
        "longest-substring-without-repeating-characters",
        "Longest Substring Without Repeating Characters",
        "sliding-window",
        "Medium",
    ),
    Problem("course-schedule", "Course Schedule", "graph", "Medium"),
    Problem("kth-largest-element-in-an-array", "Kth Largest Element in an Array", "heap", "Medium"),
    Problem("word-break", "Word Break", "dp", "Medium"),
    Problem("clone-graph", "Clone Graph", "graph", "Medium"),
    Problem("merge-intervals", "Merge Intervals", "array", "Medium"),
    Problem("validate-binary-search-tree", "Validate Binary Search Tree", "tree", "Medium"),
    Problem("lru-cache", "LRU Cache", "design", "Medium"),
    Problem("longest-palindromic-substring", "Longest Palindromic Substring", "dp", "Medium"),
    Problem("container-with-most-water", "Container With Most Water", "two-pointers", "Medium"),
    Problem("3sum", "3Sum", "two-pointers", "Medium"),
    Problem("trapping-rain-water", "Trapping Rain Water", "two-pointers", "Hard"),
    Problem("median-of-two-sorted-arrays", "Median of Two Sorted Arrays", "binary-search", "Hard"),
)
_BY_SLUG = {p.slug: p for p in PROBLEM_BANK}


def _log_path(day: date) -> Path:
    return LEETCODE_DIR / f"{day.isoformat()}.md"


def _all_logs() -> list[dict]:
    if not LEETCODE_DIR.is_dir():
        return []
    logs = []
    for path in sorted(LEETCODE_DIR.glob("*.md")):
        fields, _body = parse_frontmatter(path.read_text())
        fields["date"] = path.stem
        logs.append(fields)
    return logs


def todays_log() -> dict | None:
    path = _log_path(date.today())
    if not path.exists():
        return None
    fields, _body = parse_frontmatter(path.read_text())
    fields["date"] = path.stem
    return fields


def topic_stats() -> dict[str, dict]:
    """Per-topic {attempted, solved, solve_rate} across every logged
    attempt — the "weak-topic breakdown"."""
    stats: dict[str, dict] = {}
    for log in _all_logs():
        topic = str(log.get("topic", "unknown"))
        entry = stats.setdefault(topic, {"attempted": 0, "solved": 0})
        entry["attempted"] += 1
        if log.get("solved") == "True":
            entry["solved"] += 1
    for entry in stats.values():
        entry["solve_rate"] = entry["solved"] / entry["attempted"] if entry["attempted"] else 0.0
    return stats


def streak_days() -> int:
    """Consecutive logged days ending today or yesterday — not having
    logged *yet* today shouldn't zero out the streak before the day is
    even over. Counts showing up (solved or not), not a perfect score."""
    logged_dates = {log["date"] for log in _all_logs()}
    if not logged_dates:
        return 0
    day = date.today()
    if day.isoformat() not in logged_dates:
        day -= timedelta(days=1)
    streak = 0
    while day.isoformat() in logged_dates:
        streak += 1
        day -= timedelta(days=1)
    return streak


def pick_daily_problem() -> Problem:
    """Pick today's problem: already-solved slugs are excluded so it
    doesn't repeat, weighted toward topics with a lower historical solve
    rate once there's enough history to weight by (a never-attempted
    topic gets the same "prioritize it" weight as the weakest attempted
    one) — falls back to a uniform random pick with no history yet."""
    logs = _all_logs()
    solved_slugs = {log.get("slug") for log in logs if log.get("solved") == "True"}
    candidates = [p for p in PROBLEM_BANK if p.slug not in solved_slugs] or list(PROBLEM_BANK)

    if not logs:
        return random.choice(candidates)

    stats = topic_stats()

    def weight(p: Problem) -> float:
        entry = stats.get(p.topic)
        if not entry or entry["attempted"] == 0:
            return 1.0
        return max(1.0 - entry["solve_rate"], 0.1)

    return random.choices(candidates, weights=[weight(p) for p in candidates], k=1)[0]


def log_attempt(slug: str, solved: bool, time_spent_minutes: int | None = None, day: date | None = None) -> Path:
    day = day or date.today()
    problem = _BY_SLUG.get(slug)
    fields: dict[str, str | list[str]] = {
        "tags": ["hi", "leetcode"],
        "slug": slug,
        "title": problem.title if problem else slug,
        "topic": problem.topic if problem else "unknown",
        "difficulty": problem.difficulty if problem else "unknown",
        "solved": str(solved),
    }
    if time_spent_minutes is not None:
        fields["time_spent_minutes"] = str(time_spent_minutes)

    LEETCODE_DIR.mkdir(parents=True, exist_ok=True)
    path = _log_path(day)
    path.write_text(f"{dump_frontmatter(fields)}\n# {fields['title']}\n")
    return path


@tool
def leetcode_daily() -> str:
    """Pick today's LeetCode problem (skipping already-solved ones,
    weighted toward weaker topics once there's history) and open it in
    the browser. If today's problem is already logged, reports that
    instead of picking a new one. Use for "give me today's LeetCode
    problem" / "do my daily LeetCode"."""
    existing = todays_log()
    if existing:
        return (
            f"Already logged today: {existing.get('title')} ({existing.get('slug')}) — "
            f"solved={existing.get('solved')}"
        )
    problem = pick_daily_problem()
    opened = open_url(problem.url)
    return f"Today's problem: {problem.title} ({problem.difficulty}, {problem.topic})\n{problem.url}\n{opened}"


@tool
def log_leetcode_attempt(slug: str, solved: bool, time_spent_minutes: int | None = None) -> str:
    """Log today's attempt at a LeetCode problem.

    Args:
        slug: The problem's URL slug, e.g. "two-sum".
        solved: Whether it was solved.
        time_spent_minutes: Optional time spent, in minutes.
    """
    path = log_attempt(slug, solved, time_spent_minutes)
    return f"Logged {'solved' if solved else 'attempted'}: {slug} -> {path.name}"


@tool
def leetcode_stats() -> str:
    """Show the current LeetCode streak and a per-topic solve-rate
    breakdown (weakest topics first)."""
    streak = streak_days()
    stats = topic_stats()
    lines = [f"Streak: {streak} day{'s' if streak != 1 else ''}"]
    if stats:
        lines.append("Topic breakdown (weakest first):")
        for topic, s in sorted(stats.items(), key=lambda kv: kv[1]["solve_rate"]):
            lines.append(f"  {topic}: {s['solved']}/{s['attempted']} solved ({s['solve_rate']:.0%})")
    else:
        lines.append("No attempts logged yet.")
    return "\n".join(lines)
