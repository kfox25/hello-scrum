"""
Definition-of-done tests for hello-scrum. Run after every story deployment.
"""

import json
import re
import sys


def test_index_html_exists():
    with open("index.html", "r", encoding="utf-8") as f:
        content = f.read()
    assert "<h1" in content, "Missing h1 tag"
    assert "Hello Scrum" in content, "Missing title text"
    print("PASS  index.html exists and contains title")


def test_version_matches():
    with open("version.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    with open("index.html", "r", encoding="utf-8") as f:
        html = f.read()
    version = data["version"]
    assert f"v{version}" in html, f"version.json says {version} but index.html does not show it"
    print(f"PASS  version {version} matches between version.json and index.html")


def test_deployed_date_present():
    with open("version.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    with open("index.html", "r", encoding="utf-8") as f:
        html = f.read()
    deployed = data["deployed"]
    assert deployed in html, f"Deployed timestamp '{deployed}' not found in index.html"
    print(f"PASS  deployed timestamp '{deployed}' present in index.html")


def test_changelog_has_entry():
    with open("version.json", "r", encoding="utf-8") as f:
        data = json.load(f)
    assert len(data["changelog"]) > 0, "changelog is empty"
    latest = data["changelog"][-1]
    assert latest["version"] == data["version"], "Latest changelog entry does not match current version"
    print(f"PASS  changelog has entry for v{data['version']}: {latest['change']}")


def test_no_css_outside_style_block():
    with open("index.html", "r", encoding="utf-8") as f:
        html = f.read()
    style_end = html.find("</style>")
    assert style_end != -1, "No </style> tag found"
    script_start = html.find("<script", style_end)
    # only check HTML between </style> and <script> — JS blocks are not CSS
    between = html[style_end + 8 : script_start if script_start != -1 else len(html)]
    css_outside = re.search(r'[a-zA-Z.#][^<{]*\{[^}]*\}', between)
    assert not css_outside, f"CSS found outside style block: {css_outside.group()[:60]}"
    print("PASS  no CSS outside style block")


def test_no_duplicate_h1_rules():
    with open("index.html", "r", encoding="utf-8") as f:
        html = f.read()
    style_match = re.search(r'<style>([\s\S]*?)</style>', html)
    assert style_match, "No <style> block found"
    style = style_match.group(1)
    h1_count = len(re.findall(r'(?<![.\-\w])h1\s*[,{]', style))
    assert h1_count <= 1, f"Duplicate h1 rules found ({h1_count} occurrences)"
    print(f"PASS  no duplicate h1 rules ({h1_count} found)")


def test_no_webkit_text_fill_color():
    with open("index.html", "r", encoding="utf-8") as f:
        html = f.read()
    style_match = re.search(r'<style>([\s\S]*?)</style>', html)
    assert style_match, "No <style> block found"
    style = style_match.group(1)
    assert "-webkit-text-fill-color" not in style, "-webkit-text-fill-color found in style block — overrides color property"
    print("PASS  no -webkit-text-fill-color in style block")


if __name__ == "__main__":
    tests = [
        test_index_html_exists,
        test_version_matches,
        test_deployed_date_present,
        test_changelog_has_entry,
        test_no_css_outside_style_block,
        test_no_duplicate_h1_rules,
        test_no_webkit_text_fill_color,
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
