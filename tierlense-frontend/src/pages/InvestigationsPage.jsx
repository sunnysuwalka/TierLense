import React, { useCallback, useEffect, useState } from 'react';
import { Activity, AlertTriangle, ArrowRight, CalendarClock, ChevronDown, ClipboardList, RefreshCw, Search, X } from 'lucide-react';
import { apiRequest } from '../api/client.js';
import { useApp } from '../context/AppContext.jsx';
import { Alert, Card, EmptyState, ErrorInline, formatDate, formatNumber, LoadingState, Modal, PageHeader, StatusBadge } from '../components/Shared.jsx';

const SUMMARY_GROUPS = [
  {
    title: 'Source discovery',
    keys: ['sources_discovered', 'sources_relevant', 'sources_skipped', 'identity_rejected_sources', 'fetch_failures', 'documents_fetched', 'documents_reused', 'demo_sources_seeded_locally', 'demo_documents_seeded_locally', 'evidence_changes_detected'],
  },
  {
    title: 'Findings and validation',
    keys: ['findings_extracted', 'passages_verified', 'demo_findings_seeded_locally', 'unsupported_findings', 'needs_review_findings', 'entities_needing_identity_review'],
  },
  {
    title: 'Supply-chain graph and risk',
    keys: ['graph_entities_created', 'graph_relationships_created', 'disruption_events_created', 'risk_assessments_created_after_change'],
  },
  {
    title: 'Scenario and safeguards',
    keys: ['demo_scenario_id', 'data_status', 'external_model_calls', 'external_provider_http_calls'],
  },
];

const FRIENDLY_LABELS = {
  sources_discovered: 'Sources discovered',
  sources_relevant: 'Relevant sources',
  sources_skipped: 'Sources skipped',
  identity_rejected_sources: 'Sources rejected by identity checks',
  fetch_failures: 'Document fetch failures',
  documents_fetched: 'Documents fetched',
  documents_reused: 'Previously stored documents reused',
  demo_sources_seeded_locally: 'Demo sources added locally',
  demo_documents_seeded_locally: 'Demo documents added locally',
  evidence_changes_detected: 'Evidence changes detected',
  findings_extracted: 'Findings extracted during scan',
  passages_verified: 'Passages checked against evidence',
  demo_findings_seeded_locally: 'Demo findings added locally',
  unsupported_findings: 'Unsupported findings',
  needs_review_findings: 'Findings requiring review',
  entities_needing_identity_review: 'Entities requiring identity review',
  graph_entities_created: 'Supply-chain entities created',
  graph_relationships_created: 'Relationships recorded',
  disruption_events_created: 'Disruption scenarios recorded',
  risk_assessments_created_after_change: 'Risk assessments after evidence changes',
  demo_scenario_id: 'Demo scenario',
  data_status: 'Data classification',
  external_model_calls: 'External model calls',
  external_provider_http_calls: 'External provider requests',
  queue_attempt_count: 'Worker attempts',
  requests: 'Provider requests',
  fallback_requests: 'Fallback requests',
  successes: 'Successful requests',
  failures: 'Failed requests',
  prompt_tokens: 'Input tokens',
  completion_tokens: 'Output tokens',
  total_tokens: 'Total tokens',
  last_attempt_at: 'Last request time',
};

