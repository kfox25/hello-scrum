import json

path = 'sdlc_pipeline.json'
data = json.load(open(path, encoding='utf-8-sig'))

for item in data['items']:
    if item['id'] == 'sprint-4-version-tooltip':
        item['in_sprint'] = False

new_story = {
    "id": "sprint-4-footer-tagline",
    "idea": "Add a short tagline below the site title on the homepage",
    "in_sprint": True,
    "status": "pending",
    "story": "As a visitor to the homepage, I want to see a short tagline below the site title so that I immediately understand what the site is about.",
    "acceptance_criteria": [
        "A tagline element appears directly below the h1 site title",
        "The tagline text is: AI-powered Scrum, built in the open",
        "The tagline is styled in a muted color consistent with the dark theme",
        "No existing heading or layout styles are modified"
    ]
}

data['items'].insert(0, new_story)
json.dump(data, open(path, 'w', encoding='utf-8'), indent=2, ensure_ascii=False)
print('Done')
