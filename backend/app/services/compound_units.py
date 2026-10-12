"""Bounded literal unit algebra; no scale conversions or guessed dimensions."""
import re


ATOM = (r"(?:dimensionless|MMscf|seconds?|minutes?|hours?|days?|acres?|"
        r"psia|psig|psi|kPa|Pa|ohm-m|stb|bbl|lbf|lbmol|lb|kg|mg|g|kmol|mol|USD|EUR|\$|"
        r"kWh|kW|kJ|hp|ppg|gpm|cP|mD|md|ft|feet|inch|in|mm|km|cm|"
        r"m|L|hr|min|secs?|h|d|s|°C|달러|시간|분|%)"
        r"(?:[23²³]|⁻¹)?")
POWER = r"(?:\^[+-]?[0-8])?"
# Two parenthesis levels, at most eight factors per level; full parser caps total work.
UNIT = ATOM + POWER
for _ in range(2):
    UNIT = rf"(?:{ATOM}|\({UNIT}(?:[*/·]{UNIT}){{0,7}}\)){POWER}"
UNIT = rf"(?:{UNIT}(?:[*/·]{UNIT}){{0,7}})(?![A-Za-z0-9_/*^·²³⁻])"


def unit_factors(text: str) -> dict[str, int]:
    if not text or text in {"1", "dimensionless"}:
        return {}
    if len(text) > 96 or text.count("(") > 4:
        raise ValueError("unit complexity limit")
    text = text.replace("·", "*").replace("³", "3").replace("²", "2").replace("⁻¹", "^-1")
    tokens = re.findall(r"ohm-m|\^|[*/()]|[+-]?\d+|[^\W\d]\w*|[%°$]+[A-Za-z]*", text)
    if len(tokens) > 32:
        raise ValueError("unit expansion exceeds safe bounds")
    if "".join(tokens) != text:
        raise ValueError("invalid unit expression")
    index = 0

    def expression(depth=0):
        nonlocal index
        if depth > 2:
            raise ValueError("unit nesting limit")
        result = {}
        sign = 1
        while index < len(tokens):
            token = tokens[index]
            index += 1
            if token == "(":
                value = expression(depth + 1)
                if index >= len(tokens) or tokens[index] != ")":
                    raise ValueError("unclosed unit")
                index += 1
            elif re.fullmatch(ATOM, token, re.I) or token == "1":
                value = {} if token in {"1", "dimensionless"} else {token: 1}
            else:
                raise ValueError("invalid unit atom")
            exponent = 1
            if index < len(tokens) and tokens[index] == "^":
                index += 1
                if index >= len(tokens) or not re.fullmatch(r"[+-]?[0-8]", tokens[index]):
                    raise ValueError("invalid unit exponent")
                exponent = int(tokens[index])
                index += 1
            for atom, power in value.items():
                result[atom] = result.get(atom, 0) + sign * exponent * power
            if index == len(tokens) or tokens[index] == ")":
                break
            if tokens[index] not in {"*", "/"}:
                raise ValueError("invalid unit operator")
            sign = -1 if tokens[index] == "/" else 1
            index += 1
            if index == len(tokens):
                raise ValueError("incomplete unit")
        if sum(abs(power) for power in result.values()) > 64:
            raise ValueError("unit expansion limit")
        return {atom: power for atom, power in result.items() if power}

    result = expression()
    if index != len(tokens):
        raise ValueError("unexpected unit suffix")
    return result


def combine_units(left: str, right: str, *, divide: bool) -> str:
    factors = unit_factors(left)
    for atom, power in unit_factors(right).items():
        factors[atom] = factors.get(atom, 0) + (-power if divide else power)
    if sum(abs(power) for power in factors.values()) > 64:
        raise ValueError("unit expansion limit")
    top = [atom for atom, power in sorted(factors.items()) for _ in range(max(0, power))]
    bottom = [atom for atom, power in sorted(factors.items()) for _ in range(max(0, -power))]
    return ("*".join(top) or ("1" if bottom else "")) + ("/" + "/".join(bottom) if bottom else "")


def format_unit_factors(factors: dict[str, int]) -> str:
    """Render the bounded factor map without losing denominator grouping."""
    def term(atom: str, power: int) -> str:
        return atom if power == 1 else f"{atom}^{power}"

    top = [term(atom, power) for atom, power in factors.items() if power > 0]
    bottom = [term(atom, -power) for atom, power in factors.items() if power < 0]
    return ("*".join(top) or ("1" if bottom else "")) + (
        "/" + "/".join(bottom) if bottom else "")
