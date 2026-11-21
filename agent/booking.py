"""Booking logic. All business facts come from the database.

Double-booking is prevented by the partial unique index `one_booking_per_slot`
in schema.sql. The code below only validates the request and handles the
UniqueViolation that Postgres raises for the loser of a race.
"""
import os
import re
import secrets
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import asyncpg

ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O/1/I, easy to read aloud
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _tokens(s: str) -> set[str]:
    s = re.sub(r"'s\b", "", s.lower()).replace("color", "colour")
    return set(re.sub(r"[^a-z0-9]+", " ", s).split())


def _phone(p: str) -> str:
    return re.sub(r"\D", "", p or "")[-10:]


def _label(t: datetime) -> str:
    return t.strftime("%I:%M %p").lstrip("0")


class Booker:
    def __init__(self, pool, business):
        self.pool = pool
        self.biz = business
        self.business_id = business["id"]
        self.tz = ZoneInfo(business["timezone"])
        self.slot = timedelta(minutes=business["slot_minutes"])
        self.notice_hours = business["cancel_notice_hours"]

    @classmethod
    async def create(cls, pool=None, business_name=None):
        pool = pool or await asyncpg.create_pool(os.environ["DATABASE_URL"], min_size=1, max_size=10)
        name = business_name or os.environ.get("BUSINESS_NAME", "Sunrise Salon")
        async with pool.acquire() as c:
            biz = await c.fetchrow("select * from businesses where name = $1", name)
        if not biz:
            raise RuntimeError(f"Business '{name}' not found in database")
        return cls(pool, dict(biz))

    # ---------- helpers ----------
    def now_text(self) -> str:
        """Put this in the system prompt on every call so 'tomorrow' works."""
        n = datetime.now(self.tz)
        return n.strftime(f"%A, %d %B %Y, %I:%M %p ({self.biz['timezone']})")

    def _parse_dt(self, iso: str) -> datetime:
        dt = datetime.fromisoformat(iso)
        return dt.replace(tzinfo=self.tz) if dt.tzinfo is None else dt.astimezone(self.tz)

    async def _find_service(self, conn, term: str):
        rows = await conn.fetch(
            """select s.id, s.name, s.price_inr, s.price_note, s.stylist_id, st.name as stylist
               from services s join stylists st on st.id = s.stylist_id
               where s.business_id = $1""", self.business_id)
        q = _tokens(term)
        exact = [r for r in rows if r["name"].lower() == term.lower()]
        if exact:
            return exact[0], None
        hits = [r for r in rows if q and q <= _tokens(r["name"])]
        if len(hits) == 1:
            return hits[0], None
        if not hits:
            return None, {"ok": False, "reason": "service_not_found",
                          "message": "No such service on file. Do not invent one."}
        return None, {"ok": False, "reason": "ambiguous_service",
                      "options": [h["name"] for h in hits]}

    async def _free_slots(self, conn, stylist_id, d: date):
        wh = await conn.fetchrow(
            "select start_time, end_time from working_hours where stylist_id=$1 and weekday=$2",
            stylist_id, d.weekday())
        if not wh:
            return None
        start = datetime.combine(d, wh["start_time"], self.tz)
        end = datetime.combine(d, wh["end_time"], self.tz)
        taken = {r["start_at"] for r in await conn.fetch(
            """select start_at from bookings
               where stylist_id=$1 and status='confirmed' and start_at>=$2 and start_at<$3""",
            stylist_id, start, end)}
        now, out, t = datetime.now(self.tz), [], start
        while t + self.slot <= end:
            if t > now and t not in taken:
                out.append(t)
            t += self.slot
        return out

    async def _validate_slot(self, conn, stylist_id, start: datetime):
        local = start.astimezone(self.tz)
        if local <= datetime.now(self.tz):
            return "That time is in the past."
        if local.second or local.microsecond or (local.minute % int(self.slot.total_seconds() // 60)):
            return f"Slots start on {int(self.slot.total_seconds() // 60)}-minute boundaries."
        wh = await conn.fetchrow(
            "select start_time, end_time from working_hours where stylist_id=$1 and weekday=$2",
            stylist_id, local.weekday())
        if not wh:
            return f"The stylist does not work on {DAYS[local.weekday()]}s."
        s = datetime.combine(local.date(), wh["start_time"], self.tz)
        e = datetime.combine(local.date(), wh["end_time"], self.tz)
        if local < s or local + self.slot > e:
            return "That time is outside the stylist's working hours."
        return None

    async def _find_booking(self, conn, code, phone, lock=False):
        row = await conn.fetchrow(
            f"""select b.*, st.name as stylist, sv.name as service from bookings b
                join stylists st on st.id=b.stylist_id join services sv on sv.id=b.service_id
                where b.business_id=$1 and b.code=$2 and b.status='confirmed'
                {'for update of b' if lock else ''}""",
            self.business_id, code.strip().upper())
        # Code AND phone must match; the error never says which one was wrong.
        if not row or _phone(row["customer_phone"]) != _phone(phone):
            return None
        return row

    # ---------- tools ----------
    async def get_business_info(self) -> dict:
        async with self.pool.acquire() as c:
            stylists = await c.fetch(
                """select st.name, w.weekday, w.start_time, w.end_time
                   from stylists st left join working_hours w on w.stylist_id = st.id
                   where st.business_id=$1 order by st.name, w.weekday""", self.business_id)
            services = await c.fetch(
                """select s.name, s.price_inr, s.price_note, st.name as stylist
                   from services s join stylists st on st.id=s.stylist_id
                   where s.business_id=$1 order by st.name, s.name""", self.business_id)
            faqs = await c.fetch("select topic, answer from faqs where business_id=$1", self.business_id)
        hours: dict = {}
        for r in stylists:
            if r["weekday"] is not None:
                hours.setdefault(r["name"], []).append(
                    f"{DAYS[r['weekday']]} {_label(datetime.combine(date.today(), r['start_time']))}"
                    f" to {_label(datetime.combine(date.today(), r['end_time']))}")
        return {
            "name": self.biz["name"], "address": self.biz["address"],
            "timezone": self.biz["timezone"], "notes": self.biz["notes"],
            "cancellation_free_notice_hours": self.notice_hours,
            "not_offered": self.biz["not_offered"],
            "stylist_hours": hours,
            "services": [{"name": s["name"], "stylist": s["stylist"],
                          "price": s["price_note"] or f"Rs {s['price_inr']}"} for s in services],
            "faqs": [{"topic": f["topic"], "answer": f["answer"]} for f in faqs],
        }

    async def check_availability(self, service: str, date_str: str) -> dict:
        try:
            d = date.fromisoformat(date_str)
        except ValueError:
            return {"ok": False, "reason": "bad_date", "message": "Use YYYY-MM-DD."}
        async with self.pool.acquire() as c:
            svc, err = await self._find_service(c, service)
            if err:
                return err
            if d < datetime.now(self.tz).date():
                return {"ok": False, "reason": "past_date"}
            slots = await self._free_slots(c, svc["stylist_id"], d)
            res = {"ok": True, "service": svc["name"], "stylist": svc["stylist"],
                   "date": d.isoformat(), "weekday": DAYS[d.weekday()],
                   "works_that_day": slots is not None,
                   "free_slots": [{"iso": t.isoformat(), "say": _label(t)} for t in (slots or [])]}
            if not slots:
                nxt = []
                for i in range(1, 15):
                    nd = d + timedelta(days=i)
                    s = await self._free_slots(c, svc["stylist_id"], nd)
                    if s:
                        nxt.append({"date": nd.isoformat(), "weekday": DAYS[nd.weekday()],
                                    "first_slots": [{"iso": t.isoformat(), "say": _label(t)} for t in s[:4]]})
                    if len(nxt) == 3:
                        break
                res["next_available"] = nxt
            return res

    async def book_appointment(self, service: str, start_iso: str, name: str, phone: str) -> dict:
        if not name.strip() or len(_phone(phone)) < 10:
            return {"ok": False, "reason": "need_name_and_10_digit_phone"}
        try:
            start = self._parse_dt(start_iso)
        except ValueError:
            return {"ok": False, "reason": "bad_datetime"}
        async with self.pool.acquire() as c:
            svc, err = await self._find_service(c, service)
            if err:
                return err
            problem = await self._validate_slot(c, svc["stylist_id"], start)
            if problem:
                return {"ok": False, "reason": "invalid_slot", "message": problem}
            for _ in range(5):  # retry only if the random code collides
                code = "".join(secrets.choice(ALPHABET) for _ in range(6))
                try:
                    await c.execute(
                        """insert into bookings (business_id, stylist_id, service_id,
                              customer_name, customer_phone, start_at, code)
                           values ($1,$2,$3,$4,$5,$6,$7)""",
                        self.business_id, svc["stylist_id"], svc["id"],
                        name.strip(), _phone(phone), start, code)
                except asyncpg.UniqueViolationError as e:
                    if e.constraint_name == "one_booking_per_slot":
                        return {"ok": False, "reason": "slot_taken",
                                "alternatives": await self.check_availability(
                                    svc["name"], start.date().isoformat())}
                    continue
                return {"ok": True, "code": code, "service": svc["name"], "stylist": svc["stylist"],
                        "when": start.strftime(f"%A %d %B at {_label(start)}")}
            return {"ok": False, "reason": "try_again"}

    async def cancel_appointment(self, code: str, phone: str, confirm: bool = False) -> dict:
        async with self.pool.acquire() as c, c.transaction():
            b = await self._find_booking(c, code, phone, lock=True)
            if not b:
                return {"ok": False, "reason": "no_matching_booking"}
            start = b["start_at"].astimezone(self.tz)
            hours_left = (start - datetime.now(self.tz)).total_seconds() / 3600
            if hours_left <= 0:
                return {"ok": False, "reason": "already_passed"}
            free = hours_left >= self.notice_hours
            if not free and not confirm:
                return {"ok": False, "needs_confirmation": True, "free_cancellation": False,
                        "message": f"Less than {self.notice_hours} hours before, so it is not a free "
                                   "cancellation. Ask the caller if they still want to cancel."}
            await c.execute("update bookings set status='cancelled' where id=$1", b["id"])
            return {"ok": True, "free_cancellation": free, "cancelled": b["service"],
                    "was": start.strftime(f"%A %d %B at {_label(start)}")}

    async def reschedule_appointment(self, code: str, phone: str, new_start_iso: str) -> dict:
        try:
            new = self._parse_dt(new_start_iso)
        except ValueError:
            return {"ok": False, "reason": "bad_datetime"}
        try:
            async with self.pool.acquire() as c, c.transaction():
                b = await self._find_booking(c, code, phone, lock=True)
                if not b:
                    return {"ok": False, "reason": "no_matching_booking"}
                problem = await self._validate_slot(c, b["stylist_id"], new)
                if problem:
                    return {"ok": False, "reason": "invalid_slot", "message": problem}
                # One UPDATE: the unique index guards the new slot; on failure nothing changes.
                await c.execute("update bookings set start_at=$1 where id=$2", new, b["id"])
                return {"ok": True, "code": b["code"], "service": b["service"], "stylist": b["stylist"],
                        "when": new.strftime(f"%A %d %B at {_label(new)}")}
        except asyncpg.UniqueViolationError:
            return {"ok": False, "reason": "slot_taken"}

    async def handoff_to_staff(self, question: str, phone: str = "") -> dict:
        async with self.pool.acquire() as c:
            await c.execute("insert into tickets (business_id, question, phone) values ($1,$2,$3)",
                            self.business_id, question, _phone(phone) or None)
        return {"ok": True, "message": "Question saved for staff to follow up."}
