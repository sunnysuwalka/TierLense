import React, { useCallback, useEffect, useState } from 'react';
import { CalendarClock, CheckCircle2, Clock3, History, RefreshCw, Save, ScrollText } from 'lucide-react';
import { apiRequest } from '../api/client.js';
import { useApp } from '../context/AppContext.jsx';
import { Alert, Card, EmptyState, ErrorInline, Field, formatDate, JsonBlock, LoadingState, PageHeader, StatusBadge } from '../components/Shared.jsx';

export default function HistoryPage() {
  const { selectedOrg, selectedOrgId, pushNotice } = useApp();
  const [schedule, setSchedule] = useState(null);
  const [scheduleForm, setScheduleForm] = useState({ enabled: true, interval_minutes: 1440 });
  const [snapshots, setSnapshots] = useState([]);
  const [snapshotTotal, setSnapshotTotal] = useState(0);
  const [changes, setChanges] = useState([]);
  const [selectedSnapshot, setSelectedSnapshot] = useState(null);
  const [loading, setLoading] = useState(false);
  const [savingSchedule, setSavingSchedule] = useState(false);
  const [error, setError] = useState('');
  const [scheduleError, setScheduleError] = useState('');
  const [activeTab, setActiveTab] = useState('snapshots');

  const load = useCallback(async () => {
    if (!selectedOrgId) { setSchedule(null); setSnapshots([]); setChanges([]); return; }
    setLoading(true); setError('');
    const results = await Promise.allSettled([
      apiRequest(`/organizations/${selectedOrgId}/scan-schedule`),
      apiRequest(`/organizations/${selectedOrgId}/history?limit=100`),
      apiRequest(`/organizations/${selectedOrgId}/evidence-changes?limit=200`),
    ]);
    if (results[0].status === 'fulfilled') { setSchedule(results[0].value); setScheduleForm({ enabled: results[0].value.enabled, interval_minutes: results[0].value.interval_minutes }); }
    else setError(results[0].reason?.message || 'Could not load scan schedule.');
    if (results[1].status === 'fulfilled') { setSnapshots(results[1].value.items || []); setSnapshotTotal(results[1].value.total || 0); }
    else setError((current) => current || results[1].reason?.message || 'Could not load history.');
    if (results[2].status === 'fulfilled') setChanges(results[2].value || []);
    else setError((current) => current || results[2].reason?.message || 'Could not load evidence changes.');
    setLoading(false);
  }, [selectedOrgId]);
  useEffect(() => { load(); }, [load]);

  const saveSchedule = async (event) => {
    event.preventDefault(); setSavingSchedule(true); setScheduleError('');
    try {
      const payload = { enabled: Boolean(scheduleForm.enabled), interval_minutes: Number(scheduleForm.interval_minutes) };
      const saved = await apiRequest(`/organizations/${selectedOrgId}/scan-schedule`, { method: 'PUT', body: JSON.stringify(payload) });
      setSchedule(saved); setScheduleForm({ enabled: saved.enabled, interval_minutes: saved.interval_minutes });
      pushNotice('Recurring scan schedule saved.');
    } catch (err) { setScheduleError(err.message); }
    finally { setSavingSchedule(false); }
  };

  const viewSnapshot = async (snapshot) => {
    setSelectedSnapshot({ loading: true, id: snapshot.id });
    try { setSelectedSnapshot(await apiRequest(`/organizations/${selectedOrgId}/history/${snapshot.id}`)); }
    catch (err) { setSelectedSnapshot({ id: snapshot.id, error: err.message }); }
  };

  return <div className="page-stack">
    <PageHeader title="History & operations" description="Configure recurring scans, inspect point-in-time investigation snapshots and review detected changes to source content." actions={<button className="button button-secondary" onClick={load} disabled={loading}><RefreshCw size={15} /> Refresh</button>}>
      {selectedOrg && <div className="context-line"><span className="context-dot" /><strong>{selectedOrg.name}</strong><span className="context-separator">·</span>Schedule and history</div>}
    </PageHeader>
    {error && <Alert tone="error">{error}</Alert>}
    {!selectedOrgId && <Card><EmptyState icon={History} title="Select an organization" description="Schedules, snapshots and evidence changes are organization-specific." /></Card>}
    {selectedOrgId && <>
      <div className="history-layout">
        <Card className="schedule-settings-card"><div className="card-heading"><div><h2>Scan schedule</h2><p>Configure the automated investigation cadence.</p></div><CalendarClock size={18} className="heading-icon" /></div>
          {schedule ? <><div className="schedule-state"><div className="schedule-state-icon"><Clock3 size={19} /></div><div><strong>{schedule.enabled ? 'Schedule enabled' : 'Schedule paused'}</strong><span>Next run {formatDate(schedule.next_run_at)}</span></div><StatusBadge value={schedule.enabled ? 'enabled' : 'paused'} /></div><form className="form-stack" onSubmit={saveSchedule}><ErrorInline message={scheduleError} /><label className="toggle-row"><span><strong>Recurring scans</strong><small>Enabling a schedule lets the autonomous scheduler enqueue periodic jobs.</small></span><input type="checkbox" checked={scheduleForm.enabled} onChange={(event) => setScheduleForm((current) => ({ ...current, enabled: event.target.checked }))} /></label><Field label="Interval (minutes)"><input className="input" type="number" min="15" max="10080" required value={scheduleForm.interval_minutes} onChange={(event) => setScheduleForm((current) => ({ ...current, interval_minutes: Number(event.target.value) }))} /><small className="field-help">Accepted range: 15–10,080 minutes. Saved changes reset the next run time.</small></Field><button className="button button-primary button-full" disabled={savingSchedule}>{savingSchedule ? 'Saving…' : <><Save size={15} /> Save schedule</>}</button></form><div className="detail-rows schedule-meta"><div><span>Last successful run</span><strong>{formatDate(schedule.last_success_at)}</strong></div><div><span>Last enqueued</span><strong>{formatDate(schedule.last_enqueued_at)}</strong></div><div><span>Last job ID</span><strong className="mono">{schedule.last_job_id || 'Not recorded'}</strong></div></div><Alert tone="info">Saving schedule settings is a local API write. If the worker is running, future scheduled jobs may use configured external providers.</Alert></> : <LoadingState label="Loading recurring schedule…" />}
        </Card>
        <Card className="history-summary-card"><div className="card-heading"><div><h2>Historical snapshots</h2><p>Immutable summaries of completed investigations.</p></div><History size={18} className="heading-icon" /></div><div className="history-summary-number"><strong>{snapshotTotal}</strong><span>saved snapshots</span></div>{snapshots[0] ? <div className="latest-snapshot"><span>Latest snapshot</span><strong>{formatDate(snapshots[0].snapshot_at)}</strong><small>{snapshots[0].job_type.replaceAll('_', ' ')} · {snapshots[0].id.slice(0, 8)}…</small></div> : <p className="muted-text">No completed investigation snapshots recorded.</p>}<div className="history-summary-stats"><div><strong>{changes.length}</strong><span>Evidence changes</span></div><div><strong>{snapshots.reduce((sum, s) => sum + (s.evidence_document_ids?.length || 0), 0)}</strong><span>Document links in loaded snapshots</span></div></div></Card>
      </div>
      <Card padding={false}><div className="tabs-bar"><button className={activeTab === 'snapshots' ? 'active' : ''} onClick={() => setActiveTab('snapshots')}><History size={15} /> Snapshots <span>{snapshotTotal}</span></button><button className={activeTab === 'changes' ? 'active' : ''} onClick={() => setActiveTab('changes')}><ScrollText size={15} /> Evidence changes <span>{changes.length}</span></button></div>
        {activeTab === 'snapshots' ? (snapshots.length ? <div className="table-wrap"><table className="data-table"><thead><tr><th>Snapshot</th><th>Job type</th><th>Evidence docs</th><th>Graph entities</th><th>Disruptions</th><th>Recorded at</th><th></th></tr></thead><tbody>{snapshots.map((snapshot) => <tr key={snapshot.id}><td><strong className="mono">{snapshot.id.slice(0, 13)}…</strong><small className="table-subtext">Job {snapshot.job_id.slice(0, 8)}…</small></td><td><span className="capitalize">{snapshot.job_type.replaceAll('_', ' ')}</span></td><td>{snapshot.evidence_document_ids?.length || 0}</td><td>{snapshot.graph_entity_ids?.length || 0}</td><td>{snapshot.disruption_event_ids?.length || 0}</td><td>{formatDate(snapshot.snapshot_at)}</td><td><button className="button button-ghost button-small" onClick={() => viewSnapshot(snapshot)}>Inspect</button></td></tr>)}</tbody></table></div> : <EmptyState icon={History} title="No historical snapshots" description="A snapshot is created after an investigation completes." />) : (changes.length ? <div className="table-wrap"><table className="data-table"><thead><tr><th>Change</th><th>Type</th><th>Reassessment</th><th>Detected at</th><th>Document hashes</th></tr></thead><tbody>{changes.map((change) => <tr key={change.id}><td><strong className="mono">{change.id.slice(0, 13)}…</strong><small className="table-subtext">Source {change.source_id.slice(0, 8)}…</small></td><td><StatusBadge value={change.change_type} /></td><td><StatusBadge value={change.reassessment_status} /></td><td>{formatDate(change.detected_at)}</td><td><div className="hash-pair"><span>Previous: {change.previous_content_hash?.slice(0, 10) || '—'}</span><span>Current: {change.current_content_hash?.slice(0, 10) || '—'}</span></div></td></tr>)}</tbody></table></div> : <EmptyState icon={ScrollText} title="No evidence changes detected" description="When a source's stored content hash changes, TierLense records the revision and reassessment outcome here. A scan with no fetched documents may not exercise this workflow." />)}
      </Card>
      {selectedSnapshot && <Card><div className="card-heading"><div><h2>{selectedSnapshot.loading ? 'Loading snapshot…' : selectedSnapshot.error ? 'Snapshot could not be loaded' : `Snapshot ${selectedSnapshot.id.slice(0, 8)}…`}</h2></div><button className="button button-secondary button-small" onClick={() => setSelectedSnapshot(null)}>Close</button></div>{selectedSnapshot.loading ? <LoadingState /> : selectedSnapshot.error ? <Alert tone="error">{selectedSnapshot.error}</Alert> : <div className="snapshot-detail-grid"><div><h3 className="section-title">Result summary</h3><JsonBlock value={selectedSnapshot.result_summary} /></div><div><h3 className="section-title">Graph snapshot</h3><JsonBlock value={selectedSnapshot.graph_snapshot} /></div><div><h3 className="section-title">Evidence and record IDs</h3><JsonBlock value={{ evidence_document_ids: selectedSnapshot.evidence_document_ids, finding_ids: selectedSnapshot.finding_ids, graph_entity_ids: selectedSnapshot.graph_entity_ids, graph_relationship_ids: selectedSnapshot.graph_relationship_ids, disruption_event_ids: selectedSnapshot.disruption_event_ids, risk_assessment_ids: selectedSnapshot.risk_assessment_ids, evidence_change_ids: selectedSnapshot.evidence_change_ids }} /></div></div>}</Card>}
    </>}
  </div>;
}
