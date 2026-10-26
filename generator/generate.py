"""Course dataset generator: a fictional Australian wholesale distributor's sales, as raw CSVs.

Writes two files to data/ (or --out):
  order_lines.csv    one row per order line, 1 Jan 2024 to 31 Dec 2026, with every name repeated
                     on every line the way a sales system exports it
  sales_targets.csv  one row per category per month: last year's actual for that month plus a
                     planned growth

Seed 2026, deterministic. Every draw is built from random.Random.random(), the one part of the
random module Python promises not to change between versions (random.gauss, choices and the rest
carry no such promise). The run prints each file's SHA-256 so a rebuild can be compared.

How the data behaves (each is something a lesson leans on):
  - 2023 is simulated but not exported: it is the base for 2024's targets.
  - Customers in four segments order on business days, Hospitality on Saturdays too, with
    national public holidays off (no substitute days) and a seasonal shape per segment
    (Education drops in the January, July and December school holidays).
  - 100 customers are won during the span and 40 stop ordering, so Active Customers moves.
  - Prices and costs change every 1 July, the fiscal year start. Coffee & Tea costs jump 14
    percent from 1 July 2025 against a 5 percent price rise, so its margin dips in fiscal 2026.
  - About 10 percent of products launch during the span, so they have no sales before launch.
  - ShipDate is 0 to 4 business days after OrderDate and never later than 31 Dec 2026, so it
    stays inside a 2024-2026 date table.
"""
import argparse
import csv
import hashlib
import math
import random
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# ---------------- knobs ----------------
SEED = 2026
WARMUP = date(2023, 1, 1)        # simulated from here; only FIRST..LAST is exported
FIRST, LAST = date(2024, 1, 1), date(2026, 12, 31)
TARGET_LINES = 50_000            # expected exported lines; the order rate is scaled to hit it
EXTRA_LINES = 2.5                # mean lines per order after the first (Poisson)
MAX_LINES = 12
ORGANIC_GROWTH = 1.04            # an existing customer orders this much more each year
NEW_CUSTOMERS = 100              # first order between FIRST and 90 days before LAST
CHURNED = 40                     # existing customers whose last order falls inside the span
LAUNCHED_SHARE = 0.10            # products first sold inside the span
PLAN_GROWTH = (0.06, 0.12)       # target = last year's actual x (1 + this), per category and year
PRICE_RISE = (0.02, 0.05)        # per category, every 1 July
COST_RISE = (0.02, 0.045)
COFFEE_SQUEEZE = {2026: (0.05, 0.14), 2027: (0.06, 0.03)}  # fiscal year: (price rise, cost rise)

SEGMENTS = {  # customers, order rate against Hospitality, Saturday factor
    "Hospitality": (160, 1.00, 0.35),
    "Retail": (110, 0.80, 0.0),
    "Healthcare": (70, 0.60, 0.0),
    "Education": (60, 0.50, 0.0),
}
SEASON = {  # January to December, southern hemisphere
    "Hospitality": [1.15, 0.95, 1.00, 1.05, 0.90, 0.85, 0.90, 0.90, 1.00, 1.05, 1.15, 1.30],
    "Retail": [0.90, 0.95, 1.00, 1.00, 0.95, 0.95, 0.95, 1.00, 1.00, 1.05, 1.15, 1.40],
    "Healthcare": [0.95, 1.00, 1.00, 1.00, 1.05, 1.10, 1.10, 1.05, 1.00, 0.95, 0.95, 0.90],
    "Education": [0.35, 1.25, 1.10, 0.90, 1.10, 1.05, 0.65, 1.10, 1.05, 0.95, 1.10, 0.40],
}
WEEKDAY = [1.10, 1.05, 1.00, 1.00, 0.85]  # Monday to Friday
STATES = [("NSW", 32), ("VIC", 26), ("QLD", 20), ("WA", 10), ("SA", 7), ("TAS", 2), ("ACT", 2), ("NT", 1)]

