# ห้ารายการในไทม์ไลน์นี้ย้ายไป Azure Blob แล้ว

คำตอบดิบและ log ของการรันเป็นอนุพันธ์ของคลังลิขสิทธิ์ (L1) จึงออกจาก repo สาธารณะ
ไทม์ไลน์ที่เหลือยังครบทุกเอกสาร ขาดเฉพาะห้ารายการนี้

| เดิมในไทม์ไลน์ | ตอนนี้ |
| --- | --- |
| `2026-09-13_2232_ANSWERS_pilot-v3-three-arms.jsonl` | Blob `derived-licensed/showcase/data/arm-results-v3.jsonl` |
| `2026-09-13_2232_RUNLOG_pilot-v3-three-arms.log` | Blob `derived-licensed/showcase/data/arms-v3.log` |
| `2026-09-13_2342_ANSWERS_pilot-v4-item-arms.jsonl` | Blob `derived-licensed/showcase/data/arm-results-v4.jsonl` |
| `2026-09-13_2342_RUNLOG_pilot-v4-item-arms.log` | Blob `derived-licensed/showcase/data/arms-v4.log` |
| `2026-09-14_0041_ANSWERS_lightrag-hybrid.jsonl` | Blob `derived-licensed/showcase/data/lightrag-results-hybrid.jsonl` |

ตัวเลขทุกตัวในเอกสารสรุปคำนวณจากไฟล์เหล่านี้ ดึงจาก Blob แล้วรัน
`benchmarks/asof-pilot/score_v4.py --mcnemar` เพื่อตรวจซ้ำได้
