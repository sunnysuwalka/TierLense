import React, { useCallback, useEffect, useState } from 'react';
import { ArrowRightLeft, CheckCircle2, ExternalLink, RefreshCw, Search, ShieldCheck, Truck } from 'lucide-react';
import { apiRequest, queryString } from '../api/client.js';
import { useApp } from '../context/AppContext.jsx';
import { Alert, Card, EmptyState, ErrorInline, Field, formatDate, LoadingState, PageHeader, StatusBadge } from '../components/Shared.jsx';

function CandidateCard({ candidate }) {
  return <article className="candidate-card"><div className="candidate-top"><div className="candidate-avatar"><Truck size={18} /></div><div className="candidate-heading"><h3>{candidate.entity_name}</h3><div className="candidate-subline">{candidate.entity_type}{candidate.country_code ? ` · ${candidate.country_code}` : ''} <span>·</span> <StatusBadge value={candidate.identity_status} /></div></div><div className="candidate-score"><strong>{Number(candidate.match_index).toFixed(2)}</strong><span>match index</span></div></div><div className="candidate-tags"><StatusBadge value={candidate.match_status} /><span className="candidate-function">{candidate.matched_function || 'Function alignment not explicit'}</span></div>{candidate.rationale?.length > 0 && <div className="candidate-section"><h4>Why it matched</h4><ul>{candidate.rationale.map((line, index) => <li key={index}>{line}</li>)}</ul></div>}{candidate.missing_information?.length > 0 && <div className="candidate-section candidate-caveat"><h4>Still to verify</h4><ul>{candidate.missing_information.map((line, index) => <li key={index}>{line}</li>)}</ul></div>}<div className="candidate-evidence"><strong>Supporting passage</strong><p>“{candidate.source_passage}”</p><a href={candidate.evidence_url} target="_blank" rel="noreferrer">Open source <ExternalLink size={13} /></a></div><div className="candidate-footer"><span className="mono">Relationship {candidate.relationship_id.slice(0, 8)}…</span><span className="mono">Entity {candidate.entity_id.slice(0, 8)}…</span></div></article>;
}