CATEGORIES = {  # products, margin band, mean quantity per line
    "Coffee & Tea": (70, (0.30, 0.40), 6),
    "Beverages": (90, (0.22, 0.30), 8),
    "Snacks & Confectionery": (90, (0.28, 0.36), 8),
    "Pantry": (115, (0.20, 0.28), 7),
    "Paper & Packaging": (70, (0.32, 0.42), 5),
    "Cleaning & Hygiene": (70, (0.35, 0.45), 4),
    "Personal Care": (45, (0.38, 0.48), 5),
    "Kitchen Equipment": (50, (0.25, 0.35), 0.4),
}
AFFINITY = {  # how much each segment buys from each category, in CATEGORIES order
    "Hospitality": [3.0, 3.0, 1.5, 2.5, 2.5, 1.5, 0.3, 0.8],
    "Retail": [1.5, 3.0, 3.0, 2.5, 0.8, 1.5, 2.5, 0.3],
    "Healthcare": [1.0, 1.0, 0.8, 1.5, 1.5, 3.0, 3.0, 0.5],
    "Education": [0.8, 1.5, 1.5, 1.5, 2.0, 2.5, 1.0, 0.6],
}
BRANDS = {
    "Harbour Roast": ["Coffee & Tea"],
    "Ember and Oak": ["Coffee & Tea", "Pantry"],
    "Wattle Lane": ["Coffee & Tea", "Pantry"],
    "Bluegum": ["Beverages", "Snacks & Confectionery"],
    "Coastline": ["Beverages"],
    "Little Creek": ["Beverages", "Snacks & Confectionery"],
    "Saltbush": ["Pantry", "Snacks & Confectionery"],
    "Kestrel": ["Paper & Packaging", "Kitchen Equipment"],
    "Northpoint": ["Paper & Packaging", "Cleaning & Hygiene"],
    "Brightside": ["Paper & Packaging", "Cleaning & Hygiene", "Personal Care"],
    "Clearwater": ["Cleaning & Hygiene", "Personal Care"],
    "Ironbark": ["Kitchen Equipment"],
}
ITEMS = {  # category: ([(item, base price in A$ for the first pack)], [(pack, price multiplier)])
    "Coffee & Tea": (
        [("Espresso Beans", 24), ("House Blend Beans", 21), ("Decaf Beans", 26),
         ("Single Origin Beans", 32), ("Ground Coffee", 19), ("Instant Coffee", 16),
         ("English Breakfast Tea", 14), ("Earl Grey Tea", 15), ("Green Tea", 15),
         ("Peppermint Tea", 15), ("Chai Latte Powder", 14), ("Hot Chocolate Powder", 13)],
        [("500g", 1.0), ("1kg", 1.85), ("3kg", 5.2)]),
    "Beverages": (
        [("Sparkling Water", 14), ("Still Water", 11), ("Orange Juice", 26), ("Apple Juice", 24),
         ("Cola", 22), ("Lemonade", 21), ("Ginger Beer", 28), ("Iced Tea", 27), ("Kombucha", 42),
         ("Energy Drink", 38), ("Coconut Water", 40), ("Cold Brew Coffee", 45)],
        [("330ml x 24", 1.0), ("600ml x 24", 1.6), ("1.25L x 12", 1.3)]),
    "Snacks & Confectionery": (
        [("Sea Salt Chips", 22), ("Salt and Vinegar Chips", 22), ("Popcorn", 19), ("Pretzels", 20),
         ("Mixed Nuts", 34), ("Trail Mix", 30), ("Muesli Bars", 24), ("Protein Bars", 42),
         ("Milk Chocolate", 28), ("Dark Chocolate", 31), ("Jelly Lollies", 18),
         ("Shortbread Biscuits", 23), ("Choc Chip Cookies", 23), ("Rice Crackers", 19)],
        [("45g x 24", 1.0), ("150g x 12", 1.15), ("1kg Bulk", 0.9)]),
    "Pantry": (
        [("Basmati Rice", 4.5), ("Jasmine Rice", 4.2), ("Brown Rice", 4.6), ("Penne Pasta", 3.8),
         ("Spaghetti", 3.8), ("Plain Flour", 2.2), ("Caster Sugar", 2.6), ("Raw Sugar", 2.8),
         ("Rolled Oats", 3.4), ("Peanut Butter", 9.5), ("Strawberry Jam", 8.0), ("Honey", 14.0),
         ("Sea Salt", 3.0), ("Tomato Passata", 4.0), ("Diced Tomatoes", 3.6), ("Couscous", 5.2),
         ("Red Lentils", 4.8), ("Chickpeas", 4.4), ("Breadcrumbs", 4.0)],
        [("1kg", 1.0), ("5kg", 4.3), ("20kg", 15.0)]),
    "Paper & Packaging": (
        [("8oz Coffee Cups", 62), ("12oz Coffee Cups", 74), ("Cup Lids", 48), ("Paper Napkins", 38),
         ("Paper Straws", 29), ("Kraft Takeaway Boxes", 66), ("Paper Bags", 41), ("Cling Wrap", 33),
         ("Aluminium Foil", 39), ("Baking Paper", 31), ("Paper Towel Rolls", 44),
         ("Toilet Tissue", 52), ("Sandwich Wedges", 47)],
        [("Carton", 1.0), ("Bulk Carton", 2.8)]),
    "Cleaning & Hygiene": (
        [("Dishwashing Liquid 5L", 18), ("Dishwasher Tablets 100 Pack", 24),
         ("Multi-Surface Spray 750ml", 5.5), ("Glass Cleaner 750ml", 5.0), ("Floor Cleaner 5L", 21),
         ("Disinfectant 5L", 26), ("Bleach 5L", 12), ("Hand Soap 5L", 23),
         ("Hand Sanitiser 500ml", 6.5), ("Nitrile Gloves 100 Pack", 11),
         ("Microfibre Cloths 10 Pack", 14), ("Scourers 10 Pack", 6.0), ("Bin Liners 250 Pack", 32)],
        [("Each", 1.0), ("Case of 6", 5.5)]),
    "Personal Care": (
        [("Shampoo 400ml", 4.5), ("Conditioner 400ml", 4.5), ("Body Wash 1L", 6.5),
         ("Hand Cream 75ml", 3.8), ("Toothpaste 110g", 2.9), ("Toothbrushes 4 Pack", 3.6),
         ("Deodorant 150ml", 3.9), ("Sunscreen SPF50 1L", 18), ("Lip Balm", 1.9),
         ("Facial Tissues 200 Pack", 2.2), ("Cotton Pads 100 Pack", 2.1), ("Wet Wipes 80 Pack", 3.0)],
        [("Each", 1.0), ("Case of 12", 10.8)]),
    "Kitchen Equipment": (
        [("Chef Knife 20cm", 38), ("Cutting Board Large", 24), ("Stainless Saucepan 3L", 46),
         ("Frying Pan 28cm", 52), ("Stock Pot 20L", 118), ("Mixing Bowl Set", 34),
         ("Kitchen Scales", 42), ("Measuring Cups", 12), ("Tongs 30cm", 6), ("Balloon Whisk", 9),
         ("Baking Tray", 18), ("Gastronorm Pan", 29), ("Commercial Blender", 389),
         ("Milk Frothing Jug 600ml", 16), ("Coffee Tamper", 35), ("Digital Thermometer", 22)],
        [("Each", 1.0), ("Pack of 6", 5.4)]),
}
SUPPLIERS = [  # name, country, the category it supplies
    ("Highland Bean Traders", "Vietnam", "Coffee & Tea"),
    ("Monsoon Estates", "India", "Coffee & Tea"),
    ("Southern Roasting Co", "Australia", "Coffee & Tea"),
    ("Tea Garden Imports", "China", "Coffee & Tea"),
    ("Coastal Bottling Pty Ltd", "Australia", "Beverages"),
    ("Fernleaf Beverages", "New Zealand", "Beverages"),
    ("Sunvalley Juices", "Australia", "Beverages"),
    ("Great Lakes Drinks Co", "United States", "Beverages"),
    ("Crunch Foods Pty Ltd", "Australia", "Snacks & Confectionery"),
    ("Golden Grain Snacks", "Australia", "Snacks & Confectionery"),
    ("Kiwi Crisp Ltd", "New Zealand", "Snacks & Confectionery"),
    ("Sweet Harbour Confectionery", "Malaysia", "Snacks & Confectionery"),
    ("Murray Valley Mills", "Australia", "Pantry"),
    ("Olivero Foods", "Italy", "Pantry"),
    ("Ricefield Trading", "Thailand", "Pantry"),
    ("Red Soil Produce", "Australia", "Pantry"),
    ("Paperbark Packaging", "Australia", "Paper & Packaging"),
    ("Eastern Pulp and Paper", "China", "Paper & Packaging"),
    ("Greenfold Packaging", "New Zealand", "Paper & Packaging"),
    ("Huaxin Paper Products", "China", "Paper & Packaging"),
    ("Sparkle Chemicals Pty Ltd", "Australia", "Cleaning & Hygiene"),
    ("Rhein Hygiene GmbH", "Germany", "Cleaning & Hygiene"),
    ("Clearline Industrial", "Australia", "Cleaning & Hygiene"),
    ("Shenzhen CleanTech", "China", "Cleaning & Hygiene"),
    ("Botanica Labs", "Australia", "Personal Care"),
    ("Pure Leaf Cosmetics", "New Zealand", "Personal Care"),
    ("Atlantic Personal Care", "United States", "Personal Care"),
    ("Milano Cucina", "Italy", "Kitchen Equipment"),
    ("Steelcraft Kitchenware", "China", "Kitchen Equipment"),
    ("Forge and Steel Pty Ltd", "Australia", "Kitchen Equipment"),
]
PLACES = [
    "Harbourside", "Laneway", "Old Mill", "Riverbend", "Northside", "Bayview", "Hilltop",
    "Parkside", "Station Street", "Eastgate", "West End", "Seaside", "Greenhill", "Ironstone",
    "Sandstone", "Market Lane", "Tallowood", "Redgum", "Blue Door", "Little Bird", "Copper Pot",
    "Golden Wattle", "Morning Star", "Two Bridges", "High Street", "Kingfisher", "Lighthouse",
    "Jacaranda", "Southbank", "Banksia", "Wombat Hill", "Crossroads", "Silver Creek", "Ridgeway",
]
CUSTOMER_TYPES = {
    "Hospitality": ["Cafe", "Espresso Bar", "Bistro", "Kitchen", "Hotel", "Bakery", "Eatery",
                    "Brasserie", "Canteen", "Tavern"],
    "Retail": ["Grocers", "Fresh Market", "General Store", "Corner Store", "Providores",
               "Supermarket", "Pharmacy"],
    "Healthcare": ["Aged Care", "Medical Centre", "Private Hospital", "Dental Clinic",
                   "Physiotherapy", "Day Surgery", "Community Health"],
    "Education": ["Primary School", "High School", "College", "Grammar School",
                  "Early Learning Centre", "Childcare Centre", "Institute"],
}
GOOD_FRIDAY = {2023: date(2023, 4, 7), 2024: date(2024, 3, 29),
               2025: date(2025, 4, 18), 2026: date(2026, 4, 3)}

