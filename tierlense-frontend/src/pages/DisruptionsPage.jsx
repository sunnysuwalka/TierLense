import React, { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, ArrowDownRight, ClipboardCheck, ExternalLink, Filter, Plus, RefreshCw, ShieldAlert, X } from 'lucide-react';
import { apiRequest, queryString } from '../api/client.js';
import { useApp } from '../context/AppContext.jsx';
import { Alert, Card, EmptyState, ErrorInline, Field, formatDate, LoadingState, Modal, PageHeader, StatusBadge } from '../components/Shared.jsx';

const EVENT_TYPES = ['operational_outage', 'production_shutdown', 'capacity_shortage', 'cyber_incident', 'natural_disaster', 'labor_dispute', 'logistics_disruption', 'regulatory_action', 'financial_distress', 'supplier_loss', 'geopolitical_event', 'other'];
const EVENT_STATUSES = ['observed', 'reported', 'forecast', 'risk_signal', 'unclear'];

export default function DisruptionsPage() {
  const { selectedOrg, selectedOrgId, pushNotice } = useApp();
  const [events, setEvents] = useState([]);
  const [total, setTotal] = useState(0);
  const [entities, setEntities] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [typeFilter, setTypeFilter] = useState('all');
  const [modalOpen, setModalOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState('');
  const [selectedEvent, setSelectedEvent] = useState(null);
  const [inspectEvent, setInspectEvent] = useState(null);
  const [inspectLoading, setInspectLoading] = useState(false);
  const [impact, setImpact] = useState(null);
  const [impactLoading, setImpactLoading] = useState(false);
  const [form, setForm] = useState({ affected_entity_id: '', event_type: 'operational_outage', event_status: 'reported', severity: '3', country_code: '', event_date: '', summary: '', confidence: '0.7', evidence_document_id: '', source_passage: '' });
  const change = (key) => (event) => setForm((current) => ({ ...current, [key]: event.target.value }));

  const load = useCallback(async () => {
    if (!selectedOrgId) { setEvents([]); setEntities([]); return; }
    setLoading(true); setError('');
    const [eventsRes, entitiesRes] = await Promise.allSettled([
      apiRequest(`/supply-chain/organizations/${selectedOrgId}/disruptions?limit=200${queryString({ event_status: statusFilter === 'all' ? '' : statusFilter, event_type: typeFilter === 'all' ? '' : typeFilter })}`),
      apiRequest(`/supply-chain/organizations/${selectedOrgId}/entities?limit=200`),
    ]);
    if (eventsRes.status === 'fulfilled') { setEvents(eventsRes.value.items || []); setTotal(eventsRes.value.total || 0); }
    else setError(eventsRes.reason?.message || 'Could not load disruption records.');
    if (entitiesRes.status === 'fulfilled') setEntities(entitiesRes.value.items || []);
    else setError((current) => current || entitiesRes.reason?.message || 'Could not load graph entities.');
    setLoading(false);
  }, [selectedOrgId, statusFilter, typeFilter]);
  useEffect(() => { load(); }, [load]);

  const createEvent = async (event) => {
    event.preventDefault(); setBusy(true); setFormError('');
    try {
      const payload = { affected_entity_id: form.affected_entity_id, event_type: form.event_type, event_status: form.event_status, severity: form.severity ? Number(form.severity) : null, country_code: form.country_code.trim().toUpperCase() || null, event_date: form.event_date || null, summary: form.summary.trim(), confidence: Number(form.confidence), evidence_document_id: form.evidence_document_id.trim(), source_passage: form.source_passage.trim() };
      const result = await apiRequest(`/supply-chain/organizations/${selectedOrgId}/disruptions`, { method: 'POST', body: JSON.stringify(payload) });
      setModalOpen(false); pushNotice(result.note || 'Disruption signal recorded.'); setForm({ affected_entity_id: '', event_type: 'operational_outage', event_status: 'reported', severity: '3', country_code: '', event_date: '', summary: '', confidence: '0.7', evidence_document_id: '', source_passage: '' }); await load();
    } catch (err) { setFormError(err.message); } finally { setBusy(false); }
  };

  const inspect = async (event) => {
    setInspectEvent({ loading: true, id: event.id });
    try { setInspectEvent(await apiRequest(`/supply-chain/organizations/${selectedOrgId}/disruptions/${event.id}`)); }
    catch (err) { setInspectEvent({ id: event.id, error: err.message }); }
  };

  const calculateImpact = async (event) => {
    setSelectedEvent(event); setImpact(null); setImpactLoading(true); setError('');
    try { setImpact(await apiRequest(`/supply-chain/organizations/${selectedOrgId}/impact${queryString({ entity_id: event.affected_entity_id, event_id: event.id, max_depth: 4 })}`)); }
    catch (err) { setError(err.message); }
    finally { setImpactLoading(false); }
  };

  const highSeverity = events.filter((event) => (event.severity || 0) >= 4).length;
  return <div className="page-stack">
    <PageHeader title="Disruptions & impact" description="Review source-linked operational events and trace the entities exposed through recorded dependency paths." actions={<><button className="button button-secondary" onClick={load} disabled={loading}><RefreshCw size={15} /> Refresh</button><button className="button button-primary" onClick={() => { setFormError(''); setModalOpen(true); }} disabled={!selectedOrgId || !entities.length}><Plus size={15} /> Record disruption</button></>}>
      {selectedOrg && <div className="context-line"><span className="context-dot" /><strong>{selectedOrg.name}</strong><span className="context-separator">·</span>{total} disruption records</div>}
    </PageHeader>
    {error && <Alert tone="error">{error}</Alert>}
    {!selectedOrgId && <Card><EmptyState icon={AlertTriangle} title="Select an organization" description="Disruption records are scoped to the selected organization's graph." /></Card>}
    {selectedOrgId && <>
      <div className="metric-grid metric-grid-three"><div className="card card-padded mini-metric"><span>Disruption records</span><strong>{total}</strong><small>Source-linked records</small></div><div className="card card-padded mini-metric"><span>Severity 4–5</span><strong>{highSeverity}</strong><small>Based on reported severity field</small></div><div className="card card-padded mini-metric"><span>Source validation</span><strong>{events.filter((event) => event.validation_status === 'passage_verified').length}</strong><small>Exact-passage validated in loaded set</small></div></div>
      <Card padding={false}><div className="table-toolbar"><div className="table-toolbar-title"><strong>Disruption register</strong><span>{events.length} records loaded</span></div><div className="toolbar-filters"><label className="compact-select-label"><span>Status</span><select className="input" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}><option value="all">All statuses</option>{EVENT_STATUSES.map((status) => <option key={status} value={status}>{status.replaceAll('_', ' ')}</option>)}</select></label><label className="compact-select-label"><span>Event type</span><select className="input" value={typeFilter} onChange={(event) => setTypeFilter(event.target.value)}><option value="all">All types</option>{EVENT_TYPES.map((type) => <option key={type} value={type}>{type.replaceAll('_', ' ')}</option>)}</select></label></div></div>
        {loading && !events.length ? <LoadingState label="Loading disruption register…" /> : events.length ? <div className="table-wrap"><table className="data-table"><thead><tr><th>Event / affected entity</th><th>Type</th><th>Status</th><th>Severity</th><th>Validation</th><th>Created</th><th></th></tr></thead><tbody>{events.map((event) => <tr key={event.id}><td><strong>{event.summary}</strong><small className="table-subtext">{event.affected_entity_name}</small></td><td><span className="capitalize">{event.event_type.replaceAll('_', ' ')}</span></td><td><StatusBadge value={event.event_status} /></td><td>{event.severity ? <span className={`severity-chip severity-${event.severity}`}>{event.severity} / 5</span> : '—'}</td><td><StatusBadge value={event.validation_status} /></td><td>{formatDate(event.created_at)}</td><td><div className="row-action-buttons"><button className="button button-ghost button-small" onClick={() => inspect(event)}>Inspect</button><button className="button button-ghost button-small" onClick={() => calculateImpact(event)}><ArrowDownRight size={14} /> Impact</button></div></td></tr>)}</tbody></table></div> : <EmptyState icon={ShieldAlert} title="No disruption events recorded" description="Disruption signals are only saved when linked to a stored source document and exact supporting passage." />}
      </Card>
      {selectedEvent && <Card><div className="card-heading"><div><h2>{selectedEvent.summary}</h2><p>Downstream dependency exposure based on current graph coverage.</p></div><button className="icon-button" onClick={() => { setSelectedEvent(null); setImpact(null); }} aria-label="Close impact panel"><X size={18} /></button></div>
        {impactLoading ? <LoadingState label="Tracing downstream exposure…" /> : impact && <><div className="impact-overview"><div><span>Affected entities</span><strong>{impact.affected_entities?.length || 0}</strong></div><div><span>Traversal depth</span><strong>{impact.max_depth}</strong></div><div><span>Origin entity</span><strong>{impact.origin_entity_name}</strong></div></div>{impact.affected_entities?.length ? <div className="table-wrap"><table className="data-table"><thead><tr><th>Entity</th><th>Depth</th><th>Exposure reason</th><th>Identity</th></tr></thead><tbody>{impact.affected_entities.map((item) => <tr key={item.entity.id}><td><strong>{item.entity.name}</strong><small className="table-subtext">{item.entity.entity_type}</small></td><td>{item.depth}</td><td>{item.exposure_reason}</td><td><StatusBadge value={item.entity.identity_status} /></td></tr>)}</tbody></table></div> : <EmptyState icon={ClipboardCheck} title="No downstream entities returned" description="No affected entities were reached through the relationships currently recorded." />}{impact.notes?.map((note, i) => <p className="fine-print" key={i}>{note}</p>)}</>}</Card>}
    </>}


    <Modal open={!!inspectEvent} title="Disruption evidence" description={inspectEvent?.id} onClose={() => setInspectEvent(null)} wide footer={<button className="button button-secondary" onClick={() => setInspectEvent(null)}>Close</button>}>
      {inspectEvent?.loading ? <LoadingState label="Loading disruption details…" /> : inspectEvent?.error ? <Alert tone="error">{inspectEvent.error}</Alert> : inspectEvent && <div className="form-stack"><div className="card-heading"><div><h2>{inspectEvent.summary}</h2><p>{inspectEvent.affected_entity_name} · {inspectEvent.event_type?.replaceAll('_', ' ')}</p></div><StatusBadge value={inspectEvent.validation_status} /></div><div className="detail-rows"><div><span>Status</span><strong><StatusBadge value={inspectEvent.event_status} /></strong></div><div><span>Severity</span><strong>{inspectEvent.severity ?? 'Not specified'}</strong></div><div><span>Confidence</span><strong>{Math.round((inspectEvent.confidence || 0) * 100)}%</strong></div><div><span>Event date</span><strong>{inspectEvent.event_date || 'Not recorded'}</strong></div><div><span>Source document</span><strong className="mono">{inspectEvent.evidence_document_id}</strong></div></div><div><h3 className="section-title">Supporting passage</h3><blockquote className="source-quote">{inspectEvent.source_passage}</blockquote></div><a className="button button-secondary button-fit" href={inspectEvent.evidence_url} target="_blank" rel="noreferrer">Open original source <ExternalLink size={14} /></a></div>}
    </Modal>

    <Modal open={modalOpen} title="Record disruption signal" description="Create a source-linked event. The backend checks the excerpt against the stored evidence document." onClose={() => !busy && setModalOpen(false)} wide footer={<><button className="button button-secondary" onClick={() => setModalOpen(false)} disabled={busy}>Cancel</button><button className="button button-primary" form="disruption-form" disabled={busy}>{busy ? 'Saving…' : 'Save disruption'}</button></>}>
      <form id="disruption-form" onSubmit={createEvent} className="form-stack"><ErrorInline message={formError} /><div className="form-grid form-grid-two"><Field label="Affected entity" required><select className="input" required value={form.affected_entity_id} onChange={change('affected_entity_id')}><option value="">Select graph entity</option>{entities.map((entity) => <option key={entity.id} value={entity.id}>{entity.name}</option>)}</select></Field><Field label="Event type" required><select className="input" value={form.event_type} onChange={change('event_type')}>{EVENT_TYPES.map((type) => <option key={type} value={type}>{type.replaceAll('_', ' ')}</option>)}</select></Field><Field label="Event status" required><select className="input" value={form.event_status} onChange={change('event_status')}>{EVENT_STATUSES.map((status) => <option key={status} value={status}>{status.replaceAll('_', ' ')}</option>)}</select></Field><Field label="Severity" help="Optional scale from 1 (low) to 5 (critical)."><select className="input" value={form.severity} onChange={change('severity')}><option value="">Not specified</option>{[1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n} — {['Low', 'Guarded', 'Moderate', 'High', 'Critical'][n - 1]}</option>)}</select></Field><Field label="Country code"><input className="input input-uppercase" maxLength={2} value={form.country_code} onChange={change('country_code')} placeholder="TW" /></Field><Field label="Event date"><input className="input" value={form.event_date} onChange={change('event_date')} placeholder="2026-10-25 or source format" /></Field><Field label="Evidence document ID" required><input className="input mono" required value={form.evidence_document_id} onChange={change('evidence_document_id')} placeholder="UUID from evidence library" /></Field><Field label="Confidence (0–1)" required><input className="input" type="number" min="0" max="1" step="0.05" required value={form.confidence} onChange={change('confidence')} /></Field></div><Field label="Event summary" required><textarea className="input textarea" rows={2} required maxLength={5000} value={form.summary} onChange={change('summary')} placeholder="What happened, according to the source?" /></Field><Field label="Exact source passage" required help="Paste an excerpt from the source document. Do not write a paraphrase here."><textarea className="input textarea" rows={4} required minLength={12} maxLength={5000} value={form.source_passage} onChange={change('source_passage')} /></Field><Alert tone="info">A validated quote confirms the event is traceable to a source; it is not an independent determination that the event occurred exactly as described.</Alert></form>
    </Modal>
  </div>;
}
