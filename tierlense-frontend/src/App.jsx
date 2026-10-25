import React from 'react';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { AppProvider } from './context/AppContext.jsx';
import AppShell from './components/AppShell.jsx';
import DashboardPage from './pages/DashboardPage.jsx';
import OrganizationsPage from './pages/OrganizationsPage.jsx';
import OrganizationDetailPage from './pages/OrganizationDetailPage.jsx';
import InvestigationsPage from './pages/InvestigationsPage.jsx';
import SupplyChainPage from './pages/SupplyChainPage.jsx';
import DisruptionsPage from './pages/DisruptionsPage.jsx';
import EvidencePage from './pages/EvidencePage.jsx';
import AlternativesPage from './pages/AlternativesPage.jsx';
import HistoryPage from './pages/HistoryPage.jsx';
import SettingsPage from './pages/SettingsPage.jsx';
import { ToastViewport } from './components/ToastViewport.jsx';

export default function App() {
  return <BrowserRouter><AppProvider><Routes><Route element={<AppShell />}><Route path="/" element={<DashboardPage />} /><Route path="/organizations" element={<OrganizationsPage />} /><Route path="/organizations/:organizationId" element={<OrganizationDetailPage />} /><Route path="/investigations" element={<InvestigationsPage />} /><Route path="/supply-chain" element={<SupplyChainPage />} /><Route path="/disruptions" element={<DisruptionsPage />} /><Route path="/evidence" element={<EvidencePage />} /><Route path="/alternatives" element={<AlternativesPage />} /><Route path="/history" element={<HistoryPage />} /><Route path="/settings" element={<SettingsPage />} /><Route path="*" element={<Navigate to="/" replace />} /></Route></Routes><ToastViewport /></AppProvider></BrowserRouter>;
}
