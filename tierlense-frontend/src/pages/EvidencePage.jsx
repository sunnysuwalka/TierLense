import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { BookOpenText, ExternalLink, FileSearch, Hash, RefreshCw, Search, ShieldCheck } from 'lucide-react';
import { apiRequest } from '../api/client.js';
import { useApp } from '../context/AppContext.jsx';
import { Alert, Card, EmptyState, formatDate, LoadingState, Modal, PageHeader, StatusBadge } from '../components/Shared.jsx';

export default function EvidencePage() {
  const { selectedOrg, selectedOrgId } = useApp();
  const [documents, setDocuments] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [query, setQuery] = useState('');
  const [selectedDoc, setSelectedDoc] = useState(null);
  const [refreshNonce, setRefreshNonce] = useState(0);

  const load = useCallback(async () => {
    if (!selectedOrgId) { setDocuments([]); return; }
    setLoading(true); setError('');
    const baseline = await Promise.allSettled([
      apiRequest(`/supply-chain/organizations/${selectedOrgId}/relationships?limit=200`),
      apiRequest(`/supply-chain/organizations/${selectedOrgId}/disruptions?limit=200`),
      apiRequest(`/organizations/${selectedOrgId}/history?limit=100`),
      apiRequest(`/organizations/${selectedOrgId}/evidence-changes?limit=100`),
    ]);
    const docIds = new Set();
    let missing = false;
    baseline.forEach((result, index) => {
      if (result.status !== 'fulfilled') { missing = true; return; }
      const data = result.value;
      if (index === 0) (data.items || []).forEach((row) => row.evidence_document_id && docIds.add(row.evidence_document_id));
      if (index === 1) (data.items || []).forEach((row) => row.evidence_document_id && docIds.add(row.evidence_document_id));
      if (index === 2) (data.items || []).forEach((row) => (row.evidence_document_ids || []).forEach((id) => docIds.add(id)));
      if (index === 3) (data || []).forEach((row) => row.current_document_id && docIds.add(row.current_document_id));
    });
    const ids = [...docIds].slice(0, 60);
    const loaded = await Promise.allSettled(ids.map((id) => apiRequest(`/supply-chain/organizations/${selectedOrgId}/evidence/${id}`)));
    const docs = loaded.filter((item) => item.status === 'fulfilled').map((item) => item.value).sort((a, b) => new Date(b.fetched_at) - new Date(a.fetched_at));
    setDocuments(docs);
    if (missing) setError('Some evidence indexes could not be loaded; the displayed library may be incomplete.');
    const failedDocs = loaded.filter((item) => item.status === 'rejected').length;
    if (failedDocs) setError((current) => [current, `${failedDocs} evidence document(s) could not be retrieved.`].filter(Boolean).join(' '));
    setLoading(false);
  }, [selectedOrgId, refreshNonce]);
  useEffect(() => { load(); }, [load]);

  const filtered = useMemo(() => documents.filter((doc) => `${doc.title || ''} ${doc.source_url || ''} ${doc.content_excerpt || ''} ${(doc.passages || []).map((p) => p.passage).join(' ')}`.toLowerCase().includes(query.toLowerCase())), [documents, query]);

  return <div className="page-stack">
    <PageHeader title="Evidence library" description="Browse the source documents and quoted passages connected to graph relationships, disruption events and investigation snapshots." actions={<button className="button button-secondary" onClick={() => setRefreshNonce((n) => n + 1)} disabled={loading}><RefreshCw size={15} /> Refresh evidence</button>}>
      {selectedOrg && <div className="context-line"><span className="context-dot" /><strong>{selectedOrg.name}</strong><span className="context-separator">·</span>{documents.length} retrievable document records</div>}
    </PageHeader>
    {error && <Alert tone="warning">{error}</Alert>}
    {!selectedOrgId && <Card><EmptyState icon={BookOpenText} title="Select an organization" description="Evidence is scoped to records currently linked to the selected organization's graph and history." /></Card>}
    {selectedOrgId && <Card padding={false}><div className="table-toolbar"><div className="table-toolbar-title"><strong>Source documents</strong><span>{filtered.length} of {documents.length} loaded</span></div><label className="filter-search"><Search size={15} /><input placeholder="Search source, title or passage" value={query} onChange={(event) => setQuery(event.target.value)} /></label></div>
      {loading && !documents.length ? <LoadingState label="Resolving linked evidence records…" /> : filtered.length ? <div className="evidence-list">{filtered.map((doc) => <article className="evidence-card" key={doc.document_id}><div className="evidence-card-main"><div className="evidence-doc-icon"><FileSearch size={19} /></div><div className="evidence-card-copy"><div className="evidence-card-title-row"><h3>{doc.title || 'Untitled source document'}</h3><span className="source-type">{(doc.content_type || 'document').split(';')[0]}</span></div><a href={doc.source_url} target="_blank" rel="noreferrer" className="source-url">{doc.source_url}<ExternalLink size={13} /></a><p className="evidence-excerpt">{doc.content_excerpt || 'No excerpt stored.'}</p><div className="evidence-card-meta"><span><Hash size={13} /> {doc.content_hash?.slice(0, 14) || 'No hash'}…</span><span>Fetched {formatDate(doc.fetched_at)}</span><span>{doc.passages?.length || 0} linked passages</span><span>{doc.is_truncated ? 'Excerpt truncated' : 'Stored excerpt'}</span></div></div></div><div className="evidence-card-actions"><StatusBadge value={(doc.passages || []).some((p) => p.validation_status === 'passage_verified') ? 'passage_verified' : 'source_available'} /><button className="button button-secondary button-small" onClick={() => setSelectedDoc(doc)}>Inspect source <ExternalLink size={13} /></button></div></article>)}</div> : <EmptyState icon={BookOpenText} title={query ? 'No matching source records' : 'No linked evidence documents yet'} description={query ? 'Try another word, URL or excerpt.' : 'This index is derived from documents linked to current graph, events, history and evidence-change records. A scan with zero fetched documents will leave this library empty.'} />}
    </Card>}
    <Modal open={!!selectedDoc} title={selectedDoc?.title || 'Evidence document'} description={selectedDoc?.source_url} onClose={() => setSelectedDoc(null)} wide footer={<button className="button button-secondary" onClick={() => setSelectedDoc(null)}>Close</button>}>
      {selectedDoc && <div className="form-stack"><div className="detail-rows"><div><span>Document ID</span><strong className="mono">{selectedDoc.document_id}</strong></div><div><span>Fetched</span><strong>{formatDate(selectedDoc.fetched_at)}</strong></div><div><span>Published</span><strong>{formatDate(selectedDoc.published_at)}</strong></div><div><span>Content type</span><strong>{selectedDoc.content_type}</strong></div><div><span>Content hash</span><strong className="mono">{selectedDoc.content_hash}</strong></div></div><div><h3 className="section-title">Stored excerpt</h3><blockquote className="source-quote">{selectedDoc.content_excerpt}</blockquote></div><div><h3 className="section-title">Linked passages</h3>{selectedDoc.passages?.length ? selectedDoc.passages.map((passage, index) => <div className="passage-card" key={`${passage.record_id}-${index}`}><div className="passage-card-header"><span className="capitalize">{passage.record_type.replaceAll('_', ' ')}</span><StatusBadge value={passage.validation_status} /></div><p>{passage.passage}</p><small className="mono">Record: {passage.record_id}</small></div>) : <p className="muted-text">No findings, relationships or disruption events are linked to this document.</p>}</div><a href={selectedDoc.source_url} className="button button-secondary button-fit" target="_blank" rel="noreferrer">Open original source <ExternalLink size={14} /></a></div>}
    </Modal>
  </div>;
}
