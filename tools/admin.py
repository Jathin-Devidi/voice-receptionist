"""Change business info from the command line. Changes apply to the very next call: no redeploy.

Run from the project folder (virtual environment active):

    python -m tools.admin show
    python -m tools.admin set-price "Hair spa" 1300
    python -m tools.admin set-price "Hair colour" 2800 --note "From Rs 2,800, depends on hair length"
    python -m tools.admin add-service "Bridal trial" --stylist "Anita Rao" --price 3000
    python -m tools.admin remove-service "Bridal trial"
    python -m tools.admin set-hours "Anita Rao" mon-sat 10:00 15:00
    python -m tools.admin day-off "Anita Rao" sat
    python -m tools.admin set-faq parking "Free parking behind the salon."
    python -m tools.admin remove-faq parking
    python -m tools.admin set-address "New address here"
    python -m tools.admin add-stylist "Meera Pillai"
    python -m tools.admin not-offered add "threading"
    python -m tools.admin not-offered remove "threading"
    python -m tools.admin bookings
    python -m tools.admin tickets

Set BUSINESS_NAME in .env (or the environment) to manage a different business.
"""
import argparse
import asyncio
import sys
from datetime import datetime, time

from dotenv import load_dotenv

from agent.booking import DAYS, Booker, _label

load_dotenv()

DAY_KEYS = {d[:3].lower(): i for i, d in enumerate(DAYS)}


def parse_days(text: str) -> list[int]:
    """'mon-sat', 'tue,thu,sat', 'monday' -> [0..5], [1,3,5], [0]"""
    out: list[int] = []
    for part in text.lower().replace(" ", "").split(","):
        if "-" in part:
            a, b = part.split("-", 1)
            i, j = DAY_KEYS[a[:3]], DAY_KEYS[b[:3]]
            out += list(range(i, j + 1)) if i <= j else list(range(i, 7)) + list(range(0, j + 1))
        else:
            out.append(DAY_KEYS[part[:3]])
    return sorted(set(out))


def parse_time(text: str) -> time:
    h, m = text.split(":")
    return time(int(h), int(m))


async def find_stylist(c, b: Booker, name: str):
    row = await c.fetchrow(
        "select id, name from stylists where business_id=$1 and lower(name)=lower($2)", b.business_id, name)
    if not row:
        names = [r["name"] for r in await c.fetch("select name from stylists where business_id=$1", b.business_id)]
        sys.exit(f"No stylist called '{name}'. Stylists are: {', '.join(names)}")
    return row


async def find_service(c, b: Booker, term: str):
    svc, err = await b._find_service(c, term)
    if err:
        sys.exit(f"Could not pick one service for '{term}': {err.get('options') or err['reason']}. "
                 "Use the exact name shown by 'show'.")
    return svc


def price_text(price, note) -> str:
    return note or (f"Rs {price:,}" if price is not None else "no price")


async def warn_conflicting_bookings(c, b: Booker, stylist_id, stylist_name: str):
    """After hours change: list future confirmed bookings that no longer fit the stylist's hours."""
    hours = {r["weekday"]: (r["start_time"], r["end_time"]) for r in await c.fetch(
        "select weekday, start_time, end_time from working_hours where stylist_id=$1", stylist_id)}
    now = datetime.now(b.tz)
    bad = []
    for r in await c.fetch(
            """select code, customer_name, start_at from bookings
               where stylist_id=$1 and status='confirmed' and start_at > now() order by start_at""", stylist_id):
        t = r["start_at"].astimezone(b.tz)
        wh = hours.get(t.weekday())
        if t > now and (not wh or t.time() < wh[0] or (t + b.slot).time() > wh[1]):
            bad.append(f"  {t.strftime('%a %d %b')} {_label(t)}  {r['customer_name']}  (code {r['code']})")
    if bad:
        print(f"\nWARNING: {len(bad)} existing booking(s) for {stylist_name} are now outside their hours. "
              "Please call these customers:")
        print("\n".join(bad))


