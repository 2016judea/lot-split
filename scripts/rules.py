"""The lot-dimension rules this product checks, copied from the Minneapolis Code of
Ordinances, Title 20 Zoning Code, Chapter 540 Built Form Overlay Districts, section
540.720 (read 2026-10-19 from the code as published; the city's Built Form Overlay
District Handbook of 2023-10-10, docs/built-form-handbook-2023-10-10.md, prints the same
numbers). The brief named Chapter 546; the chapter is 540.

Table 540-15, "Single-, two- or three-family dwelling", Urban Neighborhood and
Residential Mixed-Use primary districts: minimum lot area 5,000 sq ft, minimum lot width
40 ft, maximum lot area 8,999 sq ft. Footnote 1: in Interior 1 and Interior 2, where the
average lot area of the 1-3 unit zoning lots in whole or in part within 350 feet is 9,000
sq ft or more, that average is the minimum per principal structure and 130% of it is the
maximum (also 598.240).

Table 540-16, minimum lot dimensions for dwellings of four or more units, by built form
district. Table 540-17, maximum lot area by built form district. Table 540-7 heights for
1-3 unit dwellings (from the handbook's per-district pages).

Eligibility here is a rule check on public dimensions. It is not a plat approval, a
survey or a legal opinion; the city's subdivision review (Chapter 598) decides.
"""

MIN_AREA_1_3 = 5000      # sq ft, UN and RM districts
MIN_WIDTH_1_3 = 40       # ft
MAX_AREA_1_3 = 8999      # sq ft
NEIGHBOUR_FT = 350       # the footnote-1 radius
NEIGHBOUR_TRIGGER = 9000 # average lot area at or above which the footnote applies
NEIGHBOUR_MAX_PCT = 1.30

# Table 540-16: (min area sq ft, min width ft) for 4+ unit dwellings
FOURPLUS = {
    "Interior 1": (9000, 50),
    "Interior 2": (7500, 50),
}
FOURPLUS_DEFAULT = (5000, 40)

# Table 540-17: maximum lot area by district (None = no maximum)
MAX_AREA_DISTRICT = {
    "Interior 1": 14000, "Interior 2": 14000, "Interior 3": 18000,
    "Corridor 3": 28000, "Corridor 4": 28000, "Corridor 6": 43560,
}

# Height for new 1-3 unit homes, from the handbook's district pages (Table 540-7 et seq.)
HEIGHT_1_3 = {
    "Interior 1": "2.5 stories, 28 ft", "Interior 2": "2.5 stories, 28 ft", "Interior 3": "3 stories, 42 ft",
    "Corridor 3": "3 stories", "Corridor 4": "4 stories", "Corridor 6": "6 stories",
    "Transit 10": "10 stories", "Transit 15": "15 stories", "Transit 20": "20 stories",
    "Transit 30A": "30 stories", "Transit 30B": "30 stories", "Core 50": "50 stories",
    "Production": "varies", "Parks": "varies",
}

# Primary zoning districts that carry the 40 ft / 5,000 sq ft row (UN and RM)
RESIDENTIAL_ZONING_PREFIXES = ("Urban Neighborhood", "Residential Mixed Use", "Residential Mixed-Use", "UN", "RM")


def is_residential_zoning(z):
    z = (z or "").strip()
    return z.startswith(RESIDENTIAL_ZONING_PREFIXES)


def minimums(district, avg_lot_350):
    """(min_area, min_width, max_area, note) for a new 1-3 unit home on one lot."""
    min_area, max_area, note = MIN_AREA_1_3, MAX_AREA_1_3, ""
    if district in ("Interior 1", "Interior 2") and avg_lot_350 and avg_lot_350 >= NEIGHBOUR_TRIGGER:
        min_area = int(round(avg_lot_350))
        max_area = int(round(avg_lot_350 * NEIGHBOUR_MAX_PCT))
        note = f"big-lot block: lots within {NEIGHBOUR_FT} ft average {min_area:,} sq ft, so that is the minimum here"
    return min_area, MIN_WIDTH_1_3, max_area, note


def check(area, street_side, district, zoning, avg_lot_350):
    """The rule check for one lot. Returns a dict the page draws from.

    area        lot area in sq ft (assessor)
    street_side the length of the side a split would run along, in ft (geometry)
    """
    min_area, min_width, max_area, note = minimums(district, avg_lot_350)
    need_area, need_width = 2 * min_area, 2 * min_width
    res_zoning = is_residential_zoning(zoning)
    area_ok = area is not None and area >= need_area
    width_ok = street_side is not None and street_side >= need_width
    close = lambda have, need: have is not None and have < need and have >= 0.9 * need
    fp_area, fp_width = FOURPLUS.get(district, FOURPLUS_DEFAULT)
    return {
        "can_split": bool(res_zoning and area_ok and width_ok),
        "area_ok": bool(area_ok), "width_ok": bool(width_ok),
        "area_close": bool(close(area, need_area)), "width_close": bool(close(street_side, need_width)),
        "need_area": need_area, "need_width": need_width,
        "min_area": min_area, "min_width": min_width, "max_area": max_area, "rule_note": note,
        "residential_zoning": res_zoning,
        "meets_4plus_dims": bool(area is not None and street_side is not None and area >= fp_area and street_side >= fp_width),
        "too_big_for_1_3": bool(res_zoning and area is not None and area > max_area),
        "height_1_3": HEIGHT_1_3.get(district, ""),
    }