rng = random.Random(SEED)


# ---------------- draws, all from rng.random() ----------------
def u(lo=0.0, hi=1.0):
    return lo + (hi - lo) * rng.random()


def normal():
    # Box-Muller
    return math.sqrt(-2.0 * math.log(1.0 - rng.random())) * math.cos(2.0 * math.pi * rng.random())


def poisson(lam):
    # Knuth's method; fine for a small mean
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def weighted_pick(items, weights):
    r = rng.random() * sum(weights)
    for item, w in zip(items, weights):
        r -= w
        if r < 0:
            return item
    return items[-1]


def weighted_sample(items, weights, k):
    # Efraimidis-Spirakis: k distinct items, each drawn in proportion to its weight
    keys = sorted(((rng.random() ** (1.0 / w), i) for i, w in enumerate(weights)), reverse=True)
    return [items[i] for _, i in keys[:k]]


def shuffled(seq):
    return weighted_sample(list(seq), [1.0] * len(seq), len(seq))


def fiscal_year(d):
    # named for the year it ends: 1 July 2025 to 30 June 2026 is fiscal 2026
    return d.year + (1 if d.month >= 7 else 0)


# ---------------- calendar ----------------
HOLIDAYS = set()
for y in range(WARMUP.year, LAST.year + 1):
    gf = GOOD_FRIDAY[y]
    HOLIDAYS |= {date(y, 1, 1), date(y, 1, 26), gf, gf + timedelta(days=3), date(y, 4, 25),
                 date(y, 12, 25), date(y, 12, 26)}


