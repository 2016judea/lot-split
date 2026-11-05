# Lot Split

**Live:** https://lot-split.vercel.app

Can a Minneapolis lot be split in two? Type an address and the page answers with the
lot's area and street side against the city's minimums, and draws where the new line
would run. The city's built-form rules (Minneapolis Code, Title 20, Chapter 540, Table
540-15, read 2026-10-19) let a 1-3 unit lot on Urban Neighborhood ground be divided when
each new lot has at least 5,000 sq ft and 40 ft of street. We ran that check on all
81,257 1-3 unit and residential vacant lots in the city: **1,431 pass**.

This is a rule check on public dimensions, not a survey, a plat approval or legal advice.
The city's subdivision review (Chapter 598) decides.

## What is free, what is paid

- **Free:** any address in the city (the verdict, lot area and street side against the
  district's minimum, the built-form district, the big-lot footnote when it applies),
  what the split is worth in county land value (below), ten passing lots to look at, and the market numbers: passing lots sold in the latest
  month the county has fully recorded, and over the last 12 months.
- **Paid ($150, once):** the full list of every passing lot with owner, owner-occupied or
  not, county land and total value, the split's county land value and uplift, last recorded sale, year built and the 4+ unit test,
  as a CSV. Each unlock merges in the sales Hennepin County has recorded since the build,
  read live from its parcel layer (`site/api/data.js`).

## What the split is worth

Within a ZIP, Minneapolis county land value grows slower than lot size:
`log(land) = a_zip + β·log(area)`. Two half-lots on the same curve carry `2^(1−β)` of the one
lot's land value. The build fits β from the assessor table every run (2026-10-20: **β 0.686,
n 61,995** homes of 5,062–22,670 sq ft, hash halves 0.694 / 0.677), so a split adds about 24%:
`split_land_value` and `split_uplift` on every passing lot. County land value, not a sale price.
See `DATA_MODEL.md`.

## Price

$150, once. **A hypothesis**, set 2026-10-19. One use = one small builder or designer
finding one lot worth a letter. Doing that by hand means reading the built-form map, the
parcel map and the assessor table lot by lot: about 15 hours at $100 an hour, $1,500.
A tenth of that is $150. A lot that does split is worth far more (the median passing lot
carries $249,300 of county land value), so the price is set on the
search it saves, not on the lot.

## Data

| source | what it gives | as of |
|---|---|---|
| City of Minneapolis `Planning_Zoning_Built_Form` (ArcGIS) | the built-form district of each lot | edited 2026-10-16 |
| City of Minneapolis Assessing Department Parcel Data 2026 | area, zoning, use, owner, values | 2026 |
| Hennepin County parcel polygons (bricks `hennepin_gis.duckdb`) | street side, depth, corner | |
| Hennepin County parcel layer, live (`HennepinData/LAND_PROPERTY/MapServer/1`) | last recorded sale per parcel | through September 2026 |
| bricks `closed_system.duckdb` `sale` | sale history to 2026-07 | |

Every number on the page comes out of `scripts/build.py`. See `DATA_MODEL.md` for the
ideal model and what could not be filled (where the house sits on the lot).

## Run it

    uv sync
    .venv/bin/python scripts/pull.py           # the city layers + county sales, cached under data/cache/
    .venv/bin/python scripts/pull.py sales     # refresh only the county sales (a dated folder)
    .venv/bin/python scripts/build.py          # join, rule check, private/bundle + site/public/data
    .venv/bin/python scripts/build_site.py     # site/public/index.html and /for/ pages
    .venv/bin/python -m pytest -q | tee tests/last_run.log
    node scripts/dev_server.js 48713           # local, with the API
    VERCEL_TOKEN=... .venv/bin/python scripts/deploy.py

Only `site/public/` is served. The paid bundle goes up sealed (AES-256-GCM, a fresh
`BUNDLE_KEY` per deploy, `scripts/seal.py`) and only `/api/data` opens it.
Comp password: `scripts/issue_password.py "comp:<who>"`. Lost password: `scripts/fulfil.py <cs_live_...>`.
Stripe webhook: routed through `~/Desktop/workspace/stripe-router` (registered 2026-10-19).

## Distribution

Round 1 is drafted, not sent: `scripts/candidates.py` writes `outreach/round1/ledger.csv`
and `drafts/` (gitignored). Four segments: infill builders (3+ new-house permits since
2022, or a design-build firm on a 1-3 unit lot), ADU builders (ADU permits), designers and
architects, and residential agents. Each opens on a lot of their own: their newest permit's
lot, or the lot their published business address sits on. Agents already written to on
10/13 are held as a second touch with no lot of their own.

**A/B test, one variable, pooled across the seven shelf products:** variant A states the
price in the email; variant B leaves it to the page. Assigned alternately within each
segment; the `/for/<token>/` page fires `preview_open` with the variant, never in the URL.
**Hypothesis:** stating the price in the email lowers clicks but raises paid-per-click.
Read at day 3: visits, checkout_open, paid and replies by variant.

MIT licence for the code. The data is public record from the City of Minneapolis and
Hennepin County.
