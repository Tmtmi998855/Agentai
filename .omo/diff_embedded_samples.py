import json
import re
from pathlib import Path
from pprint import pprint

html = Path("docs/ui-review/review.html").read_text(encoding="utf-8")
embedded = json.loads(re.search(r'<script id="embedded-json" type="application/json">(.*?)</script>', html, re.S).group(1))["samples"]
for name in embedded:
    expected = json.loads(Path("docs/ui-review/samples", name + ".json").read_text(encoding="utf-8"))
    if embedded[name] != expected:
        print(name)
        for key in sorted(set(embedded[name]) | set(expected)):
            if embedded[name].get(key) != expected.get(key):
                print(" ", key)
                print("  html:", repr(embedded[name].get(key))[:500])
                print("  file:", repr(expected.get(key))[:500])
