import pytest
from dotenv import load_dotenv

from agent.booking import Booker

load_dotenv()

TEST_PHONE_PREFIX = "91110000"


@pytest.fixture
async def booker():
    b = await Booker.create()
    async with b.pool.acquire() as c:
        await c.execute("delete from bookings where customer_phone like $1", TEST_PHONE_PREFIX + "%")
    try:
        yield b
    finally:
        async with b.pool.acquire() as c:
            await c.execute("delete from bookings where customer_phone like $1", TEST_PHONE_PREFIX + "%")
        await b.pool.close()