async def run(args) -> None:
    b = await Booker.create()
    try:
        async with b.pool.acquire() as c:
            cmd = args.cmd

            if cmd == "show":
                biz = await c.fetchrow("select * from businesses where id=$1", b.business_id)
                print(f"{biz['name']}  |  {biz['address']}  |  {biz['timezone']}")
                print(f"Notes: {biz['notes']}")
                print(f"Not offered: {', '.join(biz['not_offered']) or '-'}")
                print("\nServices")
                for r in await c.fetch(
                        """select s.name, s.price_inr, s.price_note, st.name stylist from services s
                           join stylists st on st.id=s.stylist_id where s.business_id=$1 and s.active
                           order by st.name, s.name""", b.business_id):
                    print(f"  {r['name']:<24} {price_text(r['price_inr'], r['price_note']):<42} {r['stylist']}")
                print("\nHours")
                for r in await c.fetch(
                        """select st.name, w.weekday, w.start_time, w.end_time from stylists st
                           left join working_hours w on w.stylist_id=st.id where st.business_id=$1
                           order by st.name, w.weekday""", b.business_id):
                    when = "(no working days)" if r["weekday"] is None else (
                        f"{DAYS[r['weekday']]:<10} {r['start_time']:%H:%M} to {r['end_time']:%H:%M}")
                    print(f"  {r['name']:<14} {when}")
                print("\nFAQs")
                for r in await c.fetch("select topic, answer from faqs where business_id=$1 order by id",
                                       b.business_id):
                    print(f"  {r['topic']:<14} {r['answer']}")

            elif cmd == "set-price":
                svc = await find_service(c, b, args.service)
                await c.execute("update services set price_inr=$1, price_note=$2 where id=$3",
                                args.amount, args.note or None, svc["id"])
                print(f"{svc['name']} is now: {price_text(args.amount, args.note)}")

            elif cmd == "add-service":
                st = await find_stylist(c, b, args.stylist)
                existing = await c.fetchrow("select id, active from services where business_id=$1 "
                                            "and lower(name)=lower($2)", b.business_id, args.name)
                if existing and existing["active"]:
                    sys.exit(f"A service called '{args.name}' already exists. Use set-price to change it.")
                if existing:  # bring back a previously removed service
                    await c.execute("update services set active=true, stylist_id=$1, price_inr=$2, price_note=$3 "
                                    "where id=$4", st["id"], args.price, args.note or None, existing["id"])
                else:
                    await c.execute(
                        "insert into services (business_id, stylist_id, name, price_inr, price_note) "
                        "values ($1,$2,$3,$4,$5)", b.business_id, st["id"], args.name, args.price, args.note or None)
                print(f"Added '{args.name}' with {st['name']}: {price_text(args.price, args.note)}")

            elif cmd == "remove-service":
                svc = await find_service(c, b, args.name)
                if await c.fetchval("select 1 from bookings where service_id=$1 and status='confirmed' "
                                    "and start_at > now()", svc["id"]):
                    sys.exit(f"'{svc['name']}' has upcoming bookings. Cancel or move those first.")
                # Soft delete: callers no longer hear about it, booking history stays intact.
                await c.execute("update services set active=false where id=$1", svc["id"])
                print(f"'{svc['name']}' removed. Callers will no longer be offered it.")

            elif cmd == "set-hours":
                st = await find_stylist(c, b, args.stylist)
                start, end = parse_time(args.start), parse_time(args.end)
                if start >= end:
                    sys.exit("Start time must be before end time.")
                step = int(b.slot.total_seconds() // 60)
                if start.minute % step or end.minute % step:
                    sys.exit(f"Times must be on {step}-minute marks, e.g. 10:00 or 10:30.")
                days = parse_days(args.days)
                for d in days:
                    await c.execute(
                        """insert into working_hours (stylist_id, weekday, start_time, end_time)
                           values ($1,$2,$3,$4)
                           on conflict (stylist_id, weekday)
                           do update set start_time=excluded.start_time, end_time=excluded.end_time""",
                        st["id"], d, start, end)
                print(f"{st['name']} now works {', '.join(DAYS[d] for d in days)} "
                      f"{args.start} to {args.end}.")
                await warn_conflicting_bookings(c, b, st["id"], st["name"])

            elif cmd == "day-off":
                st = await find_stylist(c, b, args.stylist)
                days = parse_days(args.days)
                await c.execute("delete from working_hours where stylist_id=$1 and weekday = any($2::int[])",
                                st["id"], days)
                print(f"{st['name']} is now off on {', '.join(DAYS[d] for d in days)}.")
                await warn_conflicting_bookings(c, b, st["id"], st["name"])

            elif cmd == "set-faq":
                topic = args.topic.lower()
                n = await c.fetchval("update faqs set answer=$1 where business_id=$2 and lower(topic)=$3 "
                                     "returning 1", args.answer, b.business_id, topic)
                if not n:
                    await c.execute("insert into faqs (business_id, topic, answer) values ($1,$2,$3)",
                                    b.business_id, topic, args.answer)
                print(f"FAQ '{topic}' {'updated' if n else 'added'}.")

            elif cmd == "remove-faq":
                n = await c.fetchval("delete from faqs where business_id=$1 and lower(topic)=lower($2) "
                                     "returning 1", b.business_id, args.topic)
                print("Removed." if n else f"No FAQ called '{args.topic}'.")

            elif cmd == "set-address":
                await c.execute("update businesses set address=$1 where id=$2", args.address, b.business_id)
                print("Address updated.")

            elif cmd == "add-stylist":
                await c.execute("insert into stylists (business_id, name) values ($1,$2)", b.business_id, args.name)
                print(f"Added stylist '{args.name}'. Now give them hours (set-hours) and services (add-service).")

            elif cmd == "not-offered":
                item = args.item.lower()
                if args.action == "add":
                    await c.execute("update businesses set not_offered = array_append(not_offered, $1) "
                                    "where id=$2 and not ($1 = any(not_offered))", item, b.business_id)
                else:
                    await c.execute("update businesses set not_offered = array_remove(not_offered, $1) "
                                    "where id=$2", item, b.business_id)
                print(f"'{item}' {'added to' if args.action == 'add' else 'removed from'} the not-offered list.")

            elif cmd == "bookings":
                rows = await c.fetch(
                    """select bk.code, bk.customer_name, bk.customer_phone, bk.start_at, bk.status,
                              sv.name service, st.name stylist from bookings bk
                       join services sv on sv.id=bk.service_id join stylists st on st.id=bk.stylist_id
                       where bk.business_id=$1 and bk.start_at > now() - interval '1 day'
                       order by bk.start_at""", b.business_id)
                for r in rows:
                    t = r["start_at"].astimezone(b.tz)
                    print(f"{t.strftime('%a %d %b')} {_label(t):<9} {r['service']:<22} {r['stylist']:<13} "
                          f"{r['customer_name']:<16} {r['customer_phone']}  {r['code']}  {r['status']}")
                if not rows:
                    print("No bookings.")

            elif cmd == "tickets":
                rows = await c.fetch("select created_at, question, phone from tickets where business_id=$1 "
                                     "order by created_at desc limit 50", b.business_id)
                for r in rows:
                    t = r["created_at"].astimezone(b.tz)
                    print(f"{t.strftime('%d %b %H:%M')}  {r['phone'] or 'no phone':<12}  {r['question']}")
                if not rows:
                    print("No questions waiting for staff.")
    finally:
        await b.pool.close()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m tools.admin", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("show")
    s = sub.add_parser("set-price"); s.add_argument("service"); s.add_argument("amount", type=int)
    s.add_argument("--note", help="Spoken instead of the number, e.g. 'From Rs 2,500, depends on hair length'")
    s = sub.add_parser("add-service"); s.add_argument("name"); s.add_argument("--stylist", required=True)
    s.add_argument("--price", type=int, required=True); s.add_argument("--note")
    s = sub.add_parser("remove-service"); s.add_argument("name")
    s = sub.add_parser("set-hours"); s.add_argument("stylist"); s.add_argument("days")
    s.add_argument("start"); s.add_argument("end")
    s = sub.add_parser("day-off"); s.add_argument("stylist"); s.add_argument("days")
    s = sub.add_parser("set-faq"); s.add_argument("topic"); s.add_argument("answer")
    s = sub.add_parser("remove-faq"); s.add_argument("topic")
    s = sub.add_parser("set-address"); s.add_argument("address")
    s = sub.add_parser("add-stylist"); s.add_argument("name")
    s = sub.add_parser("not-offered"); s.add_argument("action", choices=["add", "remove"]); s.add_argument("item")
    sub.add_parser("bookings")
    sub.add_parser("tickets")
    return p


if __name__ == "__main__":
    asyncio.run(run(build_parser().parse_args()))
