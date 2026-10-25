import React, { useEffect, useState } from 'react';
import { CheckCircle2, CircleHelp, ExternalLink, RefreshCw, Save, Server, Settings2, ShieldCheck, Wifi, XCircle } from 'lucide-react';
import { checkApi, getApiBase, setApiBase } from '../api/client.js';
import { useApp } from '../context/AppContext.jsx';
import { Alert, Card, Field, formatDate, PageHeader, StatusBadge } from '../components/Shared.jsx';

export default function SettingsPage() {
  const { apiStatus, apiError, lastChecked, checkConnection, refreshOrganizations, pushNotice } = useApp();
  const [apiBase, setApiBaseValue] = useState(getApiBase());
  const [savedBase, setSavedBase] = useState(getApiBase());
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [messageTone, setMessageTone] = useState('success');
  const [health, setHealth] = useState(null);

  useEffect(() => { setApiBaseValue(getApiBase()); setSavedBase(getApiBase()); }, []);
  const testConnection = async () => {
    setBusy(true); setMessage(''); setMessageTone('success'); setHealth(null);
    try {
      const result = await checkApi(); setHealth(result); await checkConnection();
      if (result.ready?.error) { setMessageTone('warning'); setMessage(`Liveness responded, but readiness check failed: ${result.ready.error}`); return false; }
      setMessage('Backend liveness and database readiness responded.');
      return true;
    } catch (error) { setMessageTone('error'); setMessage(error.message); return false; }
    finally { setBusy(false); }
  };
  const saveBase = async (event) => {
    event.preventDefault(); setBusy(true); setMessage('');
    try {
      const nextBase = setApiBase(apiBase);
      setApiBaseValue(nextBase); setSavedBase(nextBase);
      await refreshOrganizations().catch(() => {});
      const connected = await testConnection();
      pushNotice(connected ? 'API base URL saved and verified.' : 'API base URL saved, but the connection could not be verified.', connected ? 'success' : 'error');
    } catch (error) { setMessageTone('error'); setMessage(error.message); }
    finally { setBusy(false); }
  };

  return <div className="page-stack">
    <PageHeader title="API & preferences" description="Connect the workspace to your local FastAPI backend and review the current service status." />
    <div className="settings-grid">
      <Card><div className="card-heading"><div><h2>API endpoint</h2><p>The frontend communicates with the `/api/v1` endpoints used by TierLense.</p></div><Server size={18} className="heading-icon" /></div>
        <form className="form-stack" onSubmit={saveBase}><Field label="API base URL" required help="Default: http://127.0.0.1:8000/api/v1. If you enter only the host, /api/v1 is appended automatically."><input className="input mono" required value={apiBase} onChange={(event) => setApiBaseValue(event.target.value)} placeholder="http://127.0.0.1:8000/api/v1" /></Field><div className="form-actions"><button className="button button-primary" disabled={busy}>{busy ? 'Checking…' : <><Save size={15} /> Save & verify</>}</button><button className="button button-secondary" type="button" disabled={busy} onClick={testConnection}><RefreshCw size={15} /> Test current URL</button></div></form>
        {message && <Alert tone={messageTone}>{message}</Alert>}
        <div className="connection-details"><div><span>Connection status</span><strong><StatusBadge value={apiStatus} /></strong></div><div><span>Last checked</span><strong>{formatDate(lastChecked)}</strong></div><div><span>Saved API URL</span><strong className="mono">{savedBase}</strong></div><div><span>Health details</span><strong>{health ? JSON.stringify(health.live) : apiError || 'Not checked in this session'}</strong></div></div>
      </Card>
      <Card><div className="card-heading"><div><h2>Workspace configuration</h2><p>Current frontend behavior and available service endpoints.</p></div><Settings2 size={18} className="heading-icon" /></div>
        <div className="settings-feature-list"><div><div className="feature-icon"><ShieldCheck size={17} /></div><span><strong>Backend-owned persistence</strong><small>Organizations, graph entities, jobs, evidence and recommendations are saved by the API.</small></span><StatusBadge value="connected" /></div><div><div className="feature-icon"><Wifi size={17} /></div><span><strong>Local API integration</strong><small>No hard-coded demo records are shown when the backend is unavailable.</small></span><StatusBadge value="active" /></div><div><div className="feature-icon"><CircleHelp size={17} /></div><span><strong>Evidence caveats</strong><small>Source passage validation indicates traceability; risk indexes are not calibrated probabilities.</small></span><StatusBadge value="documented" /></div></div>
        <div className="settings-links"><a href={`${savedBase.replace(/\/api\/v\d+$/i, '')}/docs`} target="_blank" rel="noreferrer">Open FastAPI Swagger docs <ExternalLink size={14} /></a><a href={`${savedBase}/health/live`} target="_blank" rel="noreferrer">Open liveness endpoint <ExternalLink size={14} /></a><a href={`${savedBase}/health/ready`} target="_blank" rel="noreferrer">Open readiness endpoint <ExternalLink size={14} /></a></div>
      </Card>
    </div>
    <Card><div className="card-heading"><div><h2>Before production use</h2><p>This frontend is a local development workspace, not an authentication boundary.</p></div><ShieldCheck size={18} className="heading-icon" /></div><div className="safeguard-grid"><div><CheckCircle2 size={17} /><div><strong>Provider calls require a job runner</strong><p>Queueing investigation jobs can trigger external providers when the worker is active. Leave the worker stopped during model-free acceptance testing.</p></div></div><div><CheckCircle2 size={17} /><div><strong>Credentials stay server-side</strong><p>Configure provider keys in backend environment settings. This frontend has no provider-key field and does not store secrets.</p></div></div><div><XCircle size={17} /><div><strong>Authentication is not implemented here</strong><p>The reviewed API surface has no login/session contract. Restrict backend access to trusted local users until API authentication and authorization are available.</p></div></div></div></Card>
  </div>;
}