def is_business_day(d):
    return d.weekday() < 5 and d not in HOLIDAYS


def add_business_days(d, n):
    while n > 0:
        d += timedelta(days=1)
        if is_business_day(d):
            n -= 1
    return d


DAYS = [WARMUP + timedelta(days=i) for i in range((LAST - WARMUP).days + 1)]

# ---------------- suppliers (30) ----------------
suppliers = [{"code": f"S{i:03d}", "name": n, "country": c, "category": cat}
             for i, (n, c, cat) in enumerate(SUPPLIERS, start=1)]

# ---------------- products (600) ----------------
CAT_NAMES = list(CATEGORIES)
brand_premium = {b: u(0.90, 1.20) for b in BRANDS}
products = []
for cat, (count, (m_lo, m_hi), _) in CATEGORIES.items():
    items, packs = ITEMS[cat]
    combos = [(b, item, base, pack, mult)
              for b, cats in BRANDS.items() if cat in cats
              for item, base in items for pack, mult in packs]
    assert len(combos) >= count, f"{cat}: {len(combos)} combinations for {count} products"
    cat_suppliers = [s for s in suppliers if s["category"] == cat]
    for b, item, base, pack, mult in shuffled(combos)[:count]:
        price = base * mult * brand_premium[b] * u(0.96, 1.04)
        launch = WARMUP if rng.random() >= LAUNCHED_SHARE else FIRST + timedelta(
            days=int(u(60, (LAST - FIRST).days - 90)))
        products.append({
            "name": f"{b} {item} {pack}", "brand": b, "category": cat,
            "supplier": cat_suppliers[int(rng.random() * len(cat_suppliers))],
            "price0": price, "cost0": price * (1 - u(m_lo, m_hi)),
            "popularity": math.exp(0.9 * normal()), "launch": launch,
        })
