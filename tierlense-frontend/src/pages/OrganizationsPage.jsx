import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Building2, Plus, RefreshCw, Search, ArrowUpRight } from 'lucide-react';
import { apiRequest } from '../api/client.js';
import { useApp } from '../context/AppContext.jsx';
import { Alert, Card, EmptyState, ErrorInline, Field, formatDate, LoadingState, Modal, PageHeader, StatusBadge } from '../components/Shared.jsx';

const demoForm = {
  name: 'PDS-4 Demo - Army Logistics Spares (SIMULATED)',
  website: 'https://pds4-demo.invalid/',
  country_code: 'IN',
  description: 'SIMULATED presentation fixture for an Army logistics-vehicle preventive-maintenance spares supply chain. All suppliers and disruption scenarios are fictional.',
  dependency_role: 'equipment/spares ecosystem',
  products_services: 'vehicle preventive maintenance spare kits, air and oil filter assemblies, filter media rolls, gasket and O-ring sets',
  dependency_context: 'Fictional demonstration only; use source-linked examples to walk through tiers, ownership exposure, disruption scenarios and alternate candidates.',
  criticality: 'high',
  identity_clues: 'PDS-4 local demo fixture, SIMULATED data only',
};

export default function OrganizationsPage() {
  const { organizations, organizationsLoading, organizationsError, refreshOrganizations, setSelectedOrgId, pushNotice } = useApp();
  const navigate = useNavigate();
  const [query, setQuery] = useState('');
  const [modalOpen, setModalOpen] = useState(false);
  const [form, setForm] = useState(demoForm);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => { refreshOrganizations().catch(() => {}); }, [refreshOrganizations]);
  const filtered = organizations.filter((org) => `${org.name} ${org.website || ''} ${org.country_code || ''} ${org.identity_status || ''}`.toLowerCase().includes(query.toLowerCase()));
  const update = (key) => (event) => setForm((current) => ({ ...current, [key]: event.target.value }));
  const openCreateModal = () => { setError(''); setForm({ ...demoForm }); setModalOpen(true); };

  const createOrganization = async (event) => {
    event.preventDefault(); setBusy(true); setError('');
    const body = {
      name: form.name.trim(), website: form.website.trim() || null, country_code: form.country_code.trim().toUpperCase() || null,
      description: form.description.trim() || null,
      watch_profile: {
        dependency_role: form.dependency_role.trim() || 'supplier',
        products_services: form.products_services.split(/[\n,]/).map((value) => value.trim()).filter(Boolean),
        dependency_context: form.dependency_context.trim() || null,
        criticality: form.criticality,
        identity_clues: form.identity_clues.split(/[\n,]/).map((value) => value.trim()).filter(Boolean),
      },
    };
    try {
      const result = await apiRequest('/organizations', { method: 'POST', body: JSON.stringify(body) });
      const org = result.organization;
      await refreshOrganizations();
      setSelectedOrgId(org.id);
      setModalOpen(false); setForm({ ...demoForm });
      pushNotice(`Organization “${org.name}” registered. Its initial investigation is ${result.initial_investigation?.status || 'queued'}.`);
      navigate(`/organizations/${org.id}`);
    } catch (err) { setError(err.message); } finally { setBusy(false); }
  };

  return <div className="page-stack">
    <PageHeader title="Organizations" description="Manage the companies, suppliers and services TierLense monitors for supply-chain exposure." actions={<><button className="button button-secondary" onClick={() => refreshOrganizations().catch(() => {})} disabled={organizationsLoading}><RefreshCw size={15} /> Refresh</button><button className="button button-primary" onClick={openCreateModal}><Plus size={16} /> Add organization</button></>} />
    {organizationsError && <Alert tone="warning">{organizationsError}</Alert>}
    <Card padding={false}>
      <div className="table-toolbar"><div className="table-toolbar-title"><strong>Organization registry</strong><span>{organizations.length} registered</span></div><label className="filter-search"><Search size={15} /><input placeholder="Search organizations" value={query} onChange={(event) => setQuery(event.target.value)} /></label></div>
      {organizationsLoading && !organizations.length ? <LoadingState label="Loading organization registry…" /> : filtered.length ? <div className="table-wrap"><table className="data-table"><thead><tr><th>Organization</th><th>Country</th><th>Identity</th><th>Watch profile</th><th>Added</th><th></th></tr></thead><tbody>{filtered.map((org) => <tr key={org.id}><td><button className="table-primary-link" onClick={() => { setSelectedOrgId(org.id); navigate(`/organizations/${org.id}`); }}><span className="table-avatar"><Building2 size={16} /></span><span><strong>{org.name}</strong><small className="table-subtext">{org.website || org.id}</small></span></button></td><td>{org.country_code || '—'}</td><td><StatusBadge value={org.identity_status} /></td><td>{org.watch_profile?.criticality ? <StatusBadge value={org.watch_profile.criticality} /> : <span className="muted-text">Not configured</span>}</td><td>{formatDate(org.created_at, false)}</td><td><button className="icon-button" aria-label={`Open ${org.name}`} onClick={() => { setSelectedOrgId(org.id); navigate(`/organizations/${org.id}`); }}><ArrowUpRight size={16} /></button></td></tr>)}</tbody></table></div> : <EmptyState icon={Building2} title={query ? 'No matching organizations' : 'No organizations registered'} description={query ? 'Try another name, website or country code.' : 'Register the organization you want to monitor, then configure its dependency role and criticality.'} action={!query && <button className="button button-primary" onClick={openCreateModal}><Plus size={15} /> Register organization</button>} />}
    </Card>

    <Modal open={modalOpen} title="Register an organization" description="Pre-filled with the PDS-4 simulated presentation scenario. Edit these values to monitor a different organization." wide onClose={() => !busy && setModalOpen(false)} footer={<><button className="button button-secondary" onClick={() => setModalOpen(false)} disabled={busy}>Cancel</button><button className="button button-primary" form="create-org-form" disabled={busy}>{busy ? 'Registering…' : 'Register organization'}</button></>}>
      <form id="create-org-form" onSubmit={createOrganization} className="form-stack">
        <ErrorInline message={error} />
        <div className="alert alert-info"><Building2 size={17} /><div><strong>Presentation demo defaults</strong><br />These values target the local PDS-4 synthetic fixture. To populate the graph, disruptions, evidence and alternatives automatically, enable <code>ENABLE_PDS4_DEMO_SCENARIO=true</code> in the backend API environment. Without that flag, registration follows normal onboarding.</div></div>
        <div className="form-grid form-grid-two"><Field label="Organization name" required><input className="input" required maxLength={255} value={form.name} onChange={update('name')} placeholder="e.g. Acme Manufacturing" /></Field><Field label="Website"><input className="input" type="url" value={form.website} onChange={update('website')} placeholder="https://example.com" /></Field><Field label="Country code" help="Two-letter ISO country code, such as US or IN."><input className="input input-uppercase" maxLength={2} value={form.country_code} onChange={update('country_code')} placeholder="US" /></Field><Field label="Dependency role" required><input className="input" required maxLength={100} value={form.dependency_role} onChange={update('dependency_role')} placeholder="e.g. component supplier" /></Field></div>
        <Field label="Description"><textarea className="input textarea" rows={2} maxLength={10000} value={form.description} onChange={update('description')} placeholder="What does this organization provide or represent?" /></Field>
        <div className="form-grid form-grid-two"><Field label="Products / services" help="Separate entries with commas or new lines."><textarea className="input textarea" rows={3} value={form.products_services} onChange={update('products_services')} placeholder="Power modules, semiconductor packaging" /></Field><Field label="Identity clues" help="Known aliases, legal identifiers or trusted domains."><textarea className="input textarea" rows={3} value={form.identity_clues} onChange={update('identity_clues')} placeholder="Known company aliases, registry details" /></Field></div>
        <Field label="Dependency context"><textarea className="input textarea" rows={2} maxLength={5000} value={form.dependency_context} onChange={update('dependency_context')} placeholder="How does your organization depend on this entity?" /></Field>
        <Field label="Criticality"><select className="input" value={form.criticality} onChange={update('criticality')}><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option><option value="critical">Critical</option></select></Field>
        <div className="alert alert-info"><Building2 size={17} /><div>The demo uses fictional, clearly labelled data. It is not an actual Indian Army procurement network or a real-world risk assessment.</div></div>
      </form>
    </Modal>
  </div>;
}
