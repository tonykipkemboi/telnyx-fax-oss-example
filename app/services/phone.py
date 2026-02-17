import re


class PhoneValidationError(ValueError):
    pass


def normalize_us_fax_number(raw: str) -> str:
    digits = re.sub(r"\D", "", raw.strip())

    if len(digits) == 10:
        return f"+1{digits}"

    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"

    raise PhoneValidationError("Invalid US fax number. Use a 10-digit US number.")