for i, p in enumerate(shuffled(products), start=1):
    p["sku"] = f"P{i:04d}"
products.sort(key=lambda p: p["sku"])

# Prices and costs step up every 1 July; fiscal 2023 holds the starting values.
FISCAL_YEARS = range(fiscal_year(WARMUP), fiscal_year(LAST) + 1)
rises = {}
for cat in CAT_NAMES:
    for fy in FISCAL_YEARS[1:]:
        rises[cat, fy] = (u(*PRICE_RISE), u(*COST_RISE))
        if cat == "Coffee & Tea" and fy in COFFEE_SQUEEZE:
            rises[cat, fy] = COFFEE_SQUEEZE[fy]
for p in products:
    price, cost = p["price0"], p["cost0"]
    p["price"], p["cost"] = {}, {}
    for fy in FISCAL_YEARS:
        if fy != FISCAL_YEARS[0]:
            pr, cr = rises[p["category"], fy]
            price, cost = price * (1 + pr), cost * (1 + cr)
        p["price"][fy], p["cost"][fy] = round(price, 2), round(cost, 2)

# ---------------- customers (400) ----------------
customers = []
for seg, (count, rate, _) in SEGMENTS.items():
    types = CUSTOMER_TYPES[seg]
    names = shuffled([f"{pl} {t}" for pl in PLACES for t in types])
    assert len(names) >= count, seg
    for name in names[:count]:
        customers.append({
            "name": name, "segment": seg,
            "state": weighted_pick([s for s, _ in STATES], [w for _, w in STATES]),
            "size": math.exp(0.6 * normal()), "start": WARMUP, "end": LAST,
        })
picks = shuffled(range(len(customers)))
for i in picks[:NEW_CUSTOMERS]:
    customers[i]["start"] = FIRST + timedelta(days=int(u(0, (LAST - FIRST).days - 90)))
for i in picks[NEW_CUSTOMERS:NEW_CUSTOMERS + CHURNED]:
    customers[i]["end"] = FIRST + timedelta(days=int(u(60, (LAST - FIRST).days - 30)))
customers.sort(key=lambda c: (c["start"], c["name"]))
for i, c in enumerate(customers, start=1):
    c["code"] = f"C{i:04d}"
    affinity = dict(zip(CAT_NAMES, AFFINITY[c["segment"]]))
    c["basket"] = weighted_sample(products, [affinity[p["category"]] * p["popularity"]
                                             for p in products], 12 + int(u(0, 36)))


# ---------------- order rate, scaled so the exported span expects TARGET_LINES ----------------
def day_factor(c, d):
    if not (c["start"] <= d <= c["end"]) or d in HOLIDAYS or d.weekday() == 6:
        return 0.0
    _, rate, saturday = SEGMENTS[c["segment"]]
    weekday = saturday if d.weekday() == 5 else WEEKDAY[d.weekday()]
    years = (d - FIRST).days / 365.25
    return rate * c["size"] * SEASON[c["segment"]][d.month - 1] * weekday * ORGANIC_GROWTH ** years


