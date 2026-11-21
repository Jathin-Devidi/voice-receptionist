import asyncio
from datetime import datetime, timedelta

import pytest
from dotenv import load_dotenv

from agent.booking import Booker

load_dotenv()


async def test_two_callers_one_slot():
    b = await Booker.create()
    day = datetime.now(b.tz).date() + timedelta(days=1)
    while day.weekday() == 6:                      # skip Sunday
        day += timedelta(days=1)
    slot = f"{day.isoformat()}T10:00:00"           # Anita works 10:00 on Mon to Sat
    try:
        results = await asyncio.gather(*[
            b.book_appointment("Haircut (women)", slot, f"Caller {i}", f"90000000{i:02d}")
            for i in range(10)                     # 10 simultaneous callers
        ])
        wins = [r for r in results if r["ok"]]
        assert len(wins) == 1, results
        assert all(r["reason"] == "slot_taken" for r in results if not r["ok"])
    finally:
        async with b.pool.acquire() as c:
            await c.execute("delete from bookings where customer_phone like '90000000%'")
        await b.pool.close()