function humanizeKey(key) {
  if (FRIENDLY_LABELS[key]) return FRIENDLY_LABELS[key];
  return String(key)
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .replace(/[_-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/^./, (letter) => letter.toUpperCase());
}

function friendlyValue(key, value) {
  if (value === null || value === undefined || value === '') return 'Not recorded';
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (key === 'demo_scenario_id' && value === 'pds4_army_logistics_v1') return 'PDS-4 Army Logistics (version 1)';
  if (key === 'data_status') return String(value).toUpperCase() === 'SIMULATED' ? 'Simulated demonstration data' : String(value);
  if (key.endsWith('_at')) return formatDate(value);
  if (typeof value === 'number') return formatNumber(value);
  if (Array.isArray(value)) return value.length ? value.map((item) => typeof item === 'object' ? Object.entries(item || {}).map(([k, v]) => `${humanizeKey(k)}: ${friendlyValue(k, v)}`).join(', ') : String(item)).join('; ') : 'None';
  if (typeof value === 'object') return Object.entries(value).map(([k, v]) => `${humanizeKey(k)}: ${friendlyValue(k, v)}`).join(' · ');
  return String(value);
}

function ReadableSummary({ value }) {
  if (!value || typeof value !== 'object' || Array.isArray(value) || Object.keys(value).length === 0) {
    return <p className="readable-empty">No result summary was recorded for this investigation.</p>;
  }

  const consumed = new Set(['message']);
  const groups = SUMMARY_GROUPS.map((group) => {
    const entries = group.keys.filter((key) => Object.prototype.hasOwnProperty.call(value, key)).map((key) => [key, value[key]]);
    entries.forEach(([key]) => consumed.add(key));
    return { title: group.title, entries };
  }).filter((group) => group.entries.length > 0);
  const otherEntries = Object.entries(value).filter(([key]) => !consumed.has(key));

  return <div className="readable-summary">
    {groups.map((group) => <section className="readable-group" key={group.title}>
      <h4>{group.title}</h4>
      <div className="readable-fields">{group.entries.map(([key, fieldValue]) => <div className="readable-field" key={key}>
        <span>{humanizeKey(key)}</span>
        <strong>{key === 'data_status' ? <StatusBadge value={friendlyValue(key, fieldValue)} /> : friendlyValue(key, fieldValue)}</strong>
      </div>)}</div>
    </section>)}
    {otherEntries.length > 0 && <section className="readable-group">
      <h4>Additional details</h4>
      <div className="readable-fields">{otherEntries.map(([key, fieldValue]) => <div className="readable-field" key={key}><span>{humanizeKey(key)}</span><strong>{friendlyValue(key, fieldValue)}</strong></div>)}</div>
    </section>}
    {value.message && <div className="readable-message"><strong>Investigation note</strong><p>{value.message}</p></div>}
  </div>;
}

function ExecutionMetricsPanel({ value }) {
  if (!value || typeof value !== 'object' || Array.isArray(value) || Object.keys(value).length === 0) {
    return <p className="readable-empty">Execution telemetry was not recorded for this job.</p>;
  }
  const totals = value.totals && typeof value.totals === 'object' ? value.totals : {};
  const providers = value.providers && typeof value.providers === 'object' ? value.providers : {};
  const requestTotal = totals.requests ?? Object.values(providers).reduce((sum, provider) => {
    const stages = provider?.stages || {};
    return sum + Object.values(stages).reduce((stageSum, stage) => stageSum + Number(stage?.requests || 0), 0);
  }, 0);
  const summaryMetrics = [
    ['Provider requests', requestTotal],
    ['Successful requests', totals.successes ?? 0],
    ['Failed requests', totals.failures ?? 0],
    ['Fallback requests', totals.fallback_requests ?? 0],
    ['Input tokens', totals.prompt_tokens ?? 0],
    ['Output tokens', totals.completion_tokens ?? 0],
    ['Total tokens', totals.total_tokens ?? 0],
    ['Worker attempts', value.queue_attempt_count ?? 0],
    ['External model calls', value.external_model_calls ?? requestTotal],
  ];
  const hasProviderActivity = Number(requestTotal) > 0 || Object.keys(providers).some((name) => Object.keys(providers[name]?.stages || {}).length > 0);
  const extra = Object.entries(value).filter(([key]) => !['providers', 'totals', 'queue_attempt_count', 'demo_scenario_id', 'external_model_calls'].includes(key));

  return <div className="execution-metrics-panel">
    <div className="execution-metric-grid">{summaryMetrics.map(([label, metric]) => <div className="execution-metric" key={label}><span>{label}</span><strong>{formatNumber(metric)}</strong></div>)}</div>
    {!hasProviderActivity && <div className="readable-message readable-message-info">
      <strong>No external model-provider activity recorded</strong>
      <p>{value.demo_scenario_id ? 'This presentation scenario was populated from local simulated data. No external model calls were made for this job.' : 'No provider requests were recorded for this investigation.'}</p>
    </div>}
    {Object.entries(providers).map(([providerName, provider]) => {
      const stages = provider?.stages && typeof provider.stages === 'object' ? Object.entries(provider.stages) : [];
      if (!stages.length) return null;
      return <section className="readable-group provider-group" key={providerName}>
        <h4>{providerName} provider activity</h4>
        <div className="provider-stage-list">{stages.map(([stageName, stage]) => <div className="provider-stage" key={stageName}>
          <div className="provider-stage-heading"><strong>{humanizeKey(stageName)}</strong><span>{formatNumber(stage.requests ?? 0)} request{Number(stage.requests ?? 0) === 1 ? '' : 's'}</span></div>
          <div className="provider-stage-stats">
            {['successes', 'failures', 'fallback_requests', 'prompt_tokens', 'completion_tokens', 'total_tokens'].filter((key) => stage[key] !== undefined).map((key) => <div key={key}><span>{humanizeKey(key)}</span><strong>{formatNumber(stage[key])}</strong></div>)}
            {stage.models?.length > 0 && <div className="provider-models"><span>Models used</span><strong>{stage.models.join(', ')}</strong></div>}
            {stage.last_attempt_at && <div><span>Last request</span><strong>{formatDate(stage.last_attempt_at)}</strong></div>}
          </div>
        </div>)}</div>
      </section>;
    })}
    {value.demo_scenario_id && <div className="readable-message"><strong>Scenario</strong><p>{friendlyValue('demo_scenario_id', value.demo_scenario_id)}</p></div>}
    {extra.length > 0 && <section className="readable-group"><h4>Additional telemetry</h4><div className="readable-fields">{extra.map(([key, fieldValue]) => <div className="readable-field" key={key}><span>{humanizeKey(key)}</span><strong>{friendlyValue(key, fieldValue)}</strong></div>)}</div></section>}
  </div>;
}

export default function InvestigationsPage() {
  const { selectedOrg, selectedOrgId, pushNotice } = useApp();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [search, setSearch] = useState('');
  const [selectedJob, setSelectedJob] = useState(null);
  const [queueOpen, setQueueOpen] = useState(false);
  const [queueBusy, setQueueBusy] = useState(false);
  const [queueError, setQueueError] = useState('');

  const load = useCallback(async () => {
    if (!selectedOrgId) { setData(null); return; }
    setLoading(true); setError('');
    try { setData(await apiRequest(`/organizations/${selectedOrgId}/investigation-jobs?limit=200`)); }
    catch (err) { setError(err.message); }
    finally { setLoading(false); }
  }, [selectedOrgId]);
  useEffect(() => { load(); }, [load]);

  const jobs = data?.items || [];
  const filtered = jobs.filter((job) => (statusFilter === 'all' || job.status === statusFilter) && `${job.job_type} ${job.id} ${job.progress_message || ''}`.toLowerCase().includes(search.toLowerCase()));
  const queueJob = async () => {
    setQueueBusy(true); setQueueError('');
    try {
      const job = await apiRequest(`/organizations/${selectedOrgId}/investigation-jobs`, { method: 'POST', body: JSON.stringify({ job_type: 'manual_scan' }) });
      setQueueOpen(false); pushNotice(`Manual investigation ${job.id.slice(0, 8)} queued.`); await load();
    } catch (err) { setQueueError(err.message); }
    finally { setQueueBusy(false); }
  };

  return <div className="page-stack">
    <PageHeader title="Investigations" description="Review queued scans, execution status, evidence counts and provider telemetry for the selected organization." actions={<><button className="button button-secondary" onClick={load} disabled={loading}><RefreshCw size={15} /> Refresh</button><button className="button button-primary" onClick={() => { setQueueError(''); setQueueOpen(true); }} disabled={!selectedOrgId}><Activity size={15} /> Queue investigation</button></>}>
      {selectedOrg && <div className="context-line"><span className="context-dot" /><strong>{selectedOrg.name}</strong><span className="context-separator">·</span>Job history</div>}
    </PageHeader>
    <Alert tone="info"><strong>Execution note:</strong> Queueing creates a job record. If the separate worker is running, it may begin source discovery and call configured providers. Do not queue a scan during model-free acceptance testing.</Alert>
    {!selectedOrgId && <Card><EmptyState icon={ClipboardList} title="Select an organization" description="Choose an organization from the header or register one before reviewing investigations." /></Card>}
    {error && <Alert tone="error">{error}</Alert>}
    {selectedOrgId && loading && !data && <LoadingState label="Loading investigations…" />}
    {data && <>
      <div className="metric-grid metric-grid-four compact-metrics"><div className="card card-padded mini-metric"><span>Total shown</span><strong>{formatNumber(data.total ?? jobs.length)}</strong></div><div className="card card-padded mini-metric"><span>Queued</span><strong>{jobs.filter((j) => j.status === 'queued').length}</strong></div><div className="card card-padded mini-metric"><span>Running</span><strong>{jobs.filter((j) => j.status === 'running').length}</strong></div><div className="card card-padded mini-metric"><span>Failed</span><strong>{jobs.filter((j) => j.status === 'failed').length}</strong></div></div>
      <Card padding={false}><div className="table-toolbar"><div className="table-toolbar-title"><strong>Investigation jobs</strong><span>{filtered.length} shown</span></div><div className="toolbar-filters"><label className="filter-search"><Search size={15} /><input placeholder="Search job type or ID" value={search} onChange={(event) => setSearch(event.target.value)} /></label><select className="input filter-select" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}><option value="all">All statuses</option><option value="queued">Queued</option><option value="running">Running</option><option value="completed">Completed</option><option value="failed">Failed</option></select></div></div>
        {filtered.length ? <div className="table-wrap"><table className="data-table"><thead><tr><th>Job</th><th>Status</th><th>Progress</th><th>Scheduled at</th><th>Finished at</th><th>Attempts</th><th></th></tr></thead><tbody>{filtered.map((job) => <tr key={job.id}><td><strong className="capitalize">{job.job_type.replaceAll('_', ' ')}</strong><small className="table-subtext mono">{job.id}</small></td><td><StatusBadge value={job.status} /></td><td><div className="table-progress"><div className="progress-track"><span style={{ width: `${Math.min(100, job.progress_percent ?? (job.status === 'completed' ? 100 : 0))}%` }} /></div><small>{job.progress_percent ?? (job.status === 'completed' ? 100 : 0)}%</small></div>{job.progress_message && <small className="table-subtext">{job.progress_message}</small>}</td><td>{formatDate(job.scheduled_at)}</td><td>{formatDate(job.finished_at)}</td><td>{job.attempt_count ?? 0}</td><td><button className="button button-ghost button-small" onClick={() => setSelectedJob(job)}>Details <ArrowRight size={14} /></button></td></tr>)}</tbody></table></div> : <EmptyState icon={CalendarClock} title="No matching investigation jobs" description="Jobs appear after organization onboarding or when a manual investigation is queued." />}
      </Card>
    </>}

    <Modal open={queueOpen} title="Queue a manual investigation" description={`Create a manual scan job${selectedOrg ? ` for ${selectedOrg.name}` : ''}.`} onClose={() => !queueBusy && setQueueOpen(false)} footer={<><button className="button button-secondary" onClick={() => setQueueOpen(false)} disabled={queueBusy}>Cancel</button><button className="button button-primary" onClick={queueJob} disabled={queueBusy}>{queueBusy ? 'Queueing…' : 'Queue job'}</button></>}>
      <Alert tone="warning"><strong>Provider-use confirmation.</strong> This action may cause external search/model provider calls if the worker is running. For strict model-free testing, leave the worker stopped and cancel this dialog.</Alert><ErrorInline message={queueError} /><div className="confirmation-details"><div><span>Job type</span><strong>manual_scan</strong></div><div><span>Organization</span><strong>{selectedOrg?.name}</strong></div><div><span>Execution</span><strong>Asynchronous worker queue</strong></div></div>
    </Modal>
    <Modal open={!!selectedJob} title="Investigation details" description={selectedJob?.id} onClose={() => setSelectedJob(null)} wide footer={<button className="button button-secondary" onClick={() => setSelectedJob(null)}>Close</button>}>
      {selectedJob && <div className="form-stack"><div className="detail-rows"><div><span>Status</span><strong><StatusBadge value={selectedJob.status} /></strong></div><div><span>Type</span><strong className="capitalize">{selectedJob.job_type.replaceAll('_', ' ')}</strong></div><div><span>Started</span><strong>{formatDate(selectedJob.started_at)}</strong></div><div><span>Finished</span><strong>{formatDate(selectedJob.finished_at)}</strong></div><div><span>Attempts</span><strong>{selectedJob.attempt_count ?? 0}</strong></div><div><span>Error summary</span><strong>{selectedJob.error_summary || 'None recorded'}</strong></div></div><div><h3 className="section-title">Result summary</h3><ReadableSummary value={selectedJob.result_summary} /></div><div><h3 className="section-title">Execution metrics</h3><ExecutionMetricsPanel value={selectedJob.execution_metrics} /></div></div>}
    </Modal>
  </div>;
}