export default function AlternativesPage() {
  const { selectedOrg, selectedOrgId, pushNotice } = useApp();
  const [entities, setEntities] = useState([]);
  const [history, setHistory] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState('');
  const [result, setResult] = useState(null);
  const [selectedHistoryId, setSelectedHistoryId] = useState('');
  const [search, setSearch] = useState('');
  const [form, setForm] = useState({ affected_entity_id: '', required_function: '', required_role: '', required_country_codes: '', excluded_country_codes: '', limit: '20' });
  const change = (key) => (event) => setForm((current) => ({ ...current, [key]: event.target.value }));

  const load = useCallback(async () => {
    if (!selectedOrgId) { setEntities([]); setHistory([]); return; }
    setLoading(true); setError('');
    const [entityResult, historyResult] = await Promise.allSettled([
      apiRequest(`/supply-chain/organizations/${selectedOrgId}/entities?limit=200`),
      apiRequest(`/organizations/${selectedOrgId}/alternative-supplier-recommendations?limit=100`),
    ]);
    if (entityResult.status === 'fulfilled') {
      setEntities(entityResult.value.items || []);
      setForm((current) => ({ ...current, affected_entity_id: (current.affected_entity_id && entityResult.value.items?.some((item) => item.id === current.affected_entity_id)) ? current.affected_entity_id : (entityResult.value.items?.find((item) => !item.is_root)?.id || entityResult.value.items?.[0]?.id || '') }));
    } else setError(entityResult.reason?.message || 'Could not load graph entities.');
    if (historyResult.status === 'fulfilled') { setHistory(historyResult.value.items || []); setTotal(historyResult.value.total || 0); }
    else setError((current) => current || historyResult.reason?.message || 'Could not load supplier history.');
    setLoading(false);
  }, [selectedOrgId]);
  useEffect(() => { setResult(null); setSelectedHistoryId(''); }, [selectedOrgId]);
  useEffect(() => { load(); }, [load]);

  const submit = async (event) => {
    event.preventDefault(); setBusy(true); setFormError(''); setResult(null);
    const countryList = (value) => value.split(/[\s,;]+/).map((item) => item.trim().toUpperCase()).filter(Boolean);
    try {
      const payload = { required_function: form.required_function.trim(), required_role: form.required_role.trim() || null, required_country_codes: countryList(form.required_country_codes), excluded_country_codes: countryList(form.excluded_country_codes), limit: Number(form.limit) };
      const created = await apiRequest(`/organizations/${selectedOrgId}/entities/${form.affected_entity_id}/alternative-suppliers`, { method: 'POST', body: JSON.stringify(payload) });
      setResult(created); setSelectedHistoryId(created.id); pushNotice('Alternative-supplier assessment saved to history.'); await load();
    } catch (err) { setFormError(err.message); } finally { setBusy(false); }
  };

  const filteredHistory = history.filter((item) => `${item.required_function} ${item.required_role || ''} ${item.result_status} ${item.id}`.toLowerCase().includes(search.toLowerCase()));
  const selectedHistory = result || history.find((item) => item.id === selectedHistoryId) || null;
  return <div className="page-stack">
    <PageHeader title="Alternative suppliers" description="Find graph entities that may serve a required function, with explicit evidence and verification gaps. Matching is deterministic, not a vendor certification." actions={<button className="button button-secondary" onClick={load} disabled={loading}><RefreshCw size={15} /> Refresh history</button>}>
      {selectedOrg && <div className="context-line"><span className="context-dot" /><strong>{selectedOrg.name}</strong><span className="context-separator">·</span>Function-based supplier matching</div>}
    </PageHeader>
    <Alert tone="info">A candidate match does not prove capacity, quality, certification, contractual readiness or immediate interchangeability. Review identity, evidence passages and missing information before acting.</Alert>
    {!selectedOrgId && <Card><EmptyState icon={Truck} title="Select an organization" description="Alternative recommendations are scoped to the selected organization's supply-chain graph." /></Card>}
    {error && <Alert tone="error">{error}</Alert>}
    {selectedOrgId && <div className="alternatives-layout">
      <Card className="alternative-form-card"><div className="card-heading"><div><h2>Find candidates</h2><p>Describe the function and optional constraints.</p></div><ArrowRightLeft size={19} className="heading-icon" /></div>
        <form className="form-stack" onSubmit={submit}><ErrorInline message={formError} /><Field label="Affected entity" required><select className="input" required value={form.affected_entity_id} onChange={change('affected_entity_id')}><option value="">Select entity</option>{entities.map((entity) => <option key={entity.id} value={entity.id}>{entity.name} ({entity.entity_type})</option>)}</select></Field><Field label="Required function" required help="Use the function or service to match, not a desired supplier brand."><input className="input" required minLength={2} maxLength={500} value={form.required_function} onChange={change('required_function')} placeholder="e.g. synthetic components" /></Field><Field label="Required supplier role"><input className="input" maxLength={100} value={form.required_role} onChange={change('required_role')} placeholder="e.g. tier one supplier" /></Field><Field label="Required countries" help="Optional two-letter codes, separated by commas."><input className="input input-uppercase" value={form.required_country_codes} onChange={change('required_country_codes')} placeholder="TW, JP" /></Field><Field label="Excluded countries" help="Candidates from these countries are excluded."><input className="input input-uppercase" value={form.excluded_country_codes} onChange={change('excluded_country_codes')} placeholder="CN, RU" /></Field><Field label="Maximum candidates"><select className="input" value={form.limit} onChange={change('limit')}>{[5, 10, 20, 50, 100].map((n) => <option key={n} value={n}>{n}</option>)}</select></Field><button className="button button-primary button-full" disabled={busy || !entities.length}>{busy ? 'Evaluating graph…' : <><Search size={15} /> Find alternatives</>}</button><small className="fine-print">This endpoint uses deterministic graph matching and persists the assessment. No external model is required.</small></form>
      </Card>
      <div className="alternative-results-column">
        {selectedHistory ? <Card><div className="card-heading"><div><h2>{selectedHistory.required_function}</h2><p>Created {formatDate(selectedHistory.created_at)}</p></div><StatusBadge value={selectedHistory.result_status} /></div><div className="assessment-summary"><div><span>Candidates returned</span><strong>{selectedHistory.candidates?.length || 0}</strong></div><div><span>Required role</span><strong>{selectedHistory.required_role || 'Any role'}</strong></div><div><span>Scoring version</span><strong>{selectedHistory.scoring_version}</strong></div></div>{selectedHistory.constraints && <div className="constraints-row">Constraints: {JSON.stringify(selectedHistory.constraints)}</div>}{selectedHistory.candidates?.length ? <div className="candidate-list">{selectedHistory.candidates.map((candidate) => <CandidateCard key={`${selectedHistory.id}-${candidate.entity_id}`} candidate={candidate} />)}</div> : <EmptyState icon={Truck} title="No candidates found" description="The graph did not contain enough evidence-backed relationships for this function and constraint set." />}</Card> : <Card><EmptyState icon={Truck} title="Run an assessment" description="Matching results will appear here with candidate evidence, rationale and missing information." /></Card>}
      </div>
    </div>}
    <Card padding={false}><div className="table-toolbar"><div className="table-toolbar-title"><strong>Assessment history</strong><span>{total} saved assessments</span></div><label className="filter-search"><Search size={15} /><input placeholder="Search past assessments" value={search} onChange={(event) => setSearch(event.target.value)} /></label></div>{filteredHistory.length ? <div className="table-wrap"><table className="data-table"><thead><tr><th>Function</th><th>Result</th><th>Candidates</th><th>Created</th><th></th></tr></thead><tbody>{filteredHistory.map((item) => <tr key={item.id} className={item.id === selectedHistoryId ? 'selected-row' : ''}><td><strong>{item.required_function}</strong><small className="table-subtext">{item.required_role || 'Any role'}</small></td><td><StatusBadge value={item.result_status} /></td><td>{item.candidates?.length || 0}</td><td>{formatDate(item.created_at)}</td><td><button className="button button-ghost button-small" onClick={() => { setResult(null); setSelectedHistoryId(item.id); }}>View <CheckCircle2 size={13} /></button></td></tr>)}</tbody></table></div> : <EmptyState icon={ArrowRightLeft} title="No saved assessments yet" description="The history list updates after an assessment is generated." />}</Card>
  </div>;
}
