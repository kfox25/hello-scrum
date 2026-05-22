"""
Basic tests for hello-scrum app.
Run with: python test.py
"""

import json
import re
import sys


def test_index_html_exists():
    with open("index.html", "r") as f:
        content = f.read()
    assert "<h1>" in content, "Missing h1 tag"
    assert "Hello Scrum" in content, "Missing title text"
    print("PASS  index.html exists and contains title")


def test_version_matches():
    with open("version.json", "r") as f:
        data = json.load(f)
    with open("index.html", "r") as f:
        html = f.read()
    version = data["version"]
    assert f"v{version}" in html, f"version.json says {version} but index.html does not show it"
    print(f"PASS  version {version} matches between version.json and index.html")


def test_deployed_date_present():
    with open("version.json", "r") as f:
        data = json.load(f)
    with open("index.html", "r") as f:
        html = f.read()
    deployed = data["deployed"]
    assert deployed in html, f"Deployed timestamp '{deployed}' not found in index.html"
    print(f"PASS  deployed timestamp '{deployed}' present in index.html")


def test_changelog_has_entry():
    with open("version.json", "r") as f:
        data = json.load(f)
    assert len(data["changelog"]) > 0, "changelog is empty"
    latest = data["changelog"][-1]
    assert latest["version"] == data["version"], "Latest changelog entry does not match current version"
    print(f"PASS  changelog has entry for v{data['version']}: {latest['change']}")


if __name__ == "__main__":
    tests = [
        test_index_html_exists,
        test_version_matches,
        test_deployed_date_present,
        test_changelog_has_entry,
    ]
    failures = 0
    for test in tests:
        try:
            test()
        except Exception as e:
            print(f"FAIL  {test.__name__}: {e}")
            failures += 1

    print(f"\n{len(tests) - failures}/{len(tests)} tests passed")
    sys.exit(0 if failures == 0 else 1)
