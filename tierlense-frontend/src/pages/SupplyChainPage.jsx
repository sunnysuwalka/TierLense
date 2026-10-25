import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { AlertTriangle, ArrowDown, ArrowLeftRight, ArrowRight, Building2, ChevronDown, CircleDot, Eye, GitBranch, Link2, Plus, RefreshCw, Search, ShieldCheck, Workflow, X } from 'lucide-react';
import { apiRequest, queryString } from '../api/client.js';
import { useApp } from '../context/AppContext.jsx';
import { Alert, Card, EmptyState, ErrorInline, Field, formatDate, JsonBlock, LoadingState, Modal, PageHeader, StatusBadge } from '../components/Shared.jsx';

const RELATION_TYPES = ['supplies', 'provides_component', 'provides_service', 'owns', 'operates', 'located_in', 'manufactures_for', 'distributes_to', 'depends_on', 'board_relationship', 'country_dependency', 'other_dependency'];
const ENTITY_TYPES = ['organization', 'facility', 'component', 'service', 'country', 'person', 'other'];

function GraphView({ nodes, relationships, onSelect, selectedId }) {
  const layout = useMemo(() => {
    const buckets = new Map();
    nodes.forEach((node) => {
      const depth = Number(node.depth ?? 0);
      if (!buckets.has(depth)) buckets.set(depth, []);
      buckets.get(depth).push(node);
    });
    const depths = [...buckets.keys()].sort((a, b) => a - b);
    const maxDepth = depths.length ? Math.max(...depths) : 0;
    const width = Math.max(930, (maxDepth + 1) * 290 + 100);
    const coords = new Map();
    depths.forEach((depth) => {
      const items = buckets.get(depth);
      items.forEach((node, index) => coords.set(node.entity.id, { x: 42 + depth * 290, y: 42 + index * 108, depth, node }));
    });
    const height = Math.max(240, ...[...buckets.values()].map((items) => items.length * 108 + 70));
    return { buckets, depths, coords, width, height, maxDepth };
  }, [nodes]);
  const byId = new Map(nodes.map((node) => [node.entity.id, node]));
  if (!nodes.length) return <EmptyState icon={GitBranch} title="No graph nodes to display" description="Add an entity or select an organization with a recorded supply-chain graph." />;
  return <div className="graph-viewport"><div className="graph-canvas" style={{ width: layout.width, height: layout.height }}>
    <svg className="graph-edges" width={layout.width} height={layout.height} aria-hidden="true">
      <defs><marker id="edge-arrow" markerWidth="7" markerHeight="7" refX="5" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6 z" fill="#a3a3a3" /></marker></defs>
      {relationships.map((edge) => {
        const source = layout.coords.get(edge.source_entity_id); const target = layout.coords.get(edge.target_entity_id);
        if (!source || !target) return null;
        const forward = source.depth <= target.depth;
        const sx = source.x + (forward ? 196 : 0); const sy = source.y + 34;
        const tx = target.x + (forward ? 0 : 196); const ty = target.y + 34;
        const bend = Math.max(38, Math.abs(tx - sx) * 0.42);
        const d = `M ${sx} ${sy} C ${sx + (forward ? bend : -bend)} ${sy}, ${tx - (forward ? bend : -bend)} ${ty}, ${tx} ${ty}`;
        return <g key={edge.id}><path d={d} fill="none" stroke="#b8b8b8" strokeWidth="1.4" markerEnd="url(#edge-arrow)" /><title>{edge.relationship_type.replaceAll('_', ' ')}</title></g>;
      })}
    </svg>
    {layout.depths.map((depth) => <div className="graph-column" key={depth} style={{ left: 42 + depth * 290, height: layout.height }}><div className="graph-tier-label">{depth === 0 ? 'Root / direct' : `Tier ${depth}`}</div>{layout.buckets.get(depth).map((node) => {
      const entity = node.entity; const point = layout.coords.get(entity.id);
      return <button key={entity.id} className={`graph-node ${selectedId === entity.id ? 'selected' : ''} ${entity.is_root ? 'root-node' : ''}`} style={{ left: 0, top: point.y - 4 }} onClick={() => onSelect(node)} title={entity.name}>
        <span className={`entity-avatar entity-${entity.entity_type}`}><Building2 size={15} /></span><span className="graph-node-content"><strong>{entity.name}</strong><small>{entity.entity_type.replaceAll('_', ' ')}{entity.country_code ? ` · ${entity.country_code}` : ''}</small><span className="graph-node-status"><span className={`status-dot-small ${entity.identity_status}`} />{entity.identity_status.replaceAll('_', ' ')}</span></span><span className="graph-node-chevron"><ArrowRight size={13} /></span>
      </button>;
    })}</div>)}
  </div></div>;
}

