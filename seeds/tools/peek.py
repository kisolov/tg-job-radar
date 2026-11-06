import sys
import urllib.request

for u in sys.argv[1:]:
    t = urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"}), timeout=30).read().decode(
        "utf-8", "replace")
    name = u.rstrip("/").split("/")[3] + ".md"
    open(name, "w").write(t)
    lines = t.splitlines()
    print(u, len(lines))
    print("\n".join(lines[30:55]))
    print("----")
