"""Money helpers. All prices inside the app are integer cents; Decimal is used for parsing, never float."""
from decimal import Decimal, InvalidOperation


def to_cents(value) -> int:
    """Convert a dollar amount such as "12.34" or 12.34 to 1234. Raises ValueError if not whole cents."""
    try:
        # str() first, so a float like 19.99 is read as written instead of its binary approximation.
        cents = Decimal(str(value)) * 100
    except InvalidOperation as e:
        raise ValueError(f"not a number: {value!r}") from e
    if not cents.is_finite() or cents != cents.to_integral_value():
        raise ValueError(f"not a whole number of cents: {value!r}")
    return int(cents)


def to_dollars(cents: int) -> str:
    """Format 1234 as "12.34", the string form PayPal expects."""
    return f"{cents // 100}.{cents % 100:02d}"