export default function SupplyChainPage() {
  const { selectedOrg, selectedOrgId, pushNotice } = useApp();
  const [entities, setEntities] = useState([]);
  const [entityTotal, setEntityTotal] = useState(0);
  const [relationships, setRelationships] = useState([]);
  const [graph, setGraph] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [query, setQuery] = useState('');
  const [direction, setDirection] = useState('both');
  const [maxDepth, setMaxDepth] = useState('4');
  const [selectedNode, setSelectedNode] = useState(null);
  const [entityModal, setEntityModal] = useState(false);
  const [relationshipModal, setRelationshipModal] = useState(false);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState('');
  const [entityForm, setEntityForm] = useState({ name: '', entity_type: 'organization', country_code: '', aliases: '', attributes: '{}' });
  const [edgeForm, setEdgeForm] = useState({ source_entity_id: '', target_entity_id: '', relationship_type: 'supplies', component_or_service: '', evidence_document_id: '', source_passage: '', confidence: '0.7', country_code: '' });
  const [likelihood, setLikelihood] = useState(null);
  const [impact, setImpact] = useState(null);
  const [actionLoading, setActionLoading] = useState('');

  const load = useCallback(async () => {
    if (!selectedOrgId) { setEntities([]); setRelationships([]); setGraph(null); return; }
    setLoading(true); setError(''); setLikelihood(null); setImpact(null);
    const params = queryString({ direction, max_depth: Number(maxDepth) });
    const results = await Promise.allSettled([
      apiRequest(`/supply-chain/organizations/${selectedOrgId}/entities?limit=200${query ? `&q=${encodeURIComponent(query)}` : ''}`),
      apiRequest(`/supply-chain/organizations/${selectedOrgId}/relationships?limit=200`),
      apiRequest(`/supply-chain/organizations/${selectedOrgId}/graph${params}`),
    ]);
    if (results[0].status === 'fulfilled') { setEntities(results[0].value.items || []); setEntityTotal(results[0].value.total || 0); }
    else setError(results[0].reason?.message || 'Could not load graph entities.');
    if (results[1].status === 'fulfilled') setRelationships(results[1].value.items || []);
    else setError((current) => current || results[1].reason?.message || 'Could not load graph relationships.');
    if (results[2].status === 'fulfilled') {
      const nextGraph = results[2].value; setGraph(nextGraph);
      setSelectedNode((current) => current ? nextGraph.nodes.find((node) => node.entity.id === current.entity.id) || null : null);
    } else setError((current) => current || results[2].reason?.message || 'Could not load graph traversal.');
    setLoading(false);
  }, [selectedOrgId, direction, maxDepth, query]);
  useEffect(() => { load(); }, [load]);

  const visibleNodes = graph?.nodes || [];
  const visibleEdges = graph?.relationships || [];
  const onEntityFormChange = (key) => (event) => setEntityForm((current) => ({ ...current, [key]: event.target.value }));
  const onEdgeFormChange = (key) => (event) => setEdgeForm((current) => ({ ...current, [key]: event.target.value }));

  const createEntity = async (event) => {
    event.preventDefault(); setSaving(true); setFormError('');
    try {
      let attributes = {};
      try { attributes = JSON.parse(entityForm.attributes || '{}'); } catch { throw new Error('Attributes must be valid JSON.'); }
      const payload = { name: entityForm.name.trim(), entity_type: entityForm.entity_type, country_code: entityForm.country_code.trim().toUpperCase() || null, aliases: entityForm.aliases.split(/[\n,]/).map((x) => x.trim()).filter(Boolean), attributes };
      const result = await apiRequest(`/supply-chain/organizations/${selectedOrgId}/entities`, { method: 'POST', body: JSON.stringify(payload) });
      setEntityModal(false); setEntityForm({ name: '', entity_type: 'organization', country_code: '', aliases: '', attributes: '{}' });
      pushNotice(result.note || `Entity ${result.entity?.name || ''} saved.`); await load();
    } catch (err) { setFormError(err.message); } finally { setSaving(false); }
  };

  const createRelationship = async (event) => {
    event.preventDefault(); setSaving(true); setFormError('');
    try {
      const payload = { source_entity_id: edgeForm.source_entity_id, target_entity_id: edgeForm.target_entity_id, relationship_type: edgeForm.relationship_type, evidence_document_id: edgeForm.evidence_document_id.trim(), source_passage: edgeForm.source_passage.trim(), component_or_service: edgeForm.component_or_service.trim() || null, confidence: Number(edgeForm.confidence || 0.7), country_code: edgeForm.country_code.trim().toUpperCase() || null };
      const result = await apiRequest(`/supply-chain/organizations/${selectedOrgId}/relationships`, { method: 'POST', body: JSON.stringify(payload) });
      setRelationshipModal(false); setEdgeForm({ source_entity_id: '', target_entity_id: '', relationship_type: 'supplies', component_or_service: '', evidence_document_id: '', source_passage: '', confidence: '0.7', country_code: '' });
      pushNotice(result.note || 'Relationship saved.'); await load();
    } catch (err) { setFormError(err.message); } finally { setSaving(false); }
  };

  const runLikelihood = async () => {
    if (!selectedNode) return;
    setActionLoading('likelihood'); setError(''); setLikelihood(null);
    try { setLikelihood(await apiRequest(`/supply-chain/organizations/${selectedOrgId}/entities/${selectedNode.entity.id}/likelihood`)); }
    catch (err) { setError(err.message); }
    finally { setActionLoading(''); }
  };
  const runImpact = async () => {
    if (!selectedNode) return;
    setActionLoading('impact'); setError(''); setImpact(null);
    try { setImpact(await apiRequest(`/supply-chain/organizations/${selectedOrgId}/impact${queryString({ entity_id: selectedNode.entity.id, max_depth: 4 })}`)); }
    catch (err) { setError(err.message); }
    finally { setActionLoading(''); }
  };

  return <div className="page-stack">
    <PageHeader title="Supply chain graph" description="Explore upstream and downstream dependencies with explicit tiers, identity status and source-linked relationships." actions={<><button className="button button-secondary" onClick={() => load()} disabled={loading}><RefreshCw size={15} /> Refresh graph</button><button className="button button-secondary" onClick={() => { setFormError(''); setRelationshipModal(true); }} disabled={!selectedOrgId || entities.length < 2}><Link2 size={15} /> Add relationship</button><button className="button button-primary" onClick={() => { setFormError(''); setEntityModal(true); }} disabled={!selectedOrgId}><Plus size={15} /> Add entity</button></>}>
      {selectedOrg && <div className="context-line"><span className="context-dot" /><strong>{selectedOrg.name}</strong><span className="context-separator">·</span>{entityTotal} graph entities</div>}
    </PageHeader>
    {!selectedOrgId && <Card><EmptyState icon={GitBranch} title="Select an organization" description="Select an organization to inspect its supply-chain graph." /></Card>}
    {error && <Alert tone="error">{error}</Alert>}
    {selectedOrgId && <>
      <div className="graph-toolbar card card-padded"><div className="graph-toolbar-title"><div><strong>Dependency map</strong><span>{visibleNodes.length} nodes · {visibleEdges.length} relationship edges in current traversal</span></div></div><div className="toolbar-filters"><label className="filter-search"><Search size={15} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Filter entities" /></label><label className="compact-select-label"><span>Direction</span><select className="input" value={direction} onChange={(event) => setDirection(event.target.value)}><option value="both">Upstream + downstream</option><option value="upstream">Upstream</option><option value="downstream">Downstream</option></select></label><label className="compact-select-label"><span>Depth</span><select className="input" value={maxDepth} onChange={(event) => setMaxDepth(event.target.value)}><option value="1">1 tier</option><option value="2">2 tiers</option><option value="3">3 tiers</option><option value="4">4 tiers</option><option value="5">5 tiers</option><option value="6">6 tiers</option><option value="8">8 tiers</option></select></label></div></div>
      {loading && !graph ? <Card><LoadingState label="Tracing dependency paths…" /></Card> : <Card padding={false} className="graph-panel"><div className="graph-legend"><span><span className="legend-line" /> Evidence-backed relationship</span><span><span className="legend-dot legend-root" /> Root organization</span><span><span className="legend-dot legend-review" /> Identity review</span><span className="graph-note">Select a node to inspect it</span></div><GraphView nodes={visibleNodes} relationships={visibleEdges} onSelect={setSelectedNode} selectedId={selectedNode?.entity?.id} /></Card>}
      <div className="supply-lower-grid">
        <Card padding={false}><div className="table-toolbar"><div className="table-toolbar-title"><strong>Entities</strong><span>{entities.length} returned</span></div><label className="filter-search"><Search size={15} /><input placeholder="Filter loaded list" value={query} onChange={(event) => setQuery(event.target.value)} /></label></div>{entities.length ? <div className="table-wrap table-max-height"><table className="data-table"><thead><tr><th>Entity</th><th>Type</th><th>Country</th><th>Identity</th></tr></thead><tbody>{entities.filter((entity) => entity.name.toLowerCase().includes(query.toLowerCase())).map((entity) => <tr key={entity.id} className={selectedNode?.entity?.id === entity.id ? 'selected-row' : ''} onClick={() => setSelectedNode(visibleNodes.find((n) => n.entity.id === entity.id) || { entity, depth: 0 })}><td><strong>{entity.name}</strong>{entity.is_root && <small className="table-subtext">Root entity</small>}</td><td>{entity.entity_type}</td><td>{entity.country_code || '—'}</td><td><StatusBadge value={entity.identity_status} /></td></tr>)}</tbody></table></div> : <EmptyState icon={Building2} title="No entities returned" />}</Card>
        <Card><div className="card-heading"><div><h2>{selectedNode?.entity?.name || 'Entity details'}</h2><p>{selectedNode ? 'Inspect identity and calculate deterministic exposure signals.' : 'Select any node on the map or in the entity list.'}</p></div><CircleDot size={18} className="heading-icon" /></div>
          {selectedNode ? <div className="selected-entity-panel"><div className="detail-rows"><div><span>Type</span><strong>{selectedNode.entity.entity_type}</strong></div><div><span>Country</span><strong>{selectedNode.entity.country_code || 'Not recorded'}</strong></div><div><span>Identity status</span><strong><StatusBadge value={selectedNode.entity.identity_status} /></strong></div><div><span>Resolution confidence</span><strong>{Math.round((selectedNode.entity.resolution_confidence || 0) * 100)}%</strong></div><div><span>Entity ID</span><strong className="mono truncate-text">{selectedNode.entity.id}</strong></div></div><div className="selected-entity-actions"><button className="button button-secondary button-small" onClick={runImpact} disabled={!!actionLoading}>{actionLoading === 'impact' ? 'Calculating…' : <><ArrowDown size={14} /> Calculate impact</>}</button><button className="button button-secondary button-small" onClick={runLikelihood} disabled={!!actionLoading}>{actionLoading === 'likelihood' ? 'Assessing…' : <><ShieldCheck size={14} /> Assess signal</>}</button></div>
            {likelihood && <div className="signal-result"><div className="signal-result-top"><span>Experimental signal index</span><strong>{likelihood.experimental_index}</strong></div><StatusBadge value={likelihood.band} /><p>{likelihood.caveat}</p>{likelihood.rationale?.map((line, i) => <div className="rationale-row" key={i}>• {line}</div>)}</div>}
            {impact && <div className="impact-result"><div className="signal-result-top"><span>Downstream impact</span><strong>{impact.affected_entities?.length || 0} affected entities</strong></div>{impact.affected_entities?.length ? impact.affected_entities.map((item) => <div className="impact-item" key={item.entity.id}><strong>{item.entity.name}</strong><span>{item.exposure_reason}</span></div>) : <p className="muted-text">No downstream entities returned for this traversal.</p>}</div>}
            <div className="fine-print">Impact and signal results depend on recorded graph coverage. The signal index is experimental, not a calibrated probability.</div>
          </div> : <EmptyState icon={Eye} title="No node selected" description="Select a node to see its identity, country and graph actions." />}
        </Card>
      </div>
      <Card padding={false}><div className="table-toolbar"><div className="table-toolbar-title"><strong>Evidence-backed relationships</strong><span>{relationships.length} returned</span></div><span className="muted-text">Relationship details include source passage and validation status.</span></div>{relationships.length ? <div className="table-wrap"><table className="data-table"><thead><tr><th>From</th><th>Relationship</th><th>To</th><th>Function</th><th>Validation</th><th>Evidence</th></tr></thead><tbody>{relationships.map((edge) => <tr key={edge.id}><td><strong>{edge.source_entity_name}</strong></td><td><span className="relationship-type">{edge.relationship_type.replaceAll('_', ' ')}</span></td><td><strong>{edge.target_entity_name}</strong></td><td>{edge.component_or_service || '—'}</td><td><StatusBadge value={edge.validation_status} /></td><td><button className="text-link" onClick={() => { navigator.clipboard?.writeText(edge.evidence_document_id); pushNotice('Evidence document ID copied.'); }}>Copy ID <ArrowRight size={13} /></button></td></tr>)}</tbody></table></div> : <EmptyState icon={Link2} title="No relationships recorded" description="Relationships must be linked to a saved evidence document and validated source passage." />}</Card>
    </>}

    <Modal open={entityModal} title="Add graph entity" description="Register a node without fuzzy auto-merging. Similar names may require manual identity review." onClose={() => !saving && setEntityModal(false)} footer={<><button className="button button-secondary" onClick={() => setEntityModal(false)} disabled={saving}>Cancel</button><button className="button button-primary" form="entity-form" disabled={saving}>{saving ? 'Saving…' : 'Save entity'}</button></>}>
      <form id="entity-form" className="form-stack" onSubmit={createEntity}><ErrorInline message={formError} /><Field label="Entity name" required><input className="input" required maxLength={500} value={entityForm.name} onChange={onEntityFormChange('name')} /></Field><div className="form-grid form-grid-two"><Field label="Entity type" required><select className="input" value={entityForm.entity_type} onChange={onEntityFormChange('entity_type')}>{ENTITY_TYPES.map((type) => <option key={type} value={type}>{type.replaceAll('_', ' ')}</option>)}</select></Field><Field label="Country code"><input className="input input-uppercase" maxLength={2} value={entityForm.country_code} onChange={onEntityFormChange('country_code')} placeholder="TW" /></Field></div><Field label="Aliases" help="Comma- or newline-separated known aliases."><textarea className="input textarea" rows={2} value={entityForm.aliases} onChange={onEntityFormChange('aliases')} /></Field><Field label="Attributes (JSON)"><textarea className="input textarea mono" rows={3} value={entityForm.attributes} onChange={onEntityFormChange('attributes')} /></Field></form>
    </Modal>
    <Modal open={relationshipModal} title="Add evidence-backed relationship" description="The API validates the passage against the stored evidence document before saving this directed link." onClose={() => !saving && setRelationshipModal(false)} wide footer={<><button className="button button-secondary" onClick={() => setRelationshipModal(false)} disabled={saving}>Cancel</button><button className="button button-primary" form="edge-form" disabled={saving}>{saving ? 'Saving…' : 'Save relationship'}</button></>}>
      <form id="edge-form" className="form-stack" onSubmit={createRelationship}><ErrorInline message={formError} /><div className="form-grid form-grid-two"><Field label="Source entity" required><select className="input" required value={edgeForm.source_entity_id} onChange={onEdgeFormChange('source_entity_id')}><option value="">Select source</option>{entities.map((entity) => <option value={entity.id} key={entity.id}>{entity.name}</option>)}</select></Field><Field label="Target entity" required><select className="input" required value={edgeForm.target_entity_id} onChange={onEdgeFormChange('target_entity_id')}><option value="">Select target</option>{entities.map((entity) => <option value={entity.id} key={entity.id}>{entity.name}</option>)}</select></Field><Field label="Relationship type" required><select className="input" value={edgeForm.relationship_type} onChange={onEdgeFormChange('relationship_type')}>{RELATION_TYPES.map((type) => <option key={type} value={type}>{type.replaceAll('_', ' ')}</option>)}</select></Field><Field label="Component / service"><input className="input" maxLength={500} value={edgeForm.component_or_service} onChange={onEdgeFormChange('component_or_service')} placeholder="What is supplied or provided?" /></Field><Field label="Evidence document ID" required><input className="input mono" required value={edgeForm.evidence_document_id} onChange={onEdgeFormChange('evidence_document_id')} placeholder="UUID of the stored source document" /></Field><Field label="Country code"><input className="input input-uppercase" maxLength={2} value={edgeForm.country_code} onChange={onEdgeFormChange('country_code')} placeholder="TW" /></Field></div><Field label="Source passage" required help="Paste the exact excerpt present in the stored evidence document (minimum 12 characters)."><textarea className="input textarea" required minLength={12} maxLength={5000} rows={4} value={edgeForm.source_passage} onChange={onEdgeFormChange('source_passage')} /></Field><Field label="Confidence (0–1)"><input className="input" type="number" min="0" max="1" step="0.05" value={edgeForm.confidence} onChange={onEdgeFormChange('confidence')} /></Field><div className="alert alert-info"><ShieldCheck size={17} /><div>Save only a relationship that is supported by the quoted source. A persisted passage match confirms source alignment, not necessarily independent truth.</div></div></form>
    </Modal>
  </div>;
}
