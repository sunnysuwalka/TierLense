import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  AlertTriangle, ArrowRight, ArrowUpRight, BookOpenText, Building2,
  Clock3, FileText, GitBranch, Network, RefreshCw, ShieldCheck, Workflow,
} from 'lucide-react';
import { apiRequest } from '../api/client.js';
import { useApp } from '../context/AppContext.jsx';
import {
  Alert, Card, EmptyState, formatDate, formatNumber, LoadingState,
  MetricCard, PageHeader, StatusBadge,
} from '../components/Shared.jsx';

function plural(value, singular, pluralLabel = `${singular}s`) {
  return `${value} ${value === 1 ? singular : pluralLabel}`;
}

function NetworkMap({ entities, relationships, onOpen }) {
  const nodes = useMemo(() => {
    if (!entities.length) return [];
    const root = entities.find((item) => item.is_root || Number(item.depth) === 0) || entities[0];
    return [root, ...entities.filter((item) => item.id !== root.id)].slice(0, 8);
  }, [entities]);

  const layout = useMemo(() => {
    if (!nodes.length) return { coords: new Map(), levels: new Map(), maxLevel: 0 };
    const nodeIds = new Set(nodes.map((node) => node.id));
    const validEdges = relationships.filter((edge) => nodeIds.has(edge.source_entity_id) && nodeIds.has(edge.target_entity_id));
    const adjacency = new Map(nodes.map((node) => [node.id, []]));
    validEdges.forEach((edge) => {
      adjacency.get(edge.source_entity_id)?.push(edge.target_entity_id);
      adjacency.get(edge.target_entity_id)?.push(edge.source_entity_id);
    });
    const root = nodes[0];
    const levels = new Map([[root.id, 0]]);
    const queue = [root.id];
    while (queue.length) {
      const current = queue.shift();
      (adjacency.get(current) || []).forEach((next) => {
        if (!levels.has(next)) {
          levels.set(next, levels.get(current) + 1);
          queue.push(next);
        }
      });
    }
    nodes.forEach((node) => { if (!levels.has(node.id)) levels.set(node.id, 0); });
    const maxLevel = Math.max(0, ...levels.values());
    const byLevel = new Map();
    nodes.forEach((node) => {
      const level = levels.get(node.id);
      if (!byLevel.has(level)) byLevel.set(level, []);
      byLevel.get(level).push(node);
    });
    const coords = new Map();
    byLevel.forEach((items, level) => {
      items.forEach((node, index) => {
        const x = maxLevel === 0 ? 300 : 16 + level * (600 / maxLevel);
        const y = 20 + ((index + 1) * (320 / (items.length + 1))) - 31;
        coords.set(node.id, { x, y, level, node });
      });
    });
    return { coords, levels, maxLevel, validEdges };
  }, [nodes, relationships]);

  if (!nodes.length) {
    return <div className="network-empty"><Network size={28} /><strong>No supply-chain graph yet</strong><span>Add entities and evidence-backed relationships to map dependencies.</span></div>;
  }

  const validEdges = layout.validEdges || [];
  return <div className="network-map-viewport">
    <div className="network-map" role="img" aria-label={`Supply chain graph showing ${nodes.length} entities and ${validEdges.length} relationships`}>
      <svg className="network-map-edges" viewBox="0 0 780 360" preserveAspectRatio="xMinYMin meet" aria-hidden="true">
        <defs>
          <marker id="network-arrow" markerWidth="7" markerHeight="7" refX="5.5" refY="3.5" orient="auto"><path d="M0,0 L7,3.5 L0,7 z" fill="#a3a3a3" /></marker>
        </defs>
        {validEdges.map((edge) => {
          const source = layout.coords.get(edge.source_entity_id);
          const target = layout.coords.get(edge.target_entity_id);
          if (!source || !target) return null;
          const sx = source.x < target.x ? source.x + 158 : source.x + 4;
          const tx = source.x < target.x ? target.x + 4 : target.x + 158;
          const sy = source.y + 31;
          const ty = target.y + 31;
          const bend = Math.max(28, Math.abs(tx - sx) * 0.4);
          const curve = `M ${sx} ${sy} C ${sx + (source.x < target.x ? bend : -bend)} ${sy}, ${tx - (source.x < target.x ? bend : -bend)} ${ty}, ${tx} ${ty}`;
          return <path key={edge.id} d={curve} fill="none" stroke="#b8b8b8" strokeWidth="1.5" markerEnd="url(#network-arrow)" />;
        })}
      </svg>
      {nodes.map((node) => {
        const point = layout.coords.get(node.id);
        return <button
          type="button"
          key={node.id}
          className={`network-node ${node.id === nodes[0].id ? 'network-node-root' : ''}`}
          style={{ left: point.x, top: point.y }}
          onClick={onOpen}
          title={`${node.name} — open supply chain graph`}
        >
          <span className="network-node-icon"><Building2 size={16} /></span>
          <span className="network-node-copy"><strong>{node.name}</strong><small>{String(node.entity_type || 'entity').replaceAll('_', ' ')}{node.country_code ? ` · ${node.country_code}` : ''}</small></span>
          <span className={`network-identity-dot ${node.identity_status || 'unknown'}`} />
        </button>;
      })}
    </div>
  </div>;
}

