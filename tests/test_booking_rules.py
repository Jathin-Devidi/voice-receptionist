"""Booking rules: stylist days/hours, IST dates, cancel notice, privacy, reschedule safety."""
from datetime import datetime, timedelta

from tests.conftest import TEST_PHONE_PREFIX

P1 = TEST_PHONE_PREFIX + "01"
P2 = TEST_PHONE_PREFIX + "02"
P3 = TEST_PHONE_PREFIX + "03"


def next_weekday(b, weekdays, min_days_ahead=2):
    """First date at least `min_days_ahead` days from now whose weekday (0=Mon) is in `weekdays`."""
    d = datetime.now(b.tz).date() + timedelta(days=min_days_ahead)
    while d.weekday() not in weekdays:
        d += timedelta(days=1)
    return d


async def test_now_text_is_in_ist(booker):
    assert "Asia/Kolkata" in booker.now_text()


async def test_closed_on_sunday(booker):
    sunday = next_weekday(booker, {6})
    r = await booker.check_availability("Haircut (women)", sunday.isoformat())
    assert r["works_that_day"] is False and r["free_slots"] == []
    assert r["next_available"], "should suggest the next open days"
    b = await booker.book_appointment("Haircut (women)", f"{sunday}T11:00:00", "Test", P1)
    assert b["ok"] is False and b["reason"] == "invalid_slot"


async def test_facial_on_tuesday_offers_mon_wed_fri(booker):
    tuesday = next_weekday(booker, {1})
    r = await booker.check_availability("Facial", tuesday.isoformat())
    assert r["stylist"] == "Kavya Nair"
    assert r["works_that_day"] is False
    days = {n["weekday"] for n in r["next_available"]}
    assert days and days <= {"Monday", "Wednesday", "Friday"}


async def test_rejects_past_off_boundary_and_outside_hours(booker):
    d = next_weekday(booker, {0, 1, 2, 3, 4, 5})
    yesterday = datetime.now(booker.tz).date() - timedelta(days=1)
    cases = [
        f"{yesterday}T11:00:00",   # past
        f"{d}T11:15:00",           # not on a 30-minute boundary
        f"{d}T15:00:00",           # Anita finishes at 14:00
        f"{d}T13:30:00",           # last slot is fine, so this one is valid (control below)
    ]
    for iso in cases[:3]:
        r = await booker.book_appointment("Haircut (women)", iso, "Test", P1)
        assert r["ok"] is False and r["reason"] == "invalid_slot", (iso, r)
    ok = await booker.book_appointment("Haircut (women)", cases[3], "Test", P1)
    assert ok["ok"] is True, ok


async def test_stylist_hours_respected(booker):
    tuesday = next_weekday(booker, {1})
    # Rahul (hair spa) works Tue 16:00-20:00, not 10:00
    r = await booker.book_appointment("Hair spa", f"{tuesday}T10:00:00", "Test", P1)
    assert r["ok"] is False and r["reason"] == "invalid_slot"
    r = await booker.book_appointment("Hair spa", f"{tuesday}T16:00:00", "Test", P1)
    assert r["ok"] is True, r


async def test_book_reschedule_cancel_flow(booker):
    d = next_weekday(booker, {0, 1, 2, 3, 4, 5})
    r = await booker.book_appointment("Haircut (men)", f"{d}T11:00:00", "Asha", P1)
    assert r["ok"], r
    code = r["code"]

    moved = await booker.reschedule_appointment(code, P1, f"{d}T11:30:00")
    assert moved["ok"] and "11:30" in moved["when"], moved

    cancelled = await booker.cancel_appointment(code, P1)
    assert cancelled["ok"] and cancelled["free_cancellation"] is True, cancelled

    # The freed slot can be booked again by someone else.
    again = await booker.book_appointment("Haircut (men)", f"{d}T11:30:00", "Ravi", P2)
    assert again["ok"], again


async def test_wrong_phone_or_code_gives_no_details(booker):
    d = next_weekday(booker, {0, 1, 2, 3, 4, 5})
    r = await booker.book_appointment("Haircut (women)", f"{d}T12:00:00", "Asha", P1)
    code = r["code"]
    for bad in (
        await booker.cancel_appointment(code, P2),
        await booker.reschedule_appointment(code, P2, f"{d}T12:30:00"),
        await booker.cancel_appointment("ZZZZZZ", P1),
    ):
        assert bad == {"ok": False, "reason": "no_matching_booking"}
    # The real booking is untouched.
    assert (await booker.cancel_appointment(code, P1))["ok"]


async def test_cancel_inside_notice_window_needs_confirmation(booker):
    start = datetime.now(booker.tz) + timedelta(hours=1)
    async with booker.pool.acquire() as c:
        row = await c.fetchrow(
            "select s.id sid, st.id stid from services s join stylists st on st.id=s.stylist_id "
            "where s.name='Haircut (women)'")
        await c.execute(
            "insert into bookings (business_id, stylist_id, service_id, customer_name, customer_phone, start_at, code)"
            " values ($1,$2,$3,'Late Larry',$4,$5,'TST111')",
            booker.business_id, row["stid"], row["sid"], P3, start)
    first = await booker.cancel_appointment("TST111", P3)
    assert first["ok"] is False and first["needs_confirmation"] is True
    assert first["free_cancellation"] is False
    confirmed = await booker.cancel_appointment("TST111", P3, confirm=True)
    assert confirmed["ok"] and confirmed["free_cancellation"] is False


async def test_reschedule_into_taken_slot_changes_nothing(booker):
    d = next_weekday(booker, {0, 1, 2, 3, 4, 5})
    a = await booker.book_appointment("Haircut (women)", f"{d}T11:00:00", "A", P1)
    b = await booker.book_appointment("Haircut (women)", f"{d}T11:30:00", "B", P2)
    assert a["ok"] and b["ok"]
    r = await booker.reschedule_appointment(b["code"], P2, f"{d}T11:00:00")
    assert r["ok"] is False and r["reason"] == "slot_taken"
    # B still holds 11:30, so rebooking 11:30 must fail.
    again = await booker.book_appointment("Haircut (women)", f"{d}T11:30:00", "C", P3)
    assert again["ok"] is False and again["reason"] == "slot_taken"


async def test_us_spelling_and_possessive_service_names(booker):
    d = next_weekday(booker, {1, 3, 5})
    r = await booker.check_availability("hair color", d.isoformat())
    assert r["ok"] and r["service"] == "Hair colour"
    r = await booker.check_availability("men's haircut", d.isoformat())
    assert r["ok"] and r["service"] == "Haircut (men)"
    r = await booker.check_availability("nail art", d.isoformat())
    assert r["ok"] is False and r["reason"] == "service_not_found"


async def test_business_info_comes_from_db(booker):
    info = await booker.get_business_info()
    assert info["address"].startswith("12 Lake Road")
    assert "nail art" in info["not_offered"]
    assert any("UPI" in f["answer"] for f in info["faqs"])
    prices = {s["name"]: s["price"] for s in info["services"]}
    assert prices["Haircut (men)"] == "Rs 400"
    assert prices["Hair colour"].startswith("From Rs 2,500")
    assert info["stylist_hours"]["Rahul Shetty"] == [
        "Tuesday 4:00 PM to 8:00 PM", "Thursday 4:00 PM to 8:00 PM", "Saturday 4:00 PM to 8:00 PM"]
