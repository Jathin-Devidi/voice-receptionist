CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE businesses (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  address TEXT,
  timezone TEXT NOT NULL DEFAULT 'Asia/Kolkata',
  slot_minutes INT NOT NULL DEFAULT 30,
  cancel_notice_hours INT NOT NULL DEFAULT 2,
  not_offered TEXT[] DEFAULT '{}',
  notes TEXT
);

CREATE TABLE stylists (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id UUID NOT NULL REFERENCES businesses(id),
  name TEXT NOT NULL
);

CREATE TABLE services (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id UUID NOT NULL REFERENCES businesses(id),
  stylist_id UUID NOT NULL REFERENCES stylists(id),
  name TEXT NOT NULL,
  price_inr INT,
  price_note TEXT,         -- e.g. 'From Rs 2,500, depends on hair length'
  active BOOLEAN NOT NULL DEFAULT TRUE  -- false = retired (hidden from callers, kept for history)
);

CREATE TABLE working_hours (
  stylist_id UUID NOT NULL REFERENCES stylists(id),
  weekday INT NOT NULL,    -- 0=Mon ... 6=Sun
  start_time TIME NOT NULL,
  end_time TIME NOT NULL,
  PRIMARY KEY (stylist_id, weekday)
);

CREATE TABLE faqs (
  id SERIAL PRIMARY KEY,
  business_id UUID NOT NULL REFERENCES businesses(id),
  topic TEXT NOT NULL,
  answer TEXT NOT NULL
);

CREATE TABLE bookings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  business_id UUID NOT NULL REFERENCES businesses(id),
  stylist_id UUID NOT NULL REFERENCES stylists(id),
  service_id UUID NOT NULL REFERENCES services(id),
  customer_name TEXT NOT NULL,
  customer_phone TEXT NOT NULL,
  start_at TIMESTAMPTZ NOT NULL,
  status TEXT NOT NULL DEFAULT 'confirmed',  -- confirmed | cancelled | done
  code TEXT UNIQUE NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- The double-booking guarantee: one confirmed booking per stylist per slot.
CREATE UNIQUE INDEX one_booking_per_slot
  ON bookings (stylist_id, start_at) WHERE status = 'confirmed';

CREATE TABLE tickets (
  id SERIAL PRIMARY KEY,
  business_id UUID NOT NULL REFERENCES businesses(id),
  question TEXT NOT NULL,
  phone TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE calls (
  id SERIAL PRIMARY KEY,
  business_id UUID REFERENCES businesses(id),
  started_at TIMESTAMPTZ DEFAULT now(),
  transcript JSONB,
  latencies_ms JSONB
);
