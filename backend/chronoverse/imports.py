"""Validate local uploads, retain profile-bound previews, and commit atomic imports."""
from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path
import re
import subprocess
import sys
from uuid import uuid4

from pydantic import ValidationError

from .models import AssertionInput, now, timestamp

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_RECORDS = 500
MAX_TEXT_CHARS = 2_000_000
PREVIEW_PATTERN = re.compile(r"pv-[0-9a-f]{32}\Z")
SUPPORTED = {"pdf","txt","md","markdown","json","jsonl","csv"}


class ImportLimitError(ValueError):
    pass


def _dumps(data):
    return json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(",",":"))


def _parts(text, size=4000):
    start = 0
    while start < len(text):
        end = min(start+size,len(text))
        if end < len(text):
            split = text.rfind("\n",start+size//2,end)
            if split > start:
                end = split+1
        part=text[start:end]
        if part.strip():
            yield part
        start=end


def _decode(content):
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("Text/structured uploads must use UTF-8 encoding") from exc


def _pdf_pages(content):
    try:
        result = subprocess.run([sys.executable,"-m","chronoverse.pdf_extract"],input=content,capture_output=True,timeout=20)
    except subprocess.TimeoutExpired as exc:
        raise ValueError("PDF extraction exceeded 20 seconds; split or simplify this PDF") from exc
    try:
        output=json.loads(result.stdout)
    except (json.JSONDecodeError,UnicodeDecodeError) as exc:
        raise ValueError("PDF extraction failed or exceeded process memory/CPU limits; split or simplify this PDF") from exc
    if result.returncode or output.get("error"):
        message=output.get("error","PDF extraction failed")
        if "exceeds" in message:
            raise ImportLimitError(message)
        raise ValueError(message)
    return output


def _csv_rows(text):
    reader=csv.DictReader(StringIO(text,newline=""))
    required={"subject","predicate","object","valid_from","evidence_title","evidence_text"}
    if not reader.fieldnames or not required <= set(reader.fieldnames):
        raise ValueError("CSV requires subject,predicate,object,valid_from,evidence_title,evidence_text columns")
    if len(reader.fieldnames) != len(set(reader.fieldnames)):
        raise ValueError("CSV contains duplicate column names")
    allowed=required|{"id","world","plane","perspective","valid_to","recorded_at","summary","evidence_url","synthetic"}
    unknown=set(reader.fieldnames)-allowed
    if unknown:
        raise ValueError("Unsupported CSV columns: "+", ".join(sorted(unknown)))
    rows=[]
    try:
        for number,row in enumerate(reader,1):
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"CSV row {number} has a different number of cells than the header")
            if not any(value.strip() for value in row.values()):
                continue
            synthetic=row.get("synthetic","").strip().lower()
            if synthetic not in ("","true","false","1","0"):
                raise ValueError(f"CSV row {number}: synthetic must be true or false")
            evidence={"title":row.pop("evidence_title"),"text":row.pop("evidence_text"),"synthetic":synthetic in ("true","1")}
            url=row.pop("evidence_url","")
            if url.strip():
                evidence["url"]=url.strip()
            row.pop("synthetic",None)
            value={key:val for key,val in row.items() if val.strip()}
            value["evidence"]=[evidence]
            rows.append(value)
            if len(rows)>MAX_RECORDS:
                raise ImportLimitError("Upload exceeds 500 assertion limit")
    except csv.Error as exc:
        raise ValueError(f"Malformed CSV: {exc}") from exc
    return rows


