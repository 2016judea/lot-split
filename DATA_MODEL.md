# Data model: the ideal record for one Minneapolis lot

Written 2026-10-18 from the need alone, before the data was pulled
(`~/.claude/BUSINESS.md` rule 5). The need: *an owner of a Minneapolis house
wants to know whether their lot can be split into two, or hold more homes,
under the city's built-form rules, and a small builder wants the list of every
lot that can.* The step taken over is the rule check and the search for lots
that pass it, which today means reading a zoning map and a parcel map by hand.

Eligibility here is a rule check on public dimensions against the published
minimums. It is not a survey, a legal opinion or a plat approval. Said once on
the page, not as a banner.

The reality check against this model is at the bottom.

## Entities

```
Lot ──N:1── BuiltFormDistrict (overlay polygon)  → the minimums
 │  ──N:1── PrimaryZoningDistrict (UN1/UN2/UN3/RM..)
 │  ──1:1── Assessment (current year)
 │  ──1:N── RecordedSale
 │  ──1:N── StreetFrontage (one per public street it touches)
 └── Eligibility (computed, one per lot; the product)
```

## Lot — *what is it, physically?*

| field | question it answers |
|---|---|
| pin | which parcel (the join key to every county and city record) |
| address, zip, neighborhood | where; what the owner types in |
| area_sqft | how big is the lot (the first deciding number) |
| width_ft | how wide at the street (the second deciding number) |
| depth_ft | how deep (a split along the depth needs a second street) |
| frontage streets | which streets it fronts; a corner lot has two ways to split |
| shape regularity | is it a rectangle, or an odd shape that may not divide cleanly |
| geometry | the polygon, for the drawing on the page |
| units_now, building_use | 1 or 2 homes today; the market this product is for |
| year_built, finished_sqft | what sits on it, and where on the lot (a house in the middle blocks a split) |
| building footprint position | does the existing house leave one half of the lot clear |

## BuiltFormDistrict — *what are the rules here?*

| field | question |
|---|---|
| district (Interior 1/2/3, Corridor 3/4/6, Transit 10/15/20/30, Core, Production, Parks) | which row of the built-form table applies |
| min_lot_area_1_3_units, min_lot_width_1_3_units | the split test for 1–3 unit homes |
| min_lot_area_4plus, min_lot_width_4plus | could the lot hold a fourplex or more |
| max_lot_area_1_3_units | is the lot too big to be rebuilt as 1–3 units at all |
| max_height_stories | what can go up on a new lot |
| code section and date | where the number comes from, so a reader can check it |
| layer edit date | how fresh the city's map is |

## PrimaryZoningDistrict

| field | question |
|---|---|
| zoning (UN1, UN2, UN3, RM1.., CM.., PR..) | is this residential ground at all; UN and RM carry the 40 ft / 5,000 sq ft row |

## Assessment — *who owns it and what is it worth?*

