import json
import re
from pathlib import Path

html = Path("docs/ui-review/review.html").read_text(encoding="utf-8")
match = re.search(r'<script id="embedded-json" type="application/json">(.*?)</script>', html, re.S)
assert match
embedded = json.loads(match.group(1))["samples"]
names = ["success", "insufficient_evidence", "entity_ambiguous", "provider_auth_error", "provider_timeout", "invalid_citation"]
for name in names:
    expected = json.loads(Path("docs/ui-review/samples", name + ".json").read_text(encoding="utf-8"))
    assert embedded[name] == expected, name
print("embedded samples match all 6 JSON files")
