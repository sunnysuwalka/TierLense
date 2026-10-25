import React, { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { ArrowLeft, Building2, Globe, Save, ShieldCheck } from 'lucide-react';
import { apiRequest } from '../api/client.js';
import { useApp } from '../context/AppContext.jsx';
import { Alert, Card, ErrorInline, Field, formatDate, LoadingState, PageHeader, StatusBadge } from '../components/Shared.jsx';

function splitList(values) { return Array.isArray(values) ? values.join(', ') : ''; }

export default function OrganizationDetailPage() {
  const { organizationId } = useParams();
  const navigate = useNavigate();
  const { setSelectedOrgId, refreshOrganizations, pushNotice } = useApp();
  const [org, setOrg] = useState(null);
  const [form, setForm] = useState(null);
  const [profile, setProfile] = useState(null);
  const [loading, setLoading] = useState(true);
  const [savingOrg, setSavingOrg] = useState(false);
  const [savingProfile, setSavingProfile] = useState(false);
  const [error, setError] = useState('');

  const load = async () => {
    setLoading(true); setError('');
    try {
      const data = await apiRequest(`/organizations/${organizationId}`);
      setOrg(data); setSelectedOrgId(data.id);
      setForm({ name: data.name || '', website: data.website || '', country_code: data.country_code || '', description: data.description || '' });
      const wp = data.watch_profile || {};
      setProfile({ dependency_role: wp.dependency_role || 'supplier', products_services: splitList(wp.products_services), dependency_context: wp.dependency_context || '', criticality: wp.criticality || 'medium', identity_clues: splitList(wp.identity_clues) });
    } catch (err) { setError(err.message); } finally { setLoading(false); }
  };
  useEffect(() => { load(); }, [organizationId]);

  const update = (setState, key) => (event) => setState((current) => ({ ...current, [key]: event.target.value }));
  const saveOrg = async (event) => {
    event.preventDefault(); setSavingOrg(true); setError('');
    try {
      const payload = { name: form.name.trim(), website: form.website.trim() || null, country_code: form.country_code.trim().toUpperCase() || null, description: form.description.trim() || null };
      const updated = await apiRequest(`/organizations/${organizationId}`, { method: 'PATCH', body: JSON.stringify(payload) });
      setOrg((current) => ({ ...current, ...updated }));
      await refreshOrganizations(); pushNotice('Organization details saved.');
    } catch (err) { setError(err.message); } finally { setSavingOrg(false); }
  };
  const saveProfile = async (event) => {
    event.preventDefault(); setSavingProfile(true); setError('');
    try {
      const payload = { dependency_role: profile.dependency_role.trim(), products_services: profile.products_services.split(/[\n,]/).map((x) => x.trim()).filter(Boolean), dependency_context: profile.dependency_context.trim() || null, criticality: profile.criticality, identity_clues: profile.identity_clues.split(/[\n,]/).map((x) => x.trim()).filter(Boolean) };
      const saved = await apiRequest(`/organizations/${organizationId}/watch-profile`, { method: 'PUT', body: JSON.stringify(payload) });
      setOrg((current) => ({ ...current, watch_profile: saved }));
      await refreshOrganizations(); pushNotice('Watch profile saved.');
    } catch (err) { setError(err.message); } finally { setSavingProfile(false); }
  };

  if (loading) return <LoadingState label="Loading organization profile…" />;
  if (error && !org) return <div className="page-stack"><Alert tone="error">{error}</Alert><button className="button button-secondary" onClick={() => navigate('/organizations')}><ArrowLeft size={15} /> Organization registry</button></div>;
  return <div className="page-stack">
    <PageHeader title={org.name} description="Maintain the organization record and the dependency profile used to focus investigations." actions={<><button className="button button-secondary" onClick={() => navigate('/organizations')}><ArrowLeft size={15} /> Registry</button><button className="button button-primary" onClick={() => navigate('/investigations')}>View investigations</button></>}>
      <div className="context-line"><StatusBadge value={org.identity_status} /><span>Created {formatDate(org.created_at, false)}</span><span className="context-separator">·</span><span className="mono">{org.id}</span></div>
    </PageHeader>
    {error && <Alert tone="error">{error}</Alert>}
    <div className="settings-grid">
      <Card><div className="card-heading"><div><h2>Organization details</h2><p>Core information used to identify the monitored entity.</p></div><Building2 size={18} className="heading-icon" /></div>
        <form className="form-stack" onSubmit={saveOrg}><Field label="Name" required><input className="input" required value={form.name} onChange={update(setForm, 'name')} /></Field><Field label="Website"><input className="input" type="url" placeholder="https://example.com" value={form.website} onChange={update(setForm, 'website')} /></Field><Field label="Country code"><input className="input input-uppercase" maxLength={2} placeholder="US" value={form.country_code} onChange={update(setForm, 'country_code')} /></Field><Field label="Description"><textarea className="input textarea" rows={4} value={form.description} onChange={update(setForm, 'description')} /></Field><div className="form-actions"><button className="button button-primary" disabled={savingOrg}>{savingOrg ? 'Saving…' : <><Save size={15} /> Save details</>}</button></div></form>
      </Card>
      <Card><div className="card-heading"><div><h2>Watch profile</h2><p>Describe the dependency and its business criticality.</p></div><ShieldCheck size={18} className="heading-icon" /></div>
        <form className="form-stack" onSubmit={saveProfile}><Field label="Dependency role" required><input className="input" required maxLength={100} value={profile.dependency_role} onChange={update(setProfile, 'dependency_role')} /></Field><Field label="Products / services" help="Separate entries with commas or new lines."><textarea className="input textarea" rows={3} value={profile.products_services} onChange={update(setProfile, 'products_services')} placeholder="Key services, components or product lines" /></Field><Field label="Criticality"><select className="input" value={profile.criticality} onChange={update(setProfile, 'criticality')}><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option><option value="critical">Critical</option></select></Field><Field label="Dependency context"><textarea className="input textarea" rows={3} maxLength={5000} value={profile.dependency_context} onChange={update(setProfile, 'dependency_context')} placeholder="How this organization depends on the monitored entity" /></Field><Field label="Identity clues" help="Separate aliases and trusted identifiers with commas or new lines."><textarea className="input textarea" rows={3} value={profile.identity_clues} onChange={update(setProfile, 'identity_clues')} /></Field><div className="form-actions"><button className="button button-primary" disabled={savingProfile}>{savingProfile ? 'Saving…' : <><Save size={15} /> Save watch profile</>}</button></div></form>
      </Card>
    </div>
    <Card><div className="card-heading"><div><h2>API record</h2></div><Globe size={18} className="heading-icon" /></div><div className="data-list"><div><dt>Organization ID</dt><dd className="mono">{org.id}</dd></div><div><dt>Created</dt><dd>{formatDate(org.created_at)}</dd></div><div><dt>Last updated</dt><dd>{formatDate(org.updated_at)}</dd></div><div><dt>Identity status</dt><dd><StatusBadge value={org.identity_status} /></dd></div></div></Card>
  </div>;
}
