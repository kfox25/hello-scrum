import glob

OLD = '<a href="health.html">Health</a>'
NEW = '<a href="health.html">Health</a>\n    <a href="prompts.html">Prompts</a>'

files = [f for f in glob.glob('*.html') if f not in ('prompts.html', 'index_baseline.html')]
updated = []
for path in files:
    with open(path, encoding='utf-8') as f:
        content = f.read()
    if OLD in content and 'prompts.html' not in content:
        content = content.replace(OLD, NEW)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        updated.append(path)

print('Updated:', updated)
