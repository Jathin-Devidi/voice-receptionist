import asyncio, json
from datetime import datetime, timedelta
from dotenv import load_dotenv
load_dotenv()
from agent.booking import Booker

async def main():
    b = await Booker.create()
    d = datetime.now(b.tz).date()
    while d.weekday() != 1:          # next Tuesday
        d += timedelta(days=1)
    print(json.dumps(await b.check_availability("Facial", d.isoformat()), indent=2))
    await b.pool.close()

asyncio.run(main())