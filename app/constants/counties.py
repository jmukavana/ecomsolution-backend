"""The 47 counties of Kenya (alphabetical)."""

KENYAN_COUNTIES: tuple[str, ...] = (
    "Baringo", "Bomet", "Bungoma", "Busia", "Elgeyo-Marakwet", "Embu",
    "Garissa", "Homa Bay", "Isiolo", "Kajiado", "Kakamega", "Kericho",
    "Kiambu", "Kilifi", "Kirinyaga", "Kisii", "Kisumu", "Kitui", "Kwale",
    "Laikipia", "Lamu", "Machakos", "Makueni", "Mandera", "Marsabit",
    "Meru", "Migori", "Mombasa", "Murang'a", "Nairobi", "Nakuru",
    "Nandi", "Narok", "Nyamira", "Nyandarua", "Nyeri", "Samburu",
    "Siaya", "Taita-Taveta", "Tana River", "Tharaka-Nithi",
    "Trans-Nzoia", "Turkana", "Uasin Gishu", "Vihiga", "Wajir",
    "West Pokot",
)
COUNTY_SET = frozenset(KENYAN_COUNTIES)


def is_valid_county(name: str) -> bool:
    return name in COUNTY_SET


def normalise_phone_ke(phone: str) -> str:
    """Normalise to E.164 +254XXXXXXXXX. Accepts 0XXX, 254XXX, +254XXX."""
    raw = phone.strip().replace(" ", "").replace("-", "")
    if raw.startswith("+254"):
        digits = raw[1:]
    elif raw.startswith("254"):
        digits = raw
    elif raw.startswith("0") and len(raw) == 10:
        digits = "254" + raw[1:]
    elif raw.startswith("7") and len(raw) == 9:
        digits = "254" + raw
    else:
        raise ValueError("invalid Kenyan phone number")
    if not digits.isdigit() or len(digits) != 12:
        raise ValueError("invalid Kenyan phone number")
    return "+" + digits
