"""Extract the PE Asia-Pacific 2025 weekly issues into one local JSONL. Internal data: stays out of the repo."""
import json, re, sys
from pathlib import Path
import pypdf

SRC = Path('/Users/swissp/SCGC/Chronoverse/experiments/COPUS-TESTSET')
OUT = Path('/Users/swissp/SCGC/Chronoverse/experiments/copus-pilot/pe-asia-2025.jsonl')
DATE = re.compile(r'(\d{2})-([A-Z][a-z]{2})-(\d{4})')
MONTHS = {m: i for i, m in enumerate(
    ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'], 1)}

rows = []
for path in sorted(SRC.rglob('*Polyethylene Asia-Pacific*')):
    if '2025' not in str(path) or path.suffix.lower() != '.pdf':
        continue
    match = DATE.search(path.name)
    if not match:
        print('no date in', path.name)
        continue
    day, mon, year = match.groups()
    published = f'{year}-{MONTHS[mon]:02d}-{int(day):02d}'
    try:
        reader = pypdf.PdfReader(str(path))
        text = '\n'.join((page.extract_text() or '') for page in reader.pages)
    except Exception as exc:
        print('FAIL', path.name, type(exc).__name__)
        continue
    rows.append({'id': f'pe-{published}', 'published': published, 'pages': len(reader.pages),
                 'chars': len(text), 'source_name': path.name, 'text': text})

rows.sort(key=lambda r: r['published'])
OUT.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows))
chars = sum(r['chars'] for r in rows)
print(json.dumps({'issues': len(rows), 'first': rows[0]['published'], 'last': rows[-1]['published'],
                  'total_chars': chars, 'est_tokens': chars // 4, 'output': str(OUT)}))
