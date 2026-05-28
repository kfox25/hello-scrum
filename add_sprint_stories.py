import json

path = r'C:\Users\Kevin\projects\hello-scrum\sdlc_pipeline.json'
with open(path, encoding='utf-8-sig') as f:
    data = json.load(f)

data['sprint_number'] = data.get('sprint_number', 0) + 1
sprint_num = data['sprint_number']

for item in data['items']:
    item['in_sprint'] = False

new_stories = [
    {
        "slug": "footer-opacity",
        "idea": "Set opacity: 0.7 on the footer element so it appears slightly muted",
        "story": "As a visitor, I want the footer to appear slightly muted so it doesn't compete with the main content.",
        "acceptance_criteria": [
            "The footer selector has opacity: 0.7 added",
            "No other footer styles are modified",
            "No other selectors are added or removed"
        ]
    },
    {
        "slug": "tagline-italic",
        "idea": "Add font-style: italic to .tagline so the tagline has a distinctive look",
        "story": "As a visitor, I want the tagline to be italicised so it stands out from the heading.",
        "acceptance_criteria": [
            "The .tagline selector has font-style: italic added",
            "No other .tagline styles are modified",
            "No other selectors are added or removed"
        ]
    }
]

for s in new_stories:
    s['id'] = f"sprint-{sprint_num}-{s.pop('slug')}"
    s['in_sprint'] = True
    s['status'] = 'pending'

new_ids = {s['id'] for s in new_stories}
data['items'] = new_stories + [i for i in data['items'] if i['id'] not in new_ids]

with open(path, 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

print(f'Sprint {sprint_num} — {len(new_stories)} stories added')
for s in new_stories:
    print(f"  {s['id']}")
