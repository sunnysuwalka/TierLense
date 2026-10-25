import React, { useMemo, useState } from 'react';
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
import {
  Activity, AlertTriangle, ArrowDownUp, BookOpenText, Building2, ChevronDown,
  CircleHelp, ClipboardList, Command, Gauge, GitBranch, History, LayoutDashboard,
  Menu, Network, RefreshCw, Search, Settings2, ShieldCheck, Truck, X,
} from 'lucide-react';
import { useApp } from '../context/AppContext.jsx';
import { getApiBase } from '../api/client.js';

const navGroups = [
  { title: 'Workspace', items: [
    { to: '/', label: 'Overview', icon: LayoutDashboard, end: true },
    { to: '/organizations', label: 'Organizations', icon: Building2 },
    { to: '/investigations', label: 'Investigations', icon: ClipboardList },
  ]},
  { title: 'Intelligence', items: [
    { to: '/supply-chain', label: 'Supply chain graph', icon: GitBranch },
    { to: '/disruptions', label: 'Disruptions & impact', icon: AlertTriangle },
    { to: '/evidence', label: 'Evidence library', icon: BookOpenText },
  ]},
  { title: 'Resilience', items: [
    { to: '/alternatives', label: 'Alternative suppliers', icon: Truck },
    { to: '/history', label: 'History & operations', icon: History },
  ]},
  { title: 'Configuration', items: [
    { to: '/settings', label: 'API & preferences', icon: Settings2 },
  ]},
];

const routeTitles = {
  '/': ['Workspace', 'Overview'], '/organizations': ['Workspace', 'Organizations'],
  '/investigations': ['Workspace', 'Investigations'], '/supply-chain': ['Intelligence', 'Supply chain graph'],
  '/disruptions': ['Intelligence', 'Disruptions & impact'], '/evidence': ['Intelligence', 'Evidence library'],
  '/alternatives': ['Resilience', 'Alternative suppliers'], '/history': ['Resilience', 'History & operations'],
  '/settings': ['Configuration', 'API & preferences'],
};

function SidebarNav({ onNavigate }) {
  return <nav className="sidebar-nav">{navGroups.map((group) => <div className="nav-group" key={group.title}><div className="nav-group-label">{group.title}</div>{group.items.map(({ to, label, icon: Icon, end }) => <NavLink key={to} to={to} end={end} onClick={onNavigate} className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}><Icon size={17} strokeWidth={1.8} /><span>{label}</span></NavLink>)}</div>)}</nav>;
}

function SidebarContent({ onNavigate }) {
  const { apiStatus, selectedOrg, organizations } = useApp();
  return <div className="sidebar-inner">
    <div className="brand-lockup"><div className="brand-mark"><Network size={19} strokeWidth={2.2} /></div><div><div className="brand-name">TierLense</div><div className="brand-subtitle">Supply Chain Intelligence</div></div></div>
    <div className="workspace-switcher"><div className="workspace-avatar"><Building2 size={16} /></div><div className="workspace-copy"><span>Active workspace</span><strong title={selectedOrg?.name || 'No organization selected'}>{selectedOrg?.name || 'No organization selected'}</strong></div></div>
    <SidebarNav onNavigate={onNavigate} />
    <div className="sidebar-bottom"><div className="api-state"><span className={`api-state-dot ${apiStatus}`} /><div><strong>{apiStatus === 'online' ? 'API connected' : apiStatus === 'degraded' ? 'API partially ready' : apiStatus === 'checking' ? 'Checking API' : 'API unavailable'}</strong><span>{organizations.length} organization{organizations.length === 1 ? '' : 's'} in workspace</span></div></div></div>
  </div>;
}

export default function AppShell() {
  const [mobileOpen, setMobileOpen] = useState(false);
  const [quickSearch, setQuickSearch] = useState('');
  const { selectedOrg, organizations, selectedOrgId, setSelectedOrgId, apiStatus, checkConnection } = useApp();
  const location = useLocation();
  const navigate = useNavigate();
  const [group, title] = routeTitles[location.pathname] || (location.pathname.startsWith('/organizations/') ? ['Workspace', 'Organization profile'] : ['TierLense', 'Workspace']);
  const searchMatches = useMemo(() => {
    const query = quickSearch.trim().toLowerCase();
    if (!query) return [];
    return organizations.filter((org) => `${org.name} ${org.website || ''} ${org.country_code || ''}`.toLowerCase().includes(query)).slice(0, 5);
  }, [organizations, quickSearch]);

  const chooseOrganization = (id) => {
    setSelectedOrgId(id);
    setQuickSearch('');
    if (location.pathname.startsWith('/organizations/')) navigate(`/organizations/${id}`);
    else if (location.pathname === '/organizations') navigate('/');
  };

  return <div className="app-shell">
    <aside className="sidebar desktop-sidebar"><SidebarContent /></aside>
    {mobileOpen && <div className="mobile-nav-layer"><button className="mobile-nav-scrim" onClick={() => setMobileOpen(false)} aria-label="Close navigation" /><aside className="sidebar mobile-sidebar"><button className="mobile-close" onClick={() => setMobileOpen(false)}><X size={18} /> Close</button><SidebarContent onNavigate={() => setMobileOpen(false)} /></aside></div>}
    <div className="app-main">
      <header className="topbar"><div className="topbar-left"><button className="icon-button mobile-menu" onClick={() => setMobileOpen(true)} aria-label="Open navigation"><Menu size={19} /></button><div className="breadcrumb"><span>{group}</span><span className="breadcrumb-slash">/</span><strong>{title}</strong></div></div><div className="topbar-actions">
        <div className="quick-search"><Search size={15} /><input aria-label="Find organization" placeholder="Find organization…" value={quickSearch} onChange={(event) => setQuickSearch(event.target.value)} />{searchMatches.length > 0 && <div className="search-popover">{searchMatches.map((org) => <button key={org.id} onClick={() => chooseOrganization(org.id)}><Building2 size={15} /><span>{org.name}</span>{org.country_code && <small>{org.country_code}</small>}</button>)}</div>}</div>
        <label className="org-select-label"><Building2 size={15} /><select aria-label="Active organization" value={selectedOrgId} onChange={(event) => { const id = event.target.value; setSelectedOrgId(id); if (location.pathname.startsWith('/organizations/')) navigate(id ? `/organizations/${id}` : '/organizations'); }}><option value="">Select organization</option>{organizations.map((org) => <option value={org.id} key={org.id}>{org.name}</option>)}</select><ChevronDown size={14} /></label>
        <button className="icon-button header-refresh" title="Check API connection" onClick={() => checkConnection().catch(() => {})}><RefreshCw size={16} /></button>
        <span className={`topbar-health ${apiStatus}`} title={apiStatus}><span />{apiStatus === 'online' ? 'Connected' : apiStatus === 'checking' ? 'Checking' : apiStatus === 'degraded' ? 'Degraded' : 'Offline'}</span>
      </div></header>
      <main className="page-content"><Outlet /></main>
      <footer className="app-footer"><span>TierLense Supply Chain Intelligence</span><span>{getApiBase()}</span></footer>
    </div>
  </div>;
}
