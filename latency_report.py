import csv, statistics
v = sorted(int(r[0]) for r in csv.reader(open("latency.csv")))
print("turns:", len(v), "median ms:", statistics.median(v), "p95 ms:", v[int(0.95 * (len(v) - 1))])