| field | question |
|---|---|
| owner_name, taxpayer | who to write to (builder's question) |
| owner_type (homestead / not) | is the owner living there, or is it an investor |
| emv_land, emv_building, emv_total | what the county thinks the dirt is worth vs the house |
| land value per sqft of lot | is the second lot worth more than the house on it |
| split_land_value, split_uplift | what the two lots would carry in county land value after a split, and how much more than the one lot today |

## RecordedSale — *what does the market pay for these?*

| field | question |
|---|---|
| sale_date, sale_price | when it last traded and for what |
| sales this month among qualifying lots | the free slice's live number: is this market moving |
| median price of qualifying lots sold, last 12 months | what a builder should expect to pay |

## Eligibility — *the answer*

| field | question |
|---|---|
| can_split | area ≥ 2 × minimum AND width ≥ 2 × minimum width |
| split_area_margin_sqft, split_width_margin_ft | how far over or under each line |
| can_hold_4plus | area and width ≥ the district's 4+ minimums |
| too_big_for_1_3 | over the 1–3 unit maximum lot area |
| qualifies_by | which street side the split would run along (corner lots) |
| status colour | one colour per role: passes / fails / close (within 10%) |

## Reality check (2026-10-18, after the pull)

| field | source | result |
|---|---|---|
| pin, address, area_sqft, zoning, owner, homestead, values, units, year built | City of Minneapolis Assessing Department Parcel Data 2026 (ArcGIS, edited 2026-08-10, 132,079 rows) | **filled** |
| built form district | City of Minneapolis `Planning_Zoning_Built_Form` (ArcGIS, edited 2026-10-16, 791 polygons) spatially joined to parcel centroid | **filled** |
| minimums per district | Minneapolis Code of Ordinances, Title 20 Zoning Code, Chapter 546 Built Form Overlay Districts, lot dimension tables for BFI1/BFI2/BFI3 et al (see `docs/`) | **filled**, see `scripts/rules.py` |
| width_ft | Hennepin County parcel polygons (bricks `hennepin_gis.duckdb`): longest public-street frontage edge; fallback short side of the minimum rotated rectangle | **filled from geometry**, not a surveyed figure: a plat width can differ by a foot or two |
| depth_ft, shape regularity | geometry | filled |
| building footprint position | no public footprint layer joined to parcels in hand | **not filled**; a split that needs the house moved is shown as a split; the builder reads the aerial |
| geometry drawing | parcel polygon | filled (free page draws the lot and the split line) |
| sales | Hennepin recorded sales in bricks `closed_system.duckdb` `sale` + assessor sale fields | filled; the monthly count is the month with complete data, named on the page |
| max height, 4+ minimums | Chapter 546 | filled per district |

What could not be filled is the position of the existing house on the lot. The
page says so where it matters (a split may cross the house).

## Reality check, second pass (2026-10-19)

- **Built-form district: now filled for every lot.** The first pass read each Esri polygon's
  first ring as the shell and every other ring as a hole; 84 of 791 districts are multipart,
  so 1,070 lots fell in false holes and had no district. Rings are now split by orientation
  (`build.esri_polygon`). Qualifying went 1,474 to 1,431.
- **Sales: now current.** bricks' `sale` table stops 2026-07-01. Hennepin's live parcel layer
  carries each parcel's last recorded sale (month grain) through September 2026, pulled into a
  dated folder; the paid list merges newer sales live on every unlock. Deeds land weeks late,
  so the free page counts the latest month the county has fully recorded (July 2026), not the
  calendar month.
- **Still not filled:** the position of the house on the lot. A lot that passes may need the
  house moved; the page says so under every passing lot.

## What the split is worth (2026-10-20)

`split_land_value = emv_land × 2^(1−β)`, `split_uplift = split_land_value − emv_land`,
rounded to $1,000, on every lot that passes. In the free check and in the paid CSV.

- **β is fitted in `scripts/build.py` (`fit_land_curve`), never typed.** OLS of log county land
  value on log lot area, both demeaned within ZIP, over 1-3 unit homes whose area lies between
  half the 5th-percentile passing lot and the 95th-percentile passing lot: the sizes a split moves
  between. Build of 2026-10-20: **β = 0.686, n = 61,995, lots 5,062 to 22,670 sq ft**, so
  2^(1−β) = 1.243. Two halves split by sha256(pin): 0.694 / 0.677; the build fails if they
  differ by more than 0.03. (Halves by md5(pin) came out 0.704 / 0.668, a 0.036 gap; sha1
  0.680 / 0.692. The hash is fixed at sha256 and stated here so the check is not re-chosen.)
- Median passing lot: $249,300 of land value, about +$61,000 on a split.
- Grounded in the axioms ledger law L6′ (`~/.claude/skills/axioms/LEDGER.md`): β 0.71 on
  county.duckdb dwellings of 8,000–30,000 sq ft.
- **It is the county's land value, not a price.** A probe on recorded vacant-lot sales in
  Minneapolis was far more concave (β ≈ 0.17, n = 105), which would make a split worth much
  less on the market. Too small and noisy to publish; it is not on the page.
