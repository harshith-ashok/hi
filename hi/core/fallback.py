"""Try a list of alternatives in order, skipping dependencies known to be down."""

from __future__ import annotations

from typing import Callable, TypeVar

from hi.core import health

T = TypeVar("T")


class AllFailed(RuntimeError):
    """Every alternative failed or was skipped. `failures` maps dependency name to its error."""

    def __init__(self, failures: dict[str, str]):
        self.failures = failures
        detail = "; ".join(f"{dep}: {err}" for dep, err in failures.items()) or "nothing to try"
        super().__init__(f"No option worked ({detail})")


def first_available(chain: list[tuple[str, Callable[[], T]]]) -> T:
    """Call each `(dependency, fn)` in order and return the first result.

    A dependency in cooldown is skipped. A success marks it up, a failure marks it down and moves on.
    Raises AllFailed if none worked. Catches Exception on purpose: this is the boundary where one
    alternative's failure must not stop the next.
    """
    failures: dict[str, str] = {}
    for dep, fn in chain:
        if not health.is_up(dep):
            failures[dep] = "recently failed, skipped"
            continue
        try:
            result = fn()
        except Exception as e:
            health.mark_down(dep, e)
            failures[dep] = str(e) or type(e).__name__
            continue
        health.mark_ok(dep)
        return result
    raise AllFailed(failures)