function SeverityChart({ disruptions }) {
  const counts = [1, 2, 3, 4, 5].map((level) => ({
    level,
    count: disruptions.filter((event) => Number(event.severity || event.severity_score || 0) === level).length,
  }));
  const max = Math.max(1, ...counts.map((item) => item.count));
  return <div className="severity-chart">
    {counts.map(({ level, count }) => <div className="severity-row" key={level}>
      <span className="severity-label">{level}</span>
      <div className="severity-track"><span className={`severity-fill severity-fill-${level}`} style={{ width: `${count ? Math.max(4, count / max * 100) : 0}%` }} /></div>
      <strong>{count}</strong>
    </div>)}
    <div className="chart-scale"><span>Lower severity</span><span>Higher severity</span></div>
    {!disruptions.length && <p className="chart-empty-note">No disruption signals recorded for this organization.</p>}
  </div>;
}

function EntityMixChart({ entities }) {
  const types = ['organization', 'facility', 'component', 'service', 'country', 'other'];
  const counts = types.map((type) => ({ type, count: entities.filter((item) => (item.entity_type || 'other') === type).length })).filter((item) => item.count > 0);
  const max = Math.max(1, ...counts.map((item) => item.count));
  if (!counts.length) return <div className="chart-empty-note">Entity type distribution will appear once graph entities are available.</div>;
  return <div className="entity-mix-chart">{counts.map(({ type, count }) => <div className="entity-mix-row" key={type}>
    <div className="entity-mix-label"><span>{type.replaceAll('_', ' ')}</span><strong>{count}</strong></div>
    <div className="entity-mix-track"><span style={{ width: `${Math.max(5, count / max * 100)}%` }} /></div>
  </div>)}</div>;
}

