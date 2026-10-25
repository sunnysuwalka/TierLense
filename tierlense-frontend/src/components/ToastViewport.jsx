import React from 'react';
import { CheckCircle2, AlertCircle, X } from 'lucide-react';
import { useApp } from '../context/AppContext.jsx';

export function ToastViewport() {
  const { notice } = useApp();
  if (!notice) return null;
  const Icon = notice.type === 'error' ? AlertCircle : CheckCircle2;
  return <div className={`toast toast-${notice.type}`} role="status"><Icon size={17} /><span>{notice.message}</span></div>;
}