exported = sum(day_factor(c, d) for c in customers for d in DAYS if d >= FIRST)
base_rate = TARGET_LINES / ((1 + EXTRA_LINES) * exported)

# ---------------- orders ----------------
orders = []  # (date, customer, [(product, quantity)])
for d in DAYS:
    for c in customers:
        f = day_factor(c, d)
        if f == 0.0 or rng.random() >= min(base_rate * f, 0.95):
            continue
        available = [p for p in c["basket"] if p["launch"] <= d]
        if not available:
            continue
        n = min(1 + poisson(EXTRA_LINES), MAX_LINES, len(available))
        picked = weighted_sample(available, [p["popularity"] for p in available], n)
        lines = []
        for p in picked:
            mean_qty = CATEGORIES[p["category"]][2] * c["size"] ** 0.4
            lines.append((p, 1 + int(-math.log(1.0 - rng.random()) * mean_qty)))
        orders.append((d, c, lines))


def ship_date(d):
    r = rng.random()
    n = 0 if r < 0.15 else 1 if r < 0.75 else 2 if r < 0.90 else 3 + int(u(0, 2))
    shipped = add_business_days(d, n)
    return shipped if shipped <= LAST else d


# ---------------- targets: last year's actual plus a planned growth ----------------
actual = defaultdict(float)  # (category, year, month) -> sales
for d, c, lines in orders:
    fy = fiscal_year(d)
    for p, qty in lines:
        actual[p["category"], d.year, d.month] += qty * p["price"][fy]
targets = []
for y in range(FIRST.year, LAST.year + 1):
    for cat in CAT_NAMES:
        growth = u(*PLAN_GROWTH)
        for m in range(1, 13):
            targets.append((date(y, m, 1), cat, round(actual[cat, y - 1, m] * (1 + growth), -2)))


# ---------------- write ----------------
def write_csv(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    print(f"{path.name}: {len(rows):,} rows, {path.stat().st_size / 1e6:.1f} MB, sha256 {digest}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=ROOT / "data", help="folder for the CSVs")
    out = parser.parse_args().out
    out.mkdir(parents=True, exist_ok=True)

    rows = []
    number = 100_000
    for d, c, lines in orders:
        if d < FIRST:
            continue
        number += 1
        shipped = ship_date(d)
        fy = fiscal_year(d)
        for line_no, (p, qty) in enumerate(lines, start=1):
            s = p["supplier"]
            rows.append([f"SO-{number}", line_no, d.isoformat(), shipped.isoformat(),
                         c["code"], c["name"], c["segment"], c["state"],
                         p["sku"], p["name"], p["brand"], p["category"],
                         s["code"], s["name"], s["country"],
                         qty, f"{p['price'][fy]:.2f}", f"{p['cost'][fy]:.2f}"])
    assert all(str(v).isascii() for row in rows for v in row), "names must be ASCII for Excel"

    write_csv(out / "order_lines.csv",
              ["OrderNumber", "LineNumber", "OrderDate", "ShipDate",
               "CustomerCode", "CustomerName", "Segment", "State",
               "SKU", "ProductName", "Brand", "Category",
               "SupplierCode", "SupplierName", "SupplierCountry",
               "Quantity", "UnitPrice", "UnitCost"], rows)
    write_csv(out / "sales_targets.csv", ["Month", "Category", "TargetAmount"],
              [[m.isoformat(), cat, f"{t:.0f}"] for m, cat, t in targets])

    # Figures to check a rebuild against, and the first numbers the lessons reconcile.
    by_year = defaultdict(lambda: [0, 0.0, 0.0])
    for r in rows:
        y = by_year[r[2][:4]]
        y[0] += 1
        y[1] += r[15] * float(r[16])
        y[2] += r[15] * float(r[17])
    for y, (n, sales, cost) in sorted(by_year.items()):
        print(f"{y}: {n:,} lines, sales {sales:,.2f}, gross margin {1 - cost / sales:.1%}")
    print(f"orders {number - 100_000:,}; customers {len({r[4] for r in rows})}; "
          f"products {len({r[8] for r in rows})}; suppliers {len({r[12] for r in rows})}")
    target_total = sum(t for _, _, t in targets)
    print(f"total sales {sum(v[1] for v in by_year.values()):,.2f}; total target {target_total:,.0f}")


if __name__ == "__main__":
    main()
