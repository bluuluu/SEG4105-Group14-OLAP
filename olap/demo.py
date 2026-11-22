import csv
from datetime import date, timedelta
from pathlib import Path
from random import Random

from .etl import FILES

FIRST_DATE = date(2023, 11, 1)
LAST_DATE = date(2026, 11, 1)
PRODUCTS = (
    ("P01", "Harbour Lounge Chair", "Furniture", 32900),
    ("P02", "Marlow Side Table", "Furniture", 14900),
    ("P03", "Alder Oak Bench", "Furniture", 26900),
    ("P04", "Linen Table Runner", "Home & Living", 3900),
    ("P05", "Cedar Fragrance Set", "Home & Living", 4800),
    ("P06", "Woven Throw", "Home & Living", 7200),
    ("P07", "Stoneware Dinner Set", "Kitchen", 8900),
    ("P08", "Everyday Glassware", "Kitchen", 3400),
    ("P09", "Cast Iron Skillet", "Kitchen", 6400),
    ("P10", "Solstice Desk Lamp", "Lighting", 11900),
    ("P11", "Arc Floor Lamp", "Lighting", 18900),
    ("P12", "Dune Pendant", "Lighting", 14900),
)
STORES = (
    ("S01", "Toronto Queen", "Ontario", 1.42),
    ("S02", "Ottawa ByWard", "Ontario", 1.0),
    ("S03", "Mississauga Square One", "Ontario", 1.10),
    ("S04", "Montréal Centre", "Québec", 1.13),
    ("S05", "Québec Saint-Roch", "Québec", 0.85),
    ("S06", "Vancouver Kitsilano", "British Columbia", 1.02),
    ("S07", "Victoria Downtown", "British Columbia", 0.77),
    ("S08", "Calgary Beltline", "Prairies", 0.85),
)
SEASON = (0.76, 0.88, 1.08, 0.98, 1.12, 0.94, 1.07, 1.21, 1.12, 1.34, 1.12, 1.41)


def write_demo(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    if (directory / "READY").exists():
        return directory

    for source, rows in (("products", PRODUCTS), ("stores", STORES)):
        with (directory / f"{source}.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(FILES[source])
            writer.writerows(row[:3] for row in rows)

    rng = Random(14)
    sales_key = 0
    with (directory / "sales.csv").open("w", newline="", encoding="utf-8") as sales, (
        directory / "inventory.csv"
    ).open("w", newline="", encoding="utf-8") as inventory:
        sale_writer, stock_writer = csv.writer(sales), csv.writer(inventory)
        sale_writer.writerow(FILES["sales"])
        stock_writer.writerow(FILES["inventory"])
        for offset in range((LAST_DATE - FIRST_DATE).days + 1):
            day = FIRST_DATE + timedelta(days=offset)
            for store_index, (store_id, _, _, demand) in enumerate(STORES):
                factor = SEASON[day.month - 1] * (1 + offset / 2400) * demand
                if day < LAST_DATE:
                    for _ in range(max(1, round(rng.randint(4, 8) * factor))):
                        product_id, _, _, price = rng.choice(PRODUCTS)
                        quantity = rng.choices((1, 2, 3, 4), weights=(63, 27, 8, 2))[0]
                        cents = round(price * quantity * rng.choice((1, 1, 1, 0.90, 0.85)))
                        sales_key += 1
                        sale_writer.writerow((sales_key, day, store_id, product_id, quantity,
                                              f"{cents // 100}.{cents % 100:02}"))
                for index, (product_id, *_rest) in enumerate(PRODUCTS):
                    reorder_point = 9 + (index + store_index) % 11
                    stock = max(0, rng.randint(3, 78) + (index % 4) * 3)
                    stock_writer.writerow((day, store_id, product_id, stock, reorder_point))
    (directory / "READY").touch()
    return directory
