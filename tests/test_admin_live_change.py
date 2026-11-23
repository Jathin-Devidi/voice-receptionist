"""Live-change scenarios: the very next lookup must reflect an admin edit, with no restart."""
from datetime import datetime, timedelta

from tools.admin import build_parser, parse_days, run
from tests.conftest import TEST_PHONE_PREFIX

P1 = TEST_PHONE_PREFIX + "01"


async def admin(*argv):
    await run(build_parser().parse_args(list(argv)))


def test_parse_days():
    assert parse_days("mon-sat") == [0, 1, 2, 3, 4, 5]
    assert parse_days("tue,thu,sat") == [1, 3, 5]
    assert parse_days("Monday") == [0]
    assert parse_days("sat-mon") == [0, 5, 6]


async def test_new_service_is_bookable_then_removable(booker, capsys):
    d = datetime.now(booker.tz).date() + timedelta(days=2)
    while d.weekday() == 6:
        d += timedelta(days=1)
    try:
        await admin("add-service", "Bridal trial", "--stylist", "Anita Rao", "--price", "3000")
        info = await booker.get_business_info()
        assert {"name": "Bridal trial", "stylist": "Anita Rao", "price": "Rs 3000"} in info["services"]
        r = await booker.check_availability("bridal trial", d.isoformat())
        assert r["ok"] and r["stylist"] == "Anita Rao"
        await admin("remove-service", "Bridal trial")
        r = await booker.check_availability("bridal trial", d.isoformat())
        assert r["ok"] is False and r["reason"] == "service_not_found"
        # Adding it again brings it back.
        await admin("add-service", "Bridal trial", "--stylist", "Anita Rao", "--price", "3500")
        assert (await booker.check_availability("bridal trial", d.isoformat()))["ok"]
    finally:
        async with booker.pool.acquire() as c:
            await c.execute("delete from services where name='Bridal trial'")


async def test_price_change_is_instant(booker):
    try:
        await admin("set-price", "Hair spa", "1300")
        prices = {s["name"]: s["price"] for s in (await booker.get_business_info())["services"]}
        assert prices["Hair spa"] == "Rs 1300"
        await admin("set-price", "Hair colour", "2800", "--note", "From Rs 2,800, depends on hair length")
        prices = {s["name"]: s["price"] for s in (await booker.get_business_info())["services"]}
        assert prices["Hair colour"] == "From Rs 2,800, depends on hair length"
    finally:
        await admin("set-price", "Hair spa", "1200")
        await admin("set-price", "Hair colour", "2500", "--note", "From Rs 2,500, depends on hair length")


async def test_hours_change_and_conflict_warning(booker, capsys):
    d = datetime.now(booker.tz).date() + timedelta(days=2)
    while d.weekday() != 1:   # a Tuesday
        d += timedelta(days=1)
    try:
        assert (await booker.book_appointment("Hair spa", f"{d}T16:00:00", "Asha", P1))["ok"]
        await admin("set-hours", "Rahul Shetty", "tue", "18:00", "20:00")
        out = capsys.readouterr().out
        assert "WARNING" in out and "Asha" in out
        r = await booker.book_appointment("Hair spa", f"{d}T17:00:00", "Ravi", P1[:-1] + "9")
        assert r["ok"] is False and r["reason"] == "invalid_slot"
        info = await booker.get_business_info()
        assert "Tuesday 6:00 PM to 8:00 PM" in info["stylist_hours"]["Rahul Shetty"]
        await admin("day-off", "Rahul Shetty", "sat")
        assert not any(h.startswith("Saturday") for h in (await booker.get_business_info())["stylist_hours"]["Rahul Shetty"])
    finally:
        async with booker.pool.acquire() as c:
            await c.execute("delete from working_hours where stylist_id=(select id from stylists where name='Rahul Shetty')")
            await c.execute(
                "insert into working_hours select st.id, w, '16:00', '20:00' from stylists st, "
                "unnest(array[1,3,5]) w where st.name='Rahul Shetty'")


async def test_faq_add_update_remove(booker):
    await admin("set-faq", "wifi", "Free wifi for customers.")
    assert {"topic": "wifi", "answer": "Free wifi for customers."} in (await booker.get_business_info())["faqs"]
    await admin("set-faq", "wifi", "Wifi password is at the desk.")
    faqs = [f for f in (await booker.get_business_info())["faqs"] if f["topic"] == "wifi"]
    assert len(faqs) == 1 and "desk" in faqs[0]["answer"]
    await admin("remove-faq", "wifi")
    assert not [f for f in (await booker.get_business_info())["faqs"] if f["topic"] == "wifi"]