export default function DashboardPage() {
  const { selectedOrg, selectedOrgId, apiStatus, organizationsLoading } = useApp();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    if (!selectedOrgId) { setData(null); setLoading(false); return; }
    setLoading(true);
    setError('');
    const results = await Promise.allSettled([
      apiRequest(`/supply-chain/organizations/${selectedOrgId}/entities?limit=200`),
      apiRequest(`/supply-chain/organizations/${selectedOrgId}/relationships?limit=200`),
      apiRequest(`/supply-chain/organizations/${selectedOrgId}/disruptions?limit=100`),
      apiRequest(`/organizations/${selectedOrgId}/investigation-jobs?limit=10`),
      apiRequest(`/organizations/${selectedOrgId}/scan-schedule`),
      apiRequest(`/organizations/${selectedOrgId}/history?limit=10`),
      apiRequest(`/organizations/${selectedOrgId}/evidence-changes?limit=20`),
    ]);
    const [entities, relationships, disruptions, jobs, schedule, history, changes] = results.map((item) => item.status === 'fulfilled' ? item.value : null);
    const failed = results.find((item) => item.status === 'rejected');
    setData({ entities, relationships, disruptions, jobs, schedule, history, changes });
    if (failed) setError(failed.reason?.message || 'Some dashboard data could not be loaded.');
    setLoading(false);
  }, [selectedOrgId]);

  useEffect(() => { load(); }, [load]);

  const entities = data?.entities?.items || [];
  const relationships = data?.relationships?.items || [];
  const disruptions = data?.disruptions?.items || [];
  const jobs = data?.jobs?.items || [];
  const completedJobs = jobs.filter((job) => job.status === 'completed').length;
  const pendingJobs = jobs.filter((job) => ['queued', 'running'].includes(job.status)).length;
  const reviewCount = entities.filter((entity) => ['needs_review', 'unverified'].includes(entity.identity_status)).length;
  const urgentDisruptions = disruptions.filter((event) => Number(event.severity || event.severity_score || 0) >= 4).length;
  const latestJob = jobs[0];
  const resultSummary = latestJob?.result_summary || {};
  const recentStatusCount = ['completed', 'running', 'queued', 'failed'].map((status) => ({ status, count: jobs.filter((job) => job.status === status).length }));
  const maxStatusCount = Math.max(1, ...recentStatusCount.map((item) => item.count));
  const historyCount = data?.history?.total ?? data?.history?.items?.length ?? 0;
  const changeCount = Array.isArray(data?.changes) ? data.changes.length : data?.changes?.items?.length || 0;

  return <div className="page-stack dashboard-page">
    <PageHeader
      title="Supply chain overview"
      description={selectedOrg ? `${selectedOrg.name}${selectedOrg.country_code ? ` · ${selectedOrg.country_code}` : ''}` : 'Your monitored organizations, dependencies and risk signals.'}
      actions={<>
        <button className="button button-secondary" onClick={() => load()} disabled={loading}><RefreshCw size={16} className={loading ? 'spin' : ''} /> Refresh</button>
        <button className="button button-primary" onClick={() => navigate('/organizations')}><Building2 size={16} /> Add organization</button>
      </>}
    >
      {selectedOrg && <div className="context-line"><span className="context-dot" /><span>Monitoring active organization</span><StatusBadge value={selectedOrg.identity_status} /></div>}
    </PageHeader>

    {apiStatus === 'offline' && <Alert tone="warning">Backend unavailable. Start FastAPI and check the connection in settings.</Alert>}
    {error && <Alert tone="warning">Some panels could not be loaded: {error}</Alert>}

    {!selectedOrgId && !organizationsLoading && <Card><EmptyState icon={Building2} title="Add your first organization" description="Start a monitored workspace to see its suppliers, evidence and disruption signals." action={<button className="button button-primary" onClick={() => navigate('/organizations')}>Add organization <ArrowRight size={16} /></button>} /></Card>}
    {selectedOrgId && loading && !data && <LoadingState label="Loading supply-chain data…" />}

    {selectedOrgId && data && <>
      <section className="metric-grid metric-grid-four dashboard-kpis">
        <MetricCard label="Graph entities" value={formatNumber(data.entities?.total ?? entities.length)} detail={`${reviewCount} need review`} icon={GitBranch} tone="blue" onClick={() => navigate('/supply-chain')} />
        <MetricCard label="Relationships" value={formatNumber(data.relationships?.total ?? relationships.length)} detail="Recorded dependencies" icon={Workflow} tone="slate" onClick={() => navigate('/supply-chain')} />
        <MetricCard label="Disruption signals" value={formatNumber(data.disruptions?.total ?? disruptions.length)} detail={`${urgentDisruptions} high severity`} icon={AlertTriangle} tone={urgentDisruptions ? 'amber' : 'slate'} onClick={() => navigate('/disruptions')} />
        <MetricCard label="Evidence changes" value={formatNumber(changeCount)} detail="Source revisions detected" icon={BookOpenText} tone="green" onClick={() => navigate('/history')} />
      </section>

      <Card className="network-card">
        <div className="card-heading card-heading-large">
          <div><h2>Supply network</h2></div>
          <button className="text-link" onClick={() => navigate('/supply-chain')}>Open graph <ArrowUpRight size={16} /></button>
        </div>
        <div className="network-map-stats"><span><i className="legend-dot legend-dot-blue" /> {plural(entities.length, 'entity', 'entities')}</span><span><i className="legend-dot legend-dot-grey" /> {plural(relationships.length, 'relationship')}</span></div>
        <NetworkMap entities={entities} relationships={relationships} onOpen={() => navigate('/supply-chain')} />
        <div className="network-card-footer"><span>{relationships.length ? 'Showing recorded relationships' : 'No connected relationships in this view'}</span><span>Source-grounded graph</span></div>
      </Card>

      <section className="dashboard-grid dashboard-grid-two">
        <Card className="risk-card">
          <div className="card-heading card-heading-large"><div><h2>Severity distribution</h2></div><AlertTriangle size={19} className="heading-icon" /></div>
          <div className="risk-summary"><div><strong>{disruptions.length}</strong><span>Total signals</span></div><div className={urgentDisruptions ? 'risk-summary-alert' : ''}><strong>{urgentDisruptions}</strong><span>Severity 4–5</span></div></div>
          <SeverityChart disruptions={disruptions} />
          <button className="button button-secondary button-full" onClick={() => navigate('/disruptions')}>Review disruptions <ArrowRight size={16} /></button>
        </Card>
        <Card className="entity-mix-card">
          <div className="card-heading card-heading-large"><div><h2>Entity composition</h2></div><button className="icon-button" title="Open supply chain" onClick={() => navigate('/supply-chain')}><ArrowUpRight size={17} /></button></div>
          <EntityMixChart entities={entities} />
          <div className="entity-mix-footer"><span><ShieldCheck size={15} /> {entities.filter((item) => item.identity_status === 'verified').length} verified</span><span>{reviewCount} require review</span></div>
        </Card>
      </section>

      <Card padding={false} className="jobs-card">
        <div className="card-heading card-heading-padded"><div><h2>Investigations</h2></div><button className="text-link" onClick={() => navigate('/investigations')}>All runs <ArrowRight size={15} /></button></div>
        <div className="job-status-strip">
          {recentStatusCount.map(({ status, count }) => <div key={status} className="job-status-item"><div className="job-status-heading"><span>{status}</span><strong>{count}</strong></div><div className="job-status-track"><span className={`job-status-fill ${status}`} style={{ width: `${count ? Math.max(6, count / maxStatusCount * 100) : 0}%` }} /></div></div>)}
        </div>
        {jobs.length ? <div className="table-wrap"><table className="data-table"><thead><tr><th>Investigation</th><th>Status</th><th>Completed / scheduled</th><th>Attempts</th></tr></thead><tbody>{jobs.slice(0, 5).map((job) => <tr key={job.id} className="clickable-row" onClick={() => navigate('/investigations')}><td><strong>{String(job.job_type || 'investigation').replaceAll('_', ' ')}</strong><small className="table-subtext">{job.id.slice(0, 8)}…</small></td><td><StatusBadge value={job.status} /></td><td>{formatDate(job.finished_at || job.scheduled_at)}</td><td>{job.attempt_count ?? '—'}</td></tr>)}</tbody></table></div> : <div className="compact-empty"><Clock3 size={23} /><span>No investigation runs yet</span></div>}
      </Card>


      {latestJob && <Card className="evidence-pipeline-card">
        <div className="card-heading card-heading-large"><div><h2>Evidence pipeline</h2><p>Latest run: {formatDate(latestJob.finished_at || latestJob.updated_at || latestJob.scheduled_at)}</p></div><StatusBadge value={latestJob.status} /></div>
        <div className="pipeline-steps">
          {[
            ['Sources found', resultSummary.sources_discovered],
            ['Relevant', resultSummary.sources_relevant],
            ['Documents fetched', resultSummary.documents_fetched],
            ['Passages verified', resultSummary.passages_verified],
          ].map(([label, value], index) => <div className={`pipeline-step ${index === 3 ? 'pipeline-step-last' : ''}`} key={label}><span className="pipeline-step-index">0{index + 1}</span><div><strong>{value ?? '—'}</strong><span>{label}</span></div></div>)}
        </div>
        <div className="pipeline-note"><FileText size={15} /><span>{resultSummary.needs_review_findings ?? 0} items need review</span><span className="pipeline-note-divider" /><span>{historyCount} saved snapshots</span><button className="text-link" onClick={() => navigate('/history')}>View history <ArrowRight size={15} /></button>
        </div>
      </Card>}
    </>}
  </div>;
}
