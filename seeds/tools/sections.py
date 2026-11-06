import re
import sys

TME = re.compile(r"(?:t|telegram)\.me/(?:s/)?(\+[\w-]+|joinchat/[\w-]+|[A-Za-z]\w{3,31})", re.I)


def sections(path):
    cur, out = "_", {}
    for line in open(path):
        if line.startswith("#"):
            cur = line.strip("# \n")
            continue
        for m in TME.finditer(line):
            n = m.group(1)
            if not n.lower().endswith("bot"):
                out.setdefault(cur, []).append((n, line.strip()[:140]))
    return out


if __name__ == "__main__":
    for path in sys.argv[1:]:
        print("==", path)
        for sec, items in sections(path).items():
            print(f"{len(items):4d}  {sec}")
