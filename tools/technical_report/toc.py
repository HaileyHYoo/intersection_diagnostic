import json, subprocess, sys
doc = json.load(open(sys.argv[1])); pdf = sys.argv[2]
heads = [(b.get("h1") and 1 or 2, b.get("h1") or b.get("h2")) for b in doc["body"] if b.get("h1") or b.get("h2")]
pages = int([l for l in subprocess.run(["pdfinfo", pdf], capture_output=True, text=True).stdout.splitlines() if l.startswith("Pages")][0].split()[-1])
text = [subprocess.run(["pdftotext", "-f", str(i), "-l", str(i), "-layout", pdf, "-"], capture_output=True, text=True).stdout for i in range(1, pages + 1)]
norm = lambda s: " ".join(s.replace("–", "-").split())
out, start = [], 2
for level, h in heads:
    for i in range(start, pages):
        if any(norm(line).startswith(norm(h)) for line in text[i].splitlines()):
            out.append({"text": h, "level": level, "page": i + 1}); start = i; break
    else:
        out.append({"text": h, "level": level, "page": "?"})
json.dump(out, open("toc.json", "w"), indent=1)
print(len(out), "entries;", sum(e["page"] == "?" for e in out), "not found")
