import sqlite3

conn = sqlite3.connect('data/annales.db')
print("--- annales_externes : repartition par niveau ---")
for row in conn.execute("SELECT niveau, COUNT(*) as n FROM annales_externes GROUP BY niveau ORDER BY n DESC"):
    print(f"  {row[0]!r:20s} -> {row[1]}")

print("\n--- annales_externes : repartition par matiere (top 20) ---")
for row in conn.execute("SELECT matiere, COUNT(*) as n FROM annales_externes GROUP BY matiere ORDER BY n DESC LIMIT 20"):
    print(f"  {row[0]!r:35s} -> {row[1]}")

conn.close()