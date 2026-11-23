"""Median and 95th percentile reply latency from logs/latency.csv (written by the agent)."""
import csv
import statistics
import sys

path = sys.argv[1] if len(sys.argv) > 1 else "logs/latency.csv"
with open(path, newline="") as f:
    rows = [r for r in csv.reader(f) if r]
values = sorted(float(r[-1]) for r in rows if r[-1].replace(".", "", 1).isdigit())
if not values:
    sys.exit("No valid latency rows yet. Make a call first.")

p95 = values[min(len(values) - 1, round(0.95 * (len(values) - 1)))]
under = sum(v <= 2500 for v in values)
print(f"turns: {len(values)}")
print(f"median: {statistics.median(values):.0f} ms")
print(f"p95:    {p95:.0f} ms")
print(f"min/max: {values[0]:.0f} / {values[-1]:.0f} ms")
print(f"within 2500 ms: {under}/{len(values)}")
if len(values) < 20:
    print("NOTE: the assignment asks for at least 20 turns.")
