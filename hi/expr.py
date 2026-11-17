"""A tiny, safe math-expression language for scenes ("sin(x) * cos(y + t)"), checked here and evaluated by the chat.

It is a calculator, not Python or JavaScript: numbers, a few named variables, + - * / % ^, parentheses, and the
functions listed below. There is no `eval`, no attribute access and no strings, so an expression can only compute a
number. The browser has its own evaluator for the same grammar (tinyui/src/lib/expr.ts); this one parses the expression
when a scene is saved, so a mistake comes back to the model as an error instead of a blank viewer.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

MAX_CHARS = 300
MAX_NODES = 200
MAX_DEPTH = 24
CONSTANTS = {"pi": math.pi, "e": math.e, "tau": math.tau}


def _noise(x: float, y: float = 0.0, z: float = 0.0) -> float:
    """A smooth-ish repeatable value in [-1, 1]. Only used here to probe an expression; the chat has its own."""
    return math.sin(x * 12.9898 + y * 78.233 + z * 37.719) * 0.5 + math.sin(x * 3.1 + y * 1.7 + z * 2.3) * 0.5


def _clamp(v: float, lo: float, hi: float) -> float:
    return min(max(v, lo), hi)


def _smoothstep(a: float, b: float, x: float) -> float:
    t = _clamp((x - a) / (b - a) if b != a else 0.0, 0.0, 1.0)
    return t * t * (3 - 2 * t)


FUNCTIONS: dict[str, tuple[int, object]] = {
    "sin": (1, math.sin), "cos": (1, math.cos), "tan": (1, math.tan), "asin": (1, math.asin), "acos": (1, math.acos),
    "atan": (1, math.atan), "atan2": (2, math.atan2), "sinh": (1, math.sinh), "cosh": (1, math.cosh), "tanh": (1, math.tanh),
    "sqrt": (1, math.sqrt), "abs": (1, abs), "exp": (1, math.exp), "log": (1, math.log), "ln": (1, math.log),
    "log2": (1, math.log2), "log10": (1, math.log10), "pow": (2, math.pow), "min": (2, min), "max": (2, max),
    "floor": (1, math.floor), "ceil": (1, math.ceil), "round": (1, round), "sign": (1, lambda v: (v > 0) - (v < 0)),
    "mod": (2, lambda a, b: a % b), "hypot": (2, math.hypot), "clamp": (3, _clamp), "mix": (3, lambda a, b, k: a + (b - a) * k),
    "smoothstep": (3, _smoothstep), "fract": (1, lambda v: v - math.floor(v)), "noise": (3, _noise),
    "step": (2, lambda edge, v: 1.0 if v >= edge else 0.0),
}

_TOKEN = re.compile(r"\s*(?:(\d+\.?\d*(?:[eE][+-]?\d+)?|\.\d+)|([A-Za-z_]\w*)|(.))")
_BINARY = {"+": (1, False), "-": (1, False), "*": (2, False), "/": (2, False), "%": (2, False), "^": (4, True)}


class ExprError(ValueError):
    pass


@dataclass(frozen=True)
class Parsed:
    names: frozenset[str]  # the variables it uses
    ast: tuple


class _Parser:
    def __init__(self, text: str, allowed: set[str]):
        self.tokens = self._lex(text)
        self.pos = 0
        self.allowed = allowed
        self.names: set[str] = set()
        self.nodes = 0

    @staticmethod
    def _lex(text: str) -> list[tuple[str, str]]:
        out, at = [], 0
        while at < len(text):
            m = _TOKEN.match(text, at)
            if not m or m.end() == at:
                break
            at = m.end()
            number, name, other = m.groups()
            if number is not None:
                out.append(("num", number))
            elif name is not None:
                out.append(("name", name))
            elif other and not other.isspace():
                out.append(("op", other))
        if at < len(text.rstrip()):
            raise ExprError(f"unexpected character {text[at:at + 1]!r}")
        return out

    def peek(self) -> tuple[str, str] | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def take(self) -> tuple[str, str]:
        token = self.peek()
        if token is None:
            raise ExprError("the expression ends too soon")
        self.pos += 1
        return token

    def expect(self, op: str) -> None:
        kind, value = self.take()
        if (kind, value) != ("op", op):
            raise ExprError(f"expected {op!r}, got {value!r}")

    def parse(self, min_prec: int = 1, depth: int = 0) -> tuple:
        if depth > MAX_DEPTH:
            raise ExprError("the expression is nested too deeply")
        left = self.unary(depth)
        while (token := self.peek()) and token[0] == "op" and token[1] in _BINARY:
            prec, right_assoc = _BINARY[token[1]]
            if prec < min_prec:
                break
            self.take()
            right = self.parse(prec if right_assoc else prec + 1, depth + 1)
            left = (token[1], left, right)
            self.count()
        return left

    def count(self) -> None:
        self.nodes += 1
        if self.nodes > MAX_NODES:
            raise ExprError(f"the expression has more than {MAX_NODES} parts")

    def unary(self, depth: int) -> tuple:
        token = self.peek()
        if token == ("op", "-"):
            self.take()
            self.count()
            return ("neg", self.parse(3, depth + 1))  # binds tighter than * but looser than ^, so -x^2 is -(x^2)
        if token == ("op", "+"):
            self.take()
            return self.parse(3, depth + 1)
        return self.atom(depth)

    def atom(self, depth: int) -> tuple:
        self.count()
        kind, value = self.take()
        if kind == "num":
            return ("num", float(value))
        if kind == "name":
            if self.peek() == ("op", "("):
                if value not in FUNCTIONS:
                    raise ExprError(f"unknown function {value!r}; use one of: {', '.join(sorted(FUNCTIONS))}")
                self.take()
                args = []
                if self.peek() != ("op", ")"):
                    args.append(self.parse(1, depth + 1))
                    while self.peek() == ("op", ","):
                        self.take()
                        args.append(self.parse(1, depth + 1))
                self.expect(")")
                if len(args) != FUNCTIONS[value][0]:
                    raise ExprError(f"{value} takes {FUNCTIONS[value][0]} argument(s), got {len(args)}")
                return ("call", value, args)
            if value in CONSTANTS:
                return ("num", CONSTANTS[value])
            if value not in self.allowed:
                raise ExprError(f"unknown name {value!r}; the variables here are: {', '.join(sorted(self.allowed))}")
            self.names.add(value)
            return ("var", value)
        if (kind, value) == ("op", "("):
            inner = self.parse(1, depth + 1)
            self.expect(")")
            return inner
        raise ExprError(f"unexpected {value!r}")


def parse(text: str, allowed: set[str] | frozenset[str]) -> Parsed:
    """The expression parsed, or ExprError saying what is wrong. `allowed` is the variable names it may use."""
    if not isinstance(text, str) or not text.strip():
        raise ExprError("the expression is empty")
    if len(text) > MAX_CHARS:
        raise ExprError(f"the expression is longer than {MAX_CHARS} characters")
    parser = _Parser(text, set(allowed))
    ast = parser.parse()
    if parser.peek() is not None:
        raise ExprError(f"unexpected {parser.peek()[1]!r}")
    return Parsed(frozenset(parser.names), ast)


def evaluate(parsed: Parsed, values: dict[str, float]) -> float:
    """The value at `values`; nan where it is undefined (division by zero, sqrt of a negative, ...)."""
    def run(node: tuple) -> float:
        kind = node[0]
        if kind == "num":
            return node[1]
        if kind == "var":
            return values[node[1]]
        if kind == "neg":
            return -run(node[1])
        if kind == "call":
            return float(FUNCTIONS[node[1]][1](*(run(a) for a in node[2])))  # type: ignore[operator]
        a, b = run(node[1]), run(node[2])
        return {"+": lambda: a + b, "-": lambda: a - b, "*": lambda: a * b, "/": lambda: a / b, "%": lambda: a % b, "^": lambda: a ** b}[kind]()

    try:
        return run(parsed.ast)
    except (ZeroDivisionError, ValueError, OverflowError, TypeError):
        return math.nan
