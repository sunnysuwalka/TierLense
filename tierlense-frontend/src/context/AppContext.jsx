import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { apiRequest } from '../api/client.js';

const AppContext = createContext(null);
const ORG_STORAGE_KEY = 'tierlense_selected_organization_id';

export function AppProvider({ children }) {
  const [organizations, setOrganizations] = useState([]);
  const [selectedOrgId, setSelectedOrgIdState] = useState(() => localStorage.getItem(ORG_STORAGE_KEY) || '');
  const [organizationsLoading, setOrganizationsLoading] = useState(true);
  const [organizationsError, setOrganizationsError] = useState('');
  const [apiStatus, setApiStatus] = useState('checking');
  const [apiError, setApiError] = useState('');
  const [lastChecked, setLastChecked] = useState(null);
  const [notice, setNotice] = useState(null);

  const setSelectedOrgId = useCallback((id) => {
    const value = id || '';
    setSelectedOrgIdState(value);
    if (value) localStorage.setItem(ORG_STORAGE_KEY, value);
    else localStorage.removeItem(ORG_STORAGE_KEY);
  }, []);

  const refreshOrganizations = useCallback(async (query = '') => {
    setOrganizationsLoading(true);
    setOrganizationsError('');
    try {
      const queryPart = query ? `&q=${encodeURIComponent(query)}` : '';
      const data = await apiRequest(`/organizations?limit=200${queryPart}`);
      const items = data?.items || [];
      setOrganizations(items);
      setSelectedOrgIdState((current) => {
        const next = items.some((item) => item.id === current) ? current : (items[0]?.id || '');
        if (next) localStorage.setItem(ORG_STORAGE_KEY, next);
        else localStorage.removeItem(ORG_STORAGE_KEY);
        return next;
      });
      setApiStatus('online');
      setApiError('');
      setLastChecked(new Date());
      return items;
    } catch (error) {
      setOrganizationsError(error.message);
      setApiStatus('offline');
      setApiError(error.message);
      setLastChecked(new Date());
      throw error;
    } finally {
      setOrganizationsLoading(false);
    }
  }, []);

  const checkConnection = useCallback(async () => {
    setApiStatus('checking');
    try {
      const live = await apiRequest('/health/live');
      let ready = null;
      try { ready = await apiRequest('/health/ready'); } catch (error) { ready = { error: error.message }; }
      setApiStatus(ready?.status === 'not_ready' || ready?.error ? 'degraded' : 'online');
      setApiError(ready?.error || '');
      setLastChecked(new Date());
      return { live, ready };
    } catch (error) {
      setApiStatus('offline');
      setApiError(error.message);
      setLastChecked(new Date());
      throw error;
    }
  }, []);

  const selectedOrg = useMemo(() => organizations.find((org) => org.id === selectedOrgId) || null, [organizations, selectedOrgId]);

  useEffect(() => {
    refreshOrganizations().catch(() => {});
    checkConnection().catch(() => {});
  }, [refreshOrganizations, checkConnection]);

  const pushNotice = useCallback((message, type = 'success') => {
    const id = Date.now();
    setNotice({ id, message, type });
    window.setTimeout(() => setNotice((current) => current?.id === id ? null : current), 4200);
  }, []);

  const value = {
    organizations, selectedOrg, selectedOrgId, setSelectedOrgId,
    organizationsLoading, organizationsError, refreshOrganizations,
    apiStatus, apiError, lastChecked, checkConnection, notice, pushNotice,
  };
  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

export function useApp() {
  const value = useContext(AppContext);
  if (!value) throw new Error('useApp must be used inside AppProvider');
  return value;
}
