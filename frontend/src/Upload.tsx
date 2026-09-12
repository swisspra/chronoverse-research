import { useEffect, useRef, useState } from 'react';
import { ArrowRight, CheckCircle2, Download, FileText, LoaderCircle, ShieldCheck, TriangleAlert, UploadCloud } from 'lucide-react';
import { request } from './api';
import { profilePath } from './helpers.mjs';
import type { ImportCommit, ImportPreview, Scope } from './types';
type UploadItem = {id: number; file: File; status: 'queued'|'previewing'|'previewed'|'committing'|'complete'|'error'; preview?: ImportPreview; committed?: ImportCommit; error?: string};
export default function Upload({profileId, profileName, onExplore, onCommitted}: {profileId: string; profileName: string; onExplore: (scope: Scope) => void; onCommitted: (scope: Scope) => void}) {
  const [items, setItems] = useState<UploadItem[]>([]), [busy, setBusy] = useState(false), [dragging, setDragging] = useState(false);
  const alive = useRef(true), sequence = useRef(0), input = useRef<HTMLInputElement>(null);
  useEffect(() => {alive.current = true; return () => {alive.current = false;};}, []);
  function update(id: number, patch: Partial<UploadItem>) {if (alive.current) setItems(previous => previous.map(item => item.id === id ? {...item,...patch} : item));}
  async function previewFiles(files: File[]) {
    if (busy || !files.length) return;
    const added = files.map(file => ({id: ++sequence.current, file, status:'queued' as const}));
    setItems(previous => [...previous,...added]); setBusy(true);
    for (const item of added) {
      if (!alive.current) break;
      update(item.id, {status:'previewing'});
      try {const form = new FormData(); form.append('file', item.file); const preview = await request<ImportPreview>('/api/imports/preview', form, profileId); update(item.id,{status:'previewed',preview});}
      catch(err) {update(item.id,{status:'error',error:err instanceof Error ? err.message : String(err)});}
    }
    if (alive.current) setBusy(false);
  }
  async function commitAll() {
    const ready = items.filter(item => item.status === 'previewed'); if (!ready.length || busy) return;
    setBusy(true);
    for (const item of ready) {
      if (!alive.current) break;
      update(item.id,{status:'committing'});
      try {const committed = await request<ImportCommit>('/api/imports/commit', {preview_id:item.preview!.preview_id}, profileId); update(item.id,{status:'complete',committed}); if (alive.current) onCommitted(committed.recommended_scope);}
      catch(err) {update(item.id,{status:'error',error:err instanceof Error ? err.message : String(err)});}
    }
    if (alive.current) setBusy(false);
  }
  const readyCount = items.filter(item => item.status === 'previewed').length, done = items.filter(item => item.committed), lastScope = done.at(-1)?.committed?.recommended_scope;
  return <div className="upload-layout"><section className="upload-main"><div className={`upload-dropzone ${dragging ? 'dragging' : ''}`} onDragOver={event => {event.preventDefault(); setDragging(true);}} onDragLeave={() => setDragging(false)} onDrop={event => {event.preventDefault(); setDragging(false); previewFiles(Array.from(event.dataTransfer.files));}}><span className="upload-symbol"><UploadCloud size={30}/></span><h2>Bring your documents into view.</h2><p>PDF, TXT, and Markdown — or structured JSON, JSONL, CSV.</p><button className="primary-button" type="button" onClick={() => input.current?.click()} disabled={busy}><UploadCloud size={15}/>{busy ? 'Processing files…' : 'Choose files to preview'}</button><input ref={input} type="file" aria-label="Upload knowledge files" accept=".pdf,.txt,.md,.markdown,.json,.jsonl,.csv" multiple disabled={busy} onChange={event => {previewFiles(Array.from(event.target.files || [])); event.target.value = '';}}/><small>Drop multiple files · 10 MiB per file · Stored in <strong>{profileName}</strong></small></div>
    <div className="upload-explainer"><ShieldCheck size={18}/><p><strong>Preview first. Commit when ready.</strong> Preview validates each complete file without adding records. Import is atomic per file; other files keep their own results.</p></div>
    {items.length > 0 && <div className="upload-queue"><div className="upload-queue-heading"><h3>{items.length} {items.length === 1 ? 'file' : 'files'}</h3>{readyCount > 0 && <button className="primary-button" disabled={busy} onClick={commitAll}><CheckCircle2 size={14}/>Commit {readyCount} {readyCount === 1 ? 'file' : 'files'} to {profileName}</button>}</div>{items.map(item => <article className={`upload-item ${item.status}`} key={item.id}><div className="upload-item-heading"><FileText size={19}/><div><strong>{item.file.name}</strong><span>{(item.file.size / 1024).toFixed(1)} KiB · {item.status === 'previewed' ? 'Validated · not imported yet' : item.status === 'complete' ? 'Imported to this profile' : item.status}</span></div>{['queued','previewing','committing'].includes(item.status) && <LoaderCircle className="spin" size={17}/>} {item.status === 'complete' && <CheckCircle2 size={18}/>} {item.status === 'error' && <TriangleAlert size={18}/>}</div>{item.error && <p className="error-message" role="alert">{item.error}</p>}{item.preview && <><div className="upload-counts"><span>{item.preview.assertion_count} assertions / passages</span><span>{item.preview.document_count} documents</span><span>{item.preview.format.toUpperCase()}</span></div>{item.preview.warnings.length > 0 && <ul className="upload-warnings">{item.preview.warnings.map((warning,index) => <li key={index}>{warning}</li>)}</ul>}<details><summary>Inspect sample passages and provenance</summary>{item.preview.sample_assertions.map((assertion,index) => <div className="upload-sample" key={assertion.id || index}><span className={`plane-pill ${assertion.plane}`}>{assertion.plane}</span><h4>{assertion.subject} → {assertion.predicate} → {assertion.object}</h4><p>{assertion.summary}</p>{assertion.evidence?.map((evidence, evidenceIndex) => <blockquote key={evidence.id || evidenceIndex}>{evidence.text}</blockquote>)}</div>)}<code>SHA-256: {item.preview.content_hash}</code></details></>}{item.committed && <p className="upload-committed"><CheckCircle2 size={14}/>{item.committed.inserted_count} added · {item.committed.existing_count} already present</p>}</article>)}</div>}
    {lastScope && <div className="upload-success"><div><strong>{done.reduce((sum,item) => sum + item.committed!.inserted_count, 0)} records added to {profileName}</strong><p>Open the recommended time scope to see the imported content.</p></div><button className="primary-button" onClick={() => onExplore(lastScope)} disabled={busy}>Explore imported knowledge <ArrowRight size={15}/></button></div>}</section>
    <aside className="upload-help"><h3>Documents are sources.<br/>Assertions need context.</h3><p>Raw PDF, TXT, and Markdown become source passages in the <strong>report</strong> plane. Their text remains inspectable. No facts are automatically extracted or declared true.</p><p>Import time describes when the document entered your corpus, not when every sentence became true.</p><div className="upload-help-note"><TriangleAlert size={16}/><p>Scanned or image-only PDFs need OCR before upload. Text-based PDFs are supported.</p></div><div className="template-downloads"><h4><Download size={15}/> Example files</h4><p>Download a synthetic template and replace its content.</p>{['txt','md','json','jsonl','csv'].map(format => <a key={format} href={profilePath(`/api/imports/templates/${format}`,profileId)} download><FileText size={13}/>{format.toUpperCase()} template<Download size={12}/></a>)}</div><p className="upload-profile-note">Dataset profiles are separate local ledgers, not authentication accounts.</p></aside></div>;
}
