# BI Nexus Lab: course files

The files for the BI Nexus Lab Power BI foundations course: the dataset every module uses, the
generator that makes it, the Power BI project you build through the course, and a checkpoint
per module.

## Get started

1. Clone this repo to `C:\binexus_lab`. The project looks for its data in
   `C:\binexus_lab\data\`; if you clone somewhere else, change the `DataFolder` parameter.
   ```
   git clone https://github.com/InsightfulAnalytics/binexus_lab.git C:\binexus_lab
   ```
2. Check your PC is ready:
   ```
   powershell -ExecutionPolicy Bypass -File C:\binexus_lab\check-setup.ps1
   ```
3. Check out the module you are starting, then open `Distributor Sales.pbip` in Power BI
   Desktop and select **Refresh**. The project is saved without data, so it opens empty.
   ```
   git -C C:\binexus_lab checkout m0-start
   ```

## The data

A fictional Australian wholesale distributor that buys from 30 suppliers and sells food,
beverages, packaging, cleaning and kitchen supplies to about 400 business customers. Two raw CSV
files, the way a sales system would export them:

**`data/order_lines.csv`**: one row per order line, 1 January 2024 to 31 December 2026, about
50,000 rows. Customer, product and supplier names are repeated on every line.

| Column | Notes |
|---|---|
| OrderNumber, LineNumber | `SO-100001` onwards; lines numbered from 1 within an order |
| OrderDate, ShipDate | ISO dates; ships 0 to 4 business days after the order, never after 31 Dec 2026 |
| CustomerCode, CustomerName, Segment, State | Segment is Hospitality, Retail, Healthcare or Education |
| SKU, ProductName, Brand, Category | 12 brands, 8 categories |
| SupplierCode, SupplierName, SupplierCountry | each product has one supplier |
| Quantity, UnitPrice, UnitCost | prices and costs change every 1 July, the fiscal year start |

**`data/sales_targets.csv`**: one row per category per month (288 rows). Month is the first day
of the month; TargetAmount is last year's actual for that month and category plus a planned
growth.

The catalogue has 600 products, but only the ones that sold appear in the export (554), because a
sales export can only show what sold.

## Rebuild it

Python 3, no packages:

```
python generator/generate.py
```

It writes both files to `data/` (`--out <folder>` writes them elsewhere) and prints each file's
SHA-256 and the yearly totals. The seed is fixed, so a rebuild gives the same files; compare the
hashes below.

## Reference figures

From seed 2026:

| Year | Lines | Sales | Gross margin |
|---|---|---|---|
| 2024 | 15,381 | 5,708,437.13 | 33.8% |
| 2025 | 16,487 | 6,189,047.92 | 32.9% |
| 2026 | 17,682 | 6,761,598.38 | 32.6% |

Sales is Quantity times UnitPrice. 14,139 orders, 400 customers, 554 products, 30 suppliers.
Total target 18,670,100.

- `order_lines.csv` sha256 `b058911e9f50494ff12d529bdaacb9e56f1dc60f8606a090c24c1246f1e32213`
- `sales_targets.csv` sha256 `12d418a38a8577446fd38a4d713a859d646459ca550d57aba0e2406c33c9b68f`

## Checkpoints

Each module starts from a git tag, `m0-start` to `m8-finish`, and each module's start is the
previous module's finish, so any module can be started on its own. They arrive as the modules
are built.

| Tag | What the project holds |
|---|---|
| `m0-start` | Sales, Product, Customer and Supplier, split from the flat export by queries in the `Shipped` group; no relationships, no date table, no measures |
| `m0-finish` | plus a `Total Sales` measure |
| `m1-start` | the same as `m0-finish` |
| `m1-finish` | Sales related to Product, Customer and Supplier; `DimDate` for 2024-2026, marked as the date table, related on OrderDate (ShipDate inactive), with a `FiscalStartMonth` parameter set to July; auto date/time off; the fact's keys hidden; `Total Sales` and `Total Sales by Ship Date` in `Measure Table` |

Your rulebook, the `CLAUDE.md` you write in the course folder, is listed in `.gitignore`, so
switching to another checkpoint never replaces it.

## Licence

MIT, see [LICENSE](LICENSE). The data is fictional: the company, customer, supplier, brand and
product names were invented for the course, and any match with a real business is a coincidence.