def _structured(content,format):
    text=_decode(content)
    try:
        if format == "json":
            value=json.loads(text)
            if isinstance(value,dict) and "assertions" in value:
                if set(value)!={"assertions"}:
                    raise ValueError("JSON envelope accepts only an assertions array")
                value=value["assertions"]
            return value if isinstance(value,list) else [value]
        if format == "jsonl":
            rows=[]
            for number,line in enumerate(text.splitlines(),1):
                if line.strip():
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError as exc:
                        raise ValueError(f"JSONL row {number}: malformed JSON ({exc.msg})") from exc
                    if len(rows)>MAX_RECORDS:
                        raise ImportLimitError("Upload exceeds 500 assertion limit")
            return rows
        return _csv_rows(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Malformed JSON on line {exc.lineno}: {exc.msg}") from exc
    except RecursionError as exc:
        raise ValueError("JSON nesting is too deep; upload a flat assertion array") from exc


def _prepare(filename,content,format,content_hash,recorded_at):
    warnings=[]
    if format in ("json","jsonl","csv"):
        rows=_structured(content,format)
        document_count=0
    else:
        if format=="pdf":
            extracted=_pdf_pages(content)
            pages=extracted["pages"]
            warnings.append("PDF text extraction does not preserve visual layout; no OCR or automatic fact extraction was performed.")
            if extracted["empty_pages"]:
                warnings.append(f"{len(extracted['empty_pages'])} pages contained no extractable text and were skipped; scanned pages require OCR.")
        else:
            text=_decode(content)
            if len(text)>MAX_TEXT_CHARS:
                raise ImportLimitError("Extracted text exceeds 2,000,000-character limit")
            pages=[{"page":None,"text":text}]
        rows=[]
        for page in pages:
            for part in _parts(page["text"]):
                number=len(rows)+1
                locator=f"page {page['page']}, passage {number}" if page["page"] else f"passage {number}"
                rows.append({"id":f"doc-{content_hash[:24]}-{number}","subject":f"Document: {filename} [{content_hash[:12]}]","predicate":"contains passage","object":f"Passage {number} [{content_hash[:12]}]","world":"main","plane":"report","perspective":"document","valid_from":recorded_at,"recorded_at":recorded_at,"summary":"Source document passage. This is searchable source content, not an automatically extracted fact or an adjudicated truth.","evidence":[{"title":f"{filename} · {locator} · SHA-256 {content_hash}","text":part,"recorded_at":recorded_at,"synthetic":False}]})
                if len(rows)>MAX_RECORDS:
                    raise ImportLimitError("Upload exceeds 500 passage limit; split the document")
        document_count=1
        warnings.append("Document availability is recorded at import time. Dates inside the prose are not automatically modeled as fact-validity dates.")
    if not rows:
        raise ValueError("Upload contains no assertions or readable text")
    if len(rows)>MAX_RECORDS:
        raise ImportLimitError("Upload exceeds 500 assertion limit")
    validated=[]
    seen=set()
    for number,row in enumerate(rows,1):
        if not isinstance(row,dict):
            raise ValueError(f"Upload row {number}: expected an assertion object")
        row=dict(row)
        if row.get("id") is None:
            row["id"]=f"imp-{content_hash[:24]}-{number}"
        if row.get("recorded_at") is None:
            row["recorded_at"]=recorded_at
        try:
            assertion=AssertionInput.model_validate(row)
        except ValidationError as exc:
            errors="; ".join(f"{'.'.join(str(k) for k in error['loc'])}: {error['msg']}" for error in exc.errors(include_input=False))
            raise ValueError(f"Upload row {number}: {errors}") from exc
        if assertion.id in seen:
            raise ValueError(f"Upload row {number}: duplicate assertion id {assertion.id}")
        seen.add(assertion.id)
        validated.append(assertion.model_dump())
    first=validated[0]
    recommended={"valid_at":first["valid_from"],"known_at":max(now(),*[row["recorded_at"] for row in validated]),"world":first["world"],"plane":"all","perspective":"all"}
    if len({(row["world"],row["valid_from"],row["valid_to"]) for row in validated})>1:
        warnings.append("This upload contains multiple worlds or validity intervals. Recommended filters show the first assertion; adjust them to inspect other intervals.")
    return {"filename":filename,"format":format,"content_hash":content_hash,"assertion_count":len(validated),"document_count":document_count,"warnings":warnings,"assertions":validated,"recommended_scope":recommended}


class ImportService:
    def __init__(self,manager):
        self.manager=manager

    def preview(self,profile_id,filename,content):
        self.manager.get_profile(profile_id)
        if len(content)>MAX_UPLOAD_BYTES:
            raise ImportLimitError("Upload exceeds 10 MiB limit")
        if not content:
            raise ValueError("Upload is empty")
        filename=str(filename or "").replace("\\","/").rsplit("/",1)[-1]
        if not filename or len(filename)>160:
            raise ValueError("Upload filename must contain 1–160 characters")
        format=Path(filename).suffix.lower().lstrip(".")
        if format not in SUPPORTED:
            raise ValueError("Unsupported file type; upload PDF, TXT, Markdown, JSON, JSONL or CSV")
        content_hash=sha256(content).hexdigest()
        with self.manager._lock:
            existing=self.manager._catalog.execute("SELECT * FROM previews WHERE profile_id=? AND content_hash=?",(profile_id,content_hash)).fetchone()
        if existing:
            prepared=json.loads(existing["payload"])
        else:
            prepared=_prepare(filename,content,format,content_hash,now())
        # Serialization protects duplicate previews issued by API/MCP processes simultaneously.
        with self.manager._lock, self.manager._catalog:
            self.manager._catalog.execute("BEGIN IMMEDIATE")
            existing=self.manager._catalog.execute("SELECT * FROM previews WHERE profile_id=? AND content_hash=?",(profile_id,content_hash)).fetchone()
            if existing:
                prepared=json.loads(existing["payload"])
                preview_id=existing["id"]
                self.manager._catalog.execute("UPDATE previews SET created_at=? WHERE id=?",(now(),preview_id))
            else:
                preview_id="pv-"+uuid4().hex
                self.manager._catalog.execute("INSERT INTO previews VALUES (?,?,?,?,?)",(preview_id,profile_id,content_hash,now(),_dumps(prepared)))
        return self._public(profile_id,preview_id,prepared)

    def _public(self,profile_id,preview_id,prepared):
        result={key:value for key,value in prepared.items() if key!="assertions"}
        return {**result,"profile_id":profile_id,"preview_id":preview_id,"sample_assertions":prepared["assertions"][:5]}

    def commit(self,profile_id,preview_id):
        self.manager.get_profile(profile_id)
        if not isinstance(preview_id,str) or not PREVIEW_PATTERN.fullmatch(preview_id):
            raise ValueError("Invalid preview_id")
        with self.manager._lock:
            row=self.manager._catalog.execute("SELECT * FROM previews WHERE id=? AND profile_id=?",(preview_id,profile_id)).fetchone()
        if row is None:
            raise KeyError("Import preview not found in this profile")
        if datetime.now(timezone.utc)-datetime.fromisoformat(row["created_at"].replace("Z","+00:00"))>timedelta(hours=24):
            raise ValueError("Import preview expired after 24 hours; preview the file again")
        prepared=json.loads(row["payload"])
        result=self.manager.get_store(profile_id).add_assertions_atomic(prepared["assertions"])
        scope={**prepared["recommended_scope"],"known_at":max(now(),prepared["recommended_scope"]["known_at"])}
        return {**result,"profile_id":profile_id,"preview_id":preview_id,"filename":prepared["filename"],"content_hash":prepared["content_hash"],"recommended_scope":scope}


TEMPLATE_ASSERTION={"subject":"Synthetic Harbor","predicate":"director","object":"Ada","world":"main","plane":"report","perspective":"general","valid_from":"2026-01-01","evidence":[{"title":"Synthetic example bulletin","text":"SYNTHETIC EXAMPLE: the bulletin names Ada as director.","synthetic":True}]}
TEMPLATES={
    "txt":("text/plain; charset=utf-8","SYNTHETIC EXAMPLE\n\nThis source note describes a project meeting. Document text becomes report-plane passages; facts are not extracted automatically.\n"),
    "md":("text/markdown; charset=utf-8","# Synthetic example note\n\nThis document describes a project meeting.\n\n## Source context\nIts prose becomes searchable evidence, not an automatically verified fact.\n"),
    "json":("application/json",json.dumps({"assertions":[TEMPLATE_ASSERTION]},indent=2)),
    "jsonl":("application/x-ndjson",json.dumps(TEMPLATE_ASSERTION)+"\n"),
    "csv":("text/csv; charset=utf-8","subject,predicate,object,valid_from,plane,evidence_title,evidence_text,synthetic\nSynthetic Harbor,director,Ada,2026-01-01,report,Synthetic bulletin,SYNTHETIC EXAMPLE: Ada is named director.,true\n"),
}
