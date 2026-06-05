import json

path = r'C:\Users\Kevin\projects\hello-scrum\sdlc_pipeline.json'
with open(path, encoding='utf-8-sig') as f:
    data = json.load(f)

# Remove any leftover test stories
data['items'] = [i for i in data['items'] if not str(i['id']).startswith('status-feed-test')]

# Clear any existing sprint items
for item in data['items']:
    item['in_sprint'] = False

# Add fresh test story at the top
data['items'].insert(0, {
    "id": "status-feed-test-3",
    "idea": "Add a hover color change to the changelog entries on the homepage",
    "in_sprint": True,
    "status": "pending",
    "story": "As a visitor to the homepage, I want changelog entries to highlight when I hover over them so that I can easily read individual entries.",
    "acceptance_criteria": [
        "Hovering over a changelog entry changes its background to a subtle dark highlight color",
        "The highlight color is consistent with the dark theme (e.g. #1a1a1a or #222)",
        "The transition is smooth using CSS transition property",
        "No existing changelog styles or layout are otherwise modified"
    ]
})

with open(path, 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
print('Done — test story added to sprint')
