import json

path = 'sdlc_pipeline.json'
data = json.load(open(path, encoding='utf-8-sig'))

# Keep only the first (most recent) occurrence of each id
seen = set()
deduped = []
for item in data['items']:
    if item['id'] not in seen:
        seen.add(item['id'])
        deduped.append(item)

removed = len(data['items']) - len(deduped)
data['items'] = deduped

json.dump(data, open(path, 'w', encoding='utf-8'), indent=2, ensure_ascii=False)
print(f'Done — removed {removed} duplicate(s), {len(deduped)} items remain')
