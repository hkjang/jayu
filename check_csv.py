import csv, os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

rows = []
with open(os.path.join(BASE_DIR, 'toss_portfolio.csv'), encoding='utf-8-sig') as f:
    reader = csv.DictReader(f)
    for r in reader:
        rows.append(r)

print(f'행 수: {len(rows)}')
print('컬럼:', list(rows[0].keys()))
print()
for r in rows[:3]:
    print(r)
print()
failed = [r for r in rows if r['현재가'] == '']
print(f'가격 없음: {len(failed)}개')
for r in failed:
    print(r['종목명'], r['티커'])
