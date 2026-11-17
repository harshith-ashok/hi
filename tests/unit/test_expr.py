import math

import pytest

from hi import expr
from hi.expr import ExprError, evaluate, parse


def val(text, **v):
    return evaluate(parse(text, set(v) | {"x"}), {"x": 0.0, **v})


@pytest.mark.parametrize("text,expected", [
    ("1 + 2 * 3", 7), ("(1 + 2) * 3", 9), ("2 ^ 3 ^ 2", 512), ("-2 ^ 2", -4), ("2 * -3", -6), ("10 % 4", 2), ("7 / 2", 3.5),
    ("pi", math.pi), ("sin(0)", 0), ("max(2, 9)", 9), ("clamp(5, 0, 3)", 3), ("mix(0, 10, 0.25)", 2.5), ("hypot(3, 4)", 5),
    ("1e2 + .5", 100.5), ("abs(-3) + floor(2.7)", 5), ("smoothstep(0, 1, 0.5)", 0.5), ("fract(2.25)", 0.25),
])
def test_arithmetic_and_functions(text, expected):
    assert val(text) == pytest.approx(expected)


def test_variables_come_from_the_values_given():
    assert val("sin(x * 2) + t", x=math.pi / 4, t=1.0) == pytest.approx(2.0)
    assert parse("x * t + 1", {"x", "t"}).names == {"x", "t"}


@pytest.mark.parametrize("text,why", [
    ("", "empty"), ("   ", "empty"), ("sin(x", "ends too soon"), ("1 +", "ends too soon"), ("foo(x)", "unknown function"),
    ("y + 1", "unknown name"), ("sin()", "takes 1"), ("atan2(1)", "takes 2"), ("1 2", "unexpected"), ("x $ 2", "unexpected"),
    ("__import__('os')", "unknown function"), ("x.real", "unexpected"), ("'a'", "unexpected"), ("x" * 400, "longer than"),
    ("(" * 40 + "x" + ")" * 40, "nested"), ("x+" * 110 + "x", "more than"),
])
def test_bad_expressions_are_refused_with_a_reason(text, why):
    with pytest.raises(ExprError, match=why):
        parse(text, {"x"})


def test_undefined_values_are_nan_not_exceptions():
    for text in ("1 / x", "sqrt(x - 1)", "log(x - 1)", "acos(x + 5)", "10 ^ 1000", "mod(1, x)"):
        assert math.isnan(val(text)), text


def test_there_is_no_way_to_reach_python_from_an_expression():
    for evil in ("__import__", "open", "eval(x)", "x.__class__", "lambda: 1", "[1,2]", "x if x else 1", "import os"):
        with pytest.raises(ExprError):
            parse(evil, {"x"})


def test_every_listed_function_works_at_a_sample_point():
    for name, (arity, _) in expr.FUNCTIONS.items():
        text = f"{name}({', '.join(['0.5'] * arity)})"
        assert isinstance(val(text), float), name
