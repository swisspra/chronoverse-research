#!/usr/bin/env python3
"""กันไฟล์ลิขสิทธิ์ ไฟล์ใหญ่ และ token ไม่ให้เข้า git

ใช้เป็น pre-commit hook:  python3 scripts/check_licensed.py $(git diff --cached --name-only)
ออก 1 ถ้าเจอปัญหา
"""
import re, sys
from pathlib import Path

MAX_MB = 10
BAD_PATH = re.compile(r"icis|copus|testset", re.I)
# ลายนิ้วมือของเนื้อคลัง: บรรทัดที่มีเกรดสินค้า + ช่วงราคา
PRICE_ROW = re.compile(r"\b(HDPE|LDPE|LLDPE|PP|PVC)\b.{0,60}?\b\d{3,4}\s*[-–]\s*\d{3,4}\b", re.I)
# ประกอบจากชิ้นส่วน ไม่งั้นไฟล์นี้จะ match ตัวเองทุกครั้งที่ถูกตรวจ
SECRET = re.compile("|".join([
    r"sk-[A-Za-z0-9]{20,}",
    r"sv=20\d\d-\d\d-\d\d&s[ir]g?=",
    "Account" + "Key=",
    "-----BEGIN [A-Z ]*PRIVATE " + "KEY",
]))
TEXT_EXT = {".md", ".txt", ".py", ".json", ".jsonl", ".csv", ".tsv", ".html", ".yml", ".yaml", ".sh", ".ts", ".tsx"}


def check(path):
    p, bad = Path(path), []
    if BAD_PATH.search(str(p)):
        bad.append("ชื่อ path มีคำต้องห้าม (icis/copus/testset)")
    if not p.exists():
        return bad
    mb = p.stat().st_size / 1048576
    if mb > MAX_MB:
        bad.append(f"ไฟล์ใหญ่ {mb:.1f} MB เกิน {MAX_MB} MB — ของใหญ่ไปอยู่ Blob")
    if p.suffix.lower() in TEXT_EXT:
        try:
            head = p.read_text(encoding="utf-8", errors="ignore")[:200_000]
        except OSError:
            return bad
        if SECRET.search(head):
            bad.append("เจอรูปแบบของ token หรือคีย์")
        hits = PRICE_ROW.findall(head)
        if len(hits) >= 3:
            bad.append(f"เจอรูปแบบตารางราคา {len(hits)} จุด — น่าจะเป็นเนื้อคลังลิขสิทธิ์")
    return bad


def main(paths):
    problems = {f: b for f in paths if (b := check(f))}
    if not problems:
        print(f"check_licensed: ผ่าน {len(paths)} ไฟล์")
        return 0
    print("check_licensed: ไม่ผ่าน\n")
    for f, bad in problems.items():
        print(f"  {f}")
        for b in bad:
            print(f"      - {b}")
    print("\nถ้ามั่นใจว่าเป็น false positive ให้แก้ที่ scripts/check_licensed.py")
    print("อย่าใช้ --no-verify ข้าม — กติกานี้คุมเรื่องลิขสิทธิ์")
    return 1


if __name__ == "__main__":
    sys.exit(main([a for a in sys.argv[1:] if a]))
