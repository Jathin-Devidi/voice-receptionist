WITH b AS (
  INSERT INTO businesses (name, address, timezone, not_offered, notes)
  VALUES ('Sunrise Salon', '12 Lake Road, Indiranagar, Bengaluru', 'Asia/Kolkata',
          ARRAY['nail art','waxing','makeup','tattoos','home service'],
          'Closed on Sundays. Free cancellation up to 2 hours before. No membership or package info on file.')
  RETURNING id
), s AS (
  INSERT INTO stylists (business_id, name)
  SELECT b.id, n FROM b, unnest(ARRAY['Anita Rao','Rahul Shetty','Kavya Nair']) n
  RETURNING id, business_id, name
), sv AS (
  INSERT INTO services (business_id, stylist_id, name, price_inr, price_note)
  SELECT s.business_id, s.id, v.name, v.price, v.note
  FROM s JOIN (VALUES
    ('Anita Rao','Haircut (women)',600,NULL),
    ('Anita Rao','Haircut (men)',400,NULL),
    ('Anita Rao','Blow dry and styling',500,NULL),
    ('Rahul Shetty','Hair colour',2500,'From Rs 2,500, depends on hair length'),
    ('Rahul Shetty','Hair spa',1200,NULL),
    ('Kavya Nair','Facial',1500,NULL),
    ('Kavya Nair','Clean-up',800,NULL)
  ) AS v(sname,name,price,note) ON v.sname = s.name
  RETURNING 1
), wh AS (
  INSERT INTO working_hours (stylist_id, weekday, start_time, end_time)
  SELECT s.id, d.wd, d.st::time, d.en::time
  FROM s JOIN (VALUES
    ('Anita Rao',0,'10:00','14:00'),('Anita Rao',1,'10:00','14:00'),('Anita Rao',2,'10:00','14:00'),
    ('Anita Rao',3,'10:00','14:00'),('Anita Rao',4,'10:00','14:00'),('Anita Rao',5,'10:00','14:00'),
    ('Rahul Shetty',1,'16:00','20:00'),('Rahul Shetty',3,'16:00','20:00'),('Rahul Shetty',5,'16:00','20:00'),
    ('Kavya Nair',0,'09:00','13:00'),('Kavya Nair',2,'09:00','13:00'),('Kavya Nair',4,'09:00','13:00')
  ) AS d(sname,wd,st,en) ON d.sname = s.name
  RETURNING 1
)
INSERT INTO faqs (business_id, topic, answer)
SELECT b.id, f.t, f.a FROM b, (VALUES
  ('payment','We accept cash, UPI and cards.'),
  ('walk-ins','Walk-ins are welcome, but customers with a booking are served first.'),
  ('parking','Street parking only.'),
  ('late arrival','If you are more than 15 minutes late, your booking may be moved to the next free slot.'),
  ('discounts','There are no discounts right now.'),
  ('cancellation','Free cancellation up to 2 hours before the appointment.')
) AS f(t,a);
