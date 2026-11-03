"""Create the demo database: 3 CPG tables with deliberately cryptic column names and some PII.

    python seed_data.py            # creates data/cpg_demo.db
"""
from __future__ import annotations

import random
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "cpg_demo.db"

random.seed(7)

BRANDS = [("BRD01", "FreshSip"), ("BRD02", "CrunchBite"), ("BRD03", "GlowCare"), ("BRD04", "PureHome")]
CATS = {"BRD01": "BEV", "BRD02": "SNK", "BRD03": "PCR", "BRD04": "HHC"}
CHANNELS = ["MT", "GT", "EC"]
REGIONS = ["NORTH", "SOUTH", "EAST", "WEST"]
FIRST = ["Asha", "Ravi", "Meera", "Kiran", "Sana", "Vikram", "Neha", "Arjun", "Divya", "Imran"]
LAST = ["Rao", "Shetty", "Khan", "Iyer", "Gupta", "Nair", "Menon", "Das", "Reddy", "Patil"]


def main() -> None:
    DB.parent.mkdir(parents=True, exist_ok=True)
    if DB.exists():
        DB.unlink()
    con = sqlite3.connect(DB)
    con.executescript(
        """
        CREATE TABLE dim_product(
            prd_cd TEXT PRIMARY KEY, prd_nm TEXT, brnd_cd TEXT, catg_cd TEXT,
            pack_sz_ml INTEGER, uom TEXT, std_cost_amt REAL, lnch_dt TEXT, actv_flg TEXT);
        CREATE TABLE dim_customer(
            cust_id TEXT PRIMARY KEY, cust_nm TEXT, cust_email TEXT, cust_phn TEXT, cntct_nm TEXT,
            rgn_cd TEXT, chnl_cd TEXT, tier_cd TEXT, credit_lmt_amt REAL);
        CREATE TABLE fact_sales(
            sls_id INTEGER PRIMARY KEY, prd_cd TEXT, cust_id TEXT, dt_key INTEGER,
            qty_sld INTEGER, gross_rev_amt REAL, disc_amt REAL, net_rev_amt REAL,
            trade_prm_flg TEXT, chnl_cd TEXT);
        """
    )
    products = []
    for i in range(1, 41):
        brnd, bname = random.choice(BRANDS)
        code = f"P{i:04d}"
        products.append(code)
        con.execute(
            "INSERT INTO dim_product VALUES (?,?,?,?,?,?,?,?,?)",
            (code, f"{bname} {random.choice(['Classic','Zero','Family','Mini'])}", brnd, CATS[brnd],
             random.choice([200, 330, 500, 1000]), "ML", round(random.uniform(8, 90), 2),
             (date(2021, 1, 1) + timedelta(days=random.randint(0, 1200))).isoformat(),
             random.choice("YYYYN")),
        )
    customers = []
    for i in range(1, 31):
        cid = f"C{i:04d}"
        customers.append((cid, random.choice(CHANNELS)))
        fn, ln = random.choice(FIRST), random.choice(LAST)
        con.execute(
            "INSERT INTO dim_customer VALUES (?,?,?,?,?,?,?,?,?)",
            (cid, f"{ln} Retail {i}", f"{fn.lower()}.{ln.lower()}{i}@example.com",
             f"+91{random.randint(7000000000, 9999999999)}", f"{fn} {ln}",
             random.choice(REGIONS), customers[-1][1], random.choice("AABC"),
             random.choice([50000, 100000, 250000, 500000])),
        )
    for i in range(1, 501):
        cid, ch = random.choice(customers)
        qty = random.randint(5, 400)
        gross = round(qty * random.uniform(10, 120), 2)
        disc = round(gross * random.choice([0, 0, 0.05, 0.1, 0.15]), 2)
        d = date(2026, 1, 1) + timedelta(days=random.randint(0, 270))
        con.execute(
            "INSERT INTO fact_sales VALUES (?,?,?,?,?,?,?,?,?,?)",
            (i, random.choice(products), cid, int(d.strftime("%Y%m%d")), qty, gross, disc,
             round(gross - disc, 2), "Y" if disc else "N", ch),
        )
    con.commit()
    con.close()
    print(f"Created {DB}  (dim_product=40, dim_customer=30, fact_sales=500 rows)")


if __name__ == "__main__":
    main()
