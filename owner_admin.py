"""Simple CLI tool for Sunrise Salon's owner to update hours, prices, services, or view tickets."""
import asyncio
import os
import sys
import asyncpg
from dotenv import load_dotenv

load_dotenv()

USAGE = """
Usage:
  python owner_admin.py add-service "<Service Name>" "<Stylist Name>" <price_inr>
  python owner_admin.py set-price "<Service Name>" <price_inr>
  python owner_admin.py set-hours "<Stylist Name>" <weekday_0_mon_to_6_sun> <HH:MM> <HH:MM>
  python owner_admin.py tickets
"""

async def main():
    if len(sys.argv) < 2:
        print(USAGE)
        return
    cmd = sys.argv[1]
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    try:
        if cmd == "add-service":
            _, _, svc, stylist, price = sys.argv
            row = await conn.fetchrow("SELECT id, business_id FROM stylists WHERE name ILIKE ", stylist)
            if not row:
                print(f"Stylist '{stylist}' not found.")
                return
            await conn.execute(
                "INSERT INTO services (business_id, stylist_id, name, price_inr) VALUES (, , , )",
                row["business_id"], row["id"], svc, int(price)
            )
            print(f"Added service '{svc}' (Rs {price}) with {stylist}.")

        elif cmd == "set-price":
            _, _, svc, price = sys.argv
            res = await conn.execute("UPDATE services SET price_inr =  WHERE name ILIKE ", int(price), svc)
            print("Updated:", res)

        elif cmd == "set-hours":
            _, _, stylist, wd, st, en = sys.argv
            sid = await conn.fetchval("SELECT id FROM stylists WHERE name ILIKE ", stylist)
            if not sid:
                print(f"Stylist '{stylist}' not found.")
                return
            await conn.execute(
                """INSERT INTO working_hours (stylist_id, weekday, start_time, end_time)
                   VALUES (, , ::time, ::time)
                   ON CONFLICT (stylist_id, weekday)
                   DO UPDATE SET start_time = EXCLUDED.start_time, end_time = EXCLUDED.end_time""",
                sid, int(wd), st, en
            )
            print(f"Updated {stylist} weekday {wd} hours to {st}-{en}.")

        elif cmd == "tickets":
            rows = await conn.fetch("SELECT created_at, phone, question FROM tickets ORDER BY created_at DESC LIMIT 20")
            for r in rows:
                print(f"[{r['created_at']}] ({r['phone'] or 'no phone'}) {r['question']}")
        else:
            print(USAGE)
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(main())
