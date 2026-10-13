"""Conservative reconstruction of short, source-anchored PDF equation blocks."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass

from app.services.compound_units import UNIT, unit_factors
from app.services.formula_units import formula_output_unit


SYMBOL = r"[A-Za-zφ][A-Za-z0-9_₀-₉ₓₒₐ]*"
PRODUCT = rf"{SYMBOL}(?:[ \t]+{SYMBOL}){{0,3}}"
STACKED_POWER_FRACTION = re.compile(
    rf"(?m)^(?P<block>(?P<base>{SYMBOL})[ \t]*\r?\n[ \t]*(?P<power>{SYMBOL}|[0-8])"
    rf"[ \t]*=[ \t]*(?P<numerator>{PRODUCT})[ \t]*\r?\n[ \t]*(?P<denominator>{PRODUCT}))[ \t]*$")
STACKED_FRACTION = re.compile(
    rf"(?m)^(?P<block>(?P<lhs>{SYMBOL})[ \t]*=[ \t]*(?P<numerator>{PRODUCT})"
    rf"[ \t]*\r?\n[ \t]*(?P<denominator>{PRODUCT}))[ \t]*$")
STACKED_POWER = re.compile(
    rf"(?m)^(?P<block>(?P<base>{SYMBOL})[ \t]*\r?\n[ \t]*(?P<power>{SYMBOL}|[0-8])"
    rf"[ \t]*=[ \t]*(?P<rhs>{SYMBOL}|[0-9.]+))[ \t]*$")
WRAPPED_ADD_FRACTION = re.compile(
    rf"(?m)^(?P<block>(?P<lhs>{SYMBOL})[ \t]*=[ \t]*(?P<base>{SYMBOL})"
    rf"[ \t]*(?P<operator>[+\-])[ \t]*(?P<numerator>{SYMBOL})[ \t]*\r?\n"
    rf"[ \t]*(?P<denominator>(?:\d+(?:\.\d+)?[ \t]*[x×*][ \t]*{SYMBOL}|"
    rf"\([A-Za-z0-9_φ.+* /-]{{2,50}}\)))[ \t]*)(?=\r?\n|$)")
WRAPPED_OPERATOR_FRACTION = re.compile(
    rf"(?m)^(?P<block>(?P<lhs>{SYMBOL})[ \t]*=[ \t]*(?P<base>{SYMBOL})[ \t]*"
    rf"(?P<operator>[+\-])[ \t]*\r?\n[ \t]*(?P<numerator>{SYMBOL})[ \t]*\r?\n"
    rf"[ \t]*/[ \t]*\r?\n[ \t]*(?P<denominator>\([A-Za-z0-9_φ.+* /-]{{2,50}}\))"
    rf"[ \t]*)(?=\r?\n|$)")
WRAPPED_OPERATOR = re.compile(
    rf"(?m)^(?P<block>(?P<lhs>{SYMBOL})[ \t]*=[ \t]*(?P<base>{SYMBOL})[ \t]*\r?\n"
    rf"[ \t]*(?P<operator>[+\-*/])[ \t]*(?P<other>{SYMBOL}|\d+(?:\.\d+)?)[ \t]*)"
    rf"(?=\r?\n|$)")
IMPLICIT_PRODUCT = re.compile(rf"(?<!\w)({SYMBOL})[ \t]+({SYMBOL})(?!\w)")
IMPLICIT_PAREN = re.compile(rf"({SYMBOL})[ \t]+(?=\()")
SUBSCRIPT_TRANSLATION = str.maketrans({"φ": "phi", "ₓ": "x", "ₒ": "o", "ₐ": "a",
                                       "₀": "0", "₁": "1", "₂": "2", "₃": "3", "₄": "4",
                                       "₅": "5", "₆": "6", "₇": "7", "₈": "8", "₉": "9"})


@dataclass(frozen=True)
class LayoutNormalizationResult:
    raw_span: str
    normalized_expression: str | None
    transformations: tuple[str, ...] = ()
    symbols: tuple[str, ...] = ()
    is_ambiguous: bool = False
    rejected_candidates: tuple[str, ...] = ()
    candidate_count: int = 0
    reason: str | None = None


def _product(value: str) -> str:
    return "*".join(value.translate(SUBSCRIPT_TRANSLATION).split())


def _defined_symbols(context: str) -> set[str]:
    defined = {match.group(1).casefold() for match in re.finditer(
        rf"\b({SYMBOL})\b\s+(?:is|denotes|means|represents)\b", context, re.I)}
    defined.update(match.group(1).casefold() for match in re.finditer(
        rf"\b({SYMBOL})\b\s*\((?:dimensionless|[A-Za-z%/^-]+)\)", context, re.I))
    return defined


def _candidate_units(candidate: str, known_units: dict[str, str]) -> bool | None:
    if not known_units:
        return None
    try:
        lhs, rhs = (part.strip() for part in candidate.split("=", 1))
        names = {node.id for node in ast.walk(ast.parse(rhs, mode="eval")) if isinstance(node, ast.Name)}
        if lhs not in known_units or not names.issubset(known_units):
            return None
        output = formula_output_unit(ast.parse(rhs, mode="eval").body, known_units)
        return unit_factors(output) == unit_factors(known_units[lhs])
    except (SyntaxError, ValueError, KeyError):
        return False


def _source_units(context: str) -> dict[str, str]:
    units = {}
    for match in re.finditer(rf"\b({SYMBOL})\s*\((?P<unit>{UNIT})\)", context, re.I):
        try:
            unit_factors(match["unit"])
        except ValueError:
            continue
        units[match.group(1).translate(SUBSCRIPT_TRANSLATION)] = match["unit"]
    return units


def _safe_equation(candidate: str) -> bool:
    try:
        left, right = (ast.parse(part.strip(), mode="eval") for part in candidate.split("=", 1))
    except (SyntaxError, ValueError):
        return False
    allowed = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Name, ast.Constant,
               ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.USub, ast.UAdd, ast.Load)
    nodes = [node for tree in (left, right) for node in ast.walk(tree)]
    return len(nodes) <= 40 and all(type(node) in allowed and (
        not isinstance(node, ast.Constant) or type(node.value) in {int, float}) for node in nodes)


def normalize_extracted_equation(raw_span: str, local_context: str,
                                 known_symbols: set[str] | None = None,
                                 known_units: dict[str, str] | None = None) -> LayoutNormalizationResult:
    """Accept only uniquely supported short layouts; preserve raw_span verbatim."""
    if (not raw_span or len(raw_span) > 160 or len(local_context) > 1600
            or raw_span not in local_context or raw_span.count("=") != 1):
        return LayoutNormalizationResult(raw_span, None, reason="not_source_anchored_equation")
    raw = raw_span.strip()
    context = local_context.replace(raw_span, " ", 1)
    definitions = _defined_symbols(context)
    known = {item.casefold() for item in (known_symbols or set())} | definitions
    cue = bool(re.search(r"\b(?:equation|formula|relation|where|denominator|fraction|quotient)\b", context, re.I))
    units = known_units or _source_units(context)

    if match := WRAPPED_OPERATOR_FRACTION.fullmatch(raw):
        if not re.search(r"\b(?:divided\s+by|denominator|fraction|quotient)\b", context, re.I):
            return LayoutNormalizationResult(raw_span, None, reason="fraction_relation_not_sourced")
        candidate = (f"{match['lhs']} = {match['base']} {match['operator']} "
                     f"{match['numerator']}/{match['denominator']}")
        if _safe_equation(candidate):
            return LayoutNormalizationResult(raw_span, candidate,
                                             ("wrapped_operator", "wrapped_fraction"), candidate_count=1)
        return LayoutNormalizationResult(raw_span, None, reason="formula_layout_ambiguous")

    if match := WRAPPED_OPERATOR.fullmatch(raw):
        if not cue:
            return LayoutNormalizationResult(raw_span, None, reason="continuation_not_sourced")
        candidate = f"{match['lhs']} = {match['base']} {match['operator']} {match['other']}"
        if _safe_equation(candidate):
            return LayoutNormalizationResult(raw_span, candidate,
                                             ("wrapped_operator",), candidate_count=1)
        return LayoutNormalizationResult(raw_span, None, reason="formula_layout_ambiguous")

    if match := WRAPPED_ADD_FRACTION.fullmatch(raw):
        # The source must explicitly describe the pressure/fraction operation;
        # a line break alone is not permission to attach an unrelated row.
        if not re.search(r"\b(?:divided\s+by|denominator|fraction|quotient)\b", context, re.I):
            return LayoutNormalizationResult(raw_span, None, reason="fraction_relation_not_sourced")
        denominator = re.sub(r"(?<=\d)\s*[x×]\s*(?=[A-Za-zφ])", "*", match["denominator"])
        denominator = denominator.translate(SUBSCRIPT_TRANSLATION)
        candidate = f"{match['lhs']} = {match['base']} {match['operator']} " \
                    f"{match['numerator']}/({denominator})"
        source_units = _source_units(context)
        if (not _safe_equation(candidate) or
                (source_units.get(match["lhs"]) and source_units.get(match["base"]) and
                 unit_factors(source_units[match["lhs"]]) != unit_factors(source_units[match["base"]]))):
            return LayoutNormalizationResult(raw_span, None, reason="fraction_layout_or_units_invalid")
        return LayoutNormalizationResult(raw_span, candidate, ("wrapped_fraction",),
                                         tuple(sorted({match["lhs"], match["base"], match["numerator"]})),
                                         candidate_count=1)

    # PDF extraction often prints a literal multiplication sign as a spaced
    # letter x. Interpret only a bounded numeric-coefficient product chain;
    # leave equations with a genuine variable x untouched.
    coefficient_product = re.fullmatch(
        rf"\s*({SYMBOL})\s*=\s*(\d+(?:\.\d+)?(?:[ \t]+x[ \t]+{SYMBOL}){{1,6}})\s*",
        raw, re.I)
    if coefficient_product:
        candidate = f"{coefficient_product[1].translate(SUBSCRIPT_TRANSLATION)} = " + re.sub(
            r"[ \t]+x[ \t]+", "*", coefficient_product[2].translate(SUBSCRIPT_TRANSLATION), flags=re.I)
        if _safe_equation(candidate):
            return LayoutNormalizationResult(raw_span, candidate,
                                             ("spaced_multiplication_x",), candidate_count=1)

    if match := STACKED_POWER_FRACTION.fullmatch(raw):
        base, power = match["base"].translate(SUBSCRIPT_TRANSLATION), match["power"].translate(SUBSCRIPT_TRANSLATION)
        numerator, denominator = _product(match["numerator"]), _product(match["denominator"])
        symbols = set(re.findall(SYMBOL, f"{base} {power} {numerator} {denominator}"))
        candidate = f"{base}**{power} = ({numerator})/" + (
            denominator if "*" not in denominator else f"({denominator})")
        if re.search(rf"\b{re.escape(base)}\s*(?:\*\*|\^)\s*{re.escape(power)}\s*=", context, re.I):
            return LayoutNormalizationResult(raw_span, None, symbols=tuple(sorted(symbols)),
                                             reason="conflicting_literal_equation")
        if _safe_equation(candidate) and cue and len({item.casefold() for item in symbols} & known) >= 2 and (
                power.isdigit() or power.casefold() in known or
                len({item.casefold() for item in symbols} & definitions) >= 3):
            return LayoutNormalizationResult(raw_span, candidate, ("stacked_exponent", "stacked_fraction",
                                             "implicit_multiplication"), tuple(sorted(symbols)), candidate_count=1)
        return LayoutNormalizationResult(raw_span, None, symbols=tuple(sorted(symbols)), is_ambiguous=True,
                                         candidate_count=2, reason="formula_layout_ambiguous")

    if match := STACKED_FRACTION.fullmatch(raw):
        lhs, numerator, denominator = (match[key].translate(SUBSCRIPT_TRANSLATION)
                                       for key in ("lhs", "numerator", "denominator"))
        if re.search(rf"\b{re.escape(lhs)}\s*=", context, re.I):
            return LayoutNormalizationResult(raw_span, None, reason="conflicting_literal_equation")
        divided = f"{lhs} = ({_product(numerator)})/({_product(denominator)})"
        multiplied = f"{lhs} = ({_product(numerator)})*({_product(denominator)})"
        symbols = set(re.findall(SYMBOL, f"{lhs} {numerator} {denominator}"))
        by_units = (_candidate_units(divided, units), _candidate_units(multiplied, units))
        explicit_fraction = bool(re.search(r"\b(?:fraction|denominator|quotient|divided)\b", context, re.I))
        contextual = (cue and len({item.casefold() for item in symbols} & known) >= 2 and
                      any(word.casefold() in known for word in denominator.split()))
        if _safe_equation(divided) and (
                by_units == (True, False)
                or (by_units in {(None, None), (True, None), (None, False)} and contextual)
                or (by_units == (True, True) and explicit_fraction)):
            return LayoutNormalizationResult(raw_span, divided,
                ("stacked_fraction", "implicit_multiplication"), tuple(sorted(symbols)),
                rejected_candidates=(multiplied,), candidate_count=2)
        return LayoutNormalizationResult(raw_span, None, symbols=tuple(sorted(symbols)),
                                         is_ambiguous=True, rejected_candidates=(divided, multiplied),
                                         candidate_count=2, reason="formula_layout_ambiguous")

    if match := STACKED_POWER.fullmatch(raw):
        base, power, rhs = (match[key].translate(SUBSCRIPT_TRANSLATION)
                            for key in ("base", "power", "rhs"))
        candidate = f"{base}**{power} = {rhs}"
        if _safe_equation(candidate) and cue and base.casefold() in known and (
                power.isdigit() or power.casefold() in known):
            return LayoutNormalizationResult(raw_span, candidate, ("stacked_exponent",),
                                             tuple(sorted({base, power, rhs})), candidate_count=1)
        return LayoutNormalizationResult(raw_span, None, is_ambiguous=True, candidate_count=2,
                                         reason="formula_layout_ambiguous")

    if "\n" not in raw and re.fullmatch(rf"{SYMBOL}\s*=\s*[A-Za-z0-9_φ₀-₉ₓₒₐ+\-*/(). \t]+", raw):
        lhs, rhs = (part.strip().translate(SUBSCRIPT_TRANSLATION) for part in raw.split("=", 1))
        if IMPLICIT_PRODUCT.search(rhs) or IMPLICIT_PAREN.search(rhs):
            symbols = set(re.findall(SYMBOL, rhs))
            if not cue or not {item.casefold() for item in symbols}.issubset(known):
                return LayoutNormalizationResult(raw_span, None, is_ambiguous=True, candidate_count=1,
                                                 reason="formula_layout_ambiguous")
            normalized = IMPLICIT_PRODUCT.sub(r"\1*\2", rhs)
            normalized = re.sub(rf"({SYMBOL})\s+(?=\()", r"\1*", normalized)
            candidate = f"{lhs} = {normalized}"
            if _safe_equation(candidate):
                return LayoutNormalizationResult(raw_span, candidate,
                                                 ("implicit_multiplication",), tuple(sorted(symbols)), candidate_count=1)
    return LayoutNormalizationResult(raw_span, None, reason="no_supported_layout")


def isolate_equation(source_equation: str, target: str) -> str | None:
    """Invert one occurrence through +, -, *, /; never invert powers."""
    try:
        left, right = (ast.parse(part.strip(), mode="eval").body
                       for part in source_equation.split("=", 1))
    except (SyntaxError, ValueError):
        return None
    if sum(isinstance(node, ast.Name) and node.id == target for node in ast.walk(right)) != 1:
        return None
    if any(isinstance(node, ast.Name) and node.id == target for node in ast.walk(left)):
        return None
    if sum(1 for node in ast.walk(right)) > 30:
        return None
    if not _safe_equation(source_equation):
        return None

    def contains(node: ast.AST) -> bool:
        return any(isinstance(part, ast.Name) and part.id == target for part in ast.walk(node))

    current, opposite = right, ast.unparse(left)
    while not isinstance(current, ast.Name):
        if not isinstance(current, ast.BinOp) or isinstance(current.op, ast.Pow):
            return None
        left_has, right_has = contains(current.left), contains(current.right)
        if left_has == right_has:
            return None
        other = ast.unparse(current.right if left_has else current.left)
        if isinstance(current.op, ast.Add):
            opposite = f"({opposite})-({other})"
        elif isinstance(current.op, ast.Sub):
            opposite = f"({opposite})+({other})" if left_has else f"({other})-({opposite})"
        elif isinstance(current.op, ast.Mult):
            opposite = f"({opposite})/({other})"
        elif isinstance(current.op, ast.Div):
            opposite = f"({opposite})*({other})" if left_has else f"({other})/({opposite})"
        else:
            return None
        current = current.left if left_has else current.right
    return f"{target} = {opposite}" if current.id == target else None
