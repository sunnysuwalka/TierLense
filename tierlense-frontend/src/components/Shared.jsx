import React, { useEffect } from 'react';
import { AlertCircle, CheckCircle2, CircleHelp, Info, LoaderCircle, RefreshCw, X } from 'lucide-react';

export function PageHeader({ title, description, actions, children }) {
  return <div className="page-header"><div className="page-header-copy"><h1>{title}</h1>{description && <p>{description}</p>}{children}</div>{actions && <div className="page-header-actions">{actions}</div>}</div>;
}

export function Card({ children, className = '', padding = true }) {
  return <section className={`card ${padding ? 'card-padded' : ''} ${className}`.trim()}>{children}</section>;
}

export function MetricCard({ label, value, detail, icon: Icon, tone = 'blue', onClick }) {
  const body = <><div className="metric-top"><span>{label}</span>{Icon && <span className={`metric-icon ${tone}`}><Icon size={17} /></span>}</div><div className="metric-value">{value ?? '—'}</div>{detail && <div className="metric-detail">{detail}</div>}</>;
  return onClick ? <button className="card card-padded metric-card metric-action" onClick={onClick}>{body}</button> : <div className="card card-padded metric-card">{body}</div>;
}

export function StatusBadge({ value, children, kind }) {
  const text = String(children ?? value ?? 'unknown');
  const raw = String(kind || value || text).toLowerCase().replace(/[\s-]+/g, '_');
  let tone = 'neutral';
  if (/verified|completed|potential_matches_found|online|pass|success|observed/.test(raw)) tone = 'green';
  else if (/running|queued|reported|forecast|risk_signal|needs_review|conditional_match|conditional_matches_only|degraded/.test(raw)) tone = 'amber';
  else if (/failed|error|critical|unverified|insufficient_evidence|offline|rejected/.test(raw)) tone = 'red';
  else if (/potential_match|potential_matches_found|high|medium|low|review|experimental|unknown|active|enabled|connected|documented/.test(raw)) tone = 'blue';
  return <span className={`status-badge ${tone}`}><span className="status-dot" />{text.replaceAll('_', ' ')}</span>;
}

export function LoadingState({ label = 'Loading data…' }) {
  return <div className="loading-state"><LoaderCircle className="spin" size={20} /><span>{label}</span></div>;
}

export function ErrorState({ message, onRetry }) {
  return <div className="error-state"><AlertCircle size={20} /><div><strong>We couldn’t load this view</strong><p>{message || 'The request failed.'}</p>{onRetry && <button className="button button-secondary button-small" onClick={onRetry}><RefreshCw size={14} /> Try again</button>}</div></div>;
}

export function EmptyState({ icon: Icon = CircleHelp, title = 'Nothing here yet', description, action }) {
  return <div className="empty-state">{Icon && <div className="empty-icon"><Icon size={22} /></div>}<h3>{title}</h3>{description && <p>{description}</p>}{action}</div>;
}

export function Modal({ open, title, description, onClose, children, wide = false, footer }) {
  useEffect(() => {
    if (!open) return undefined;
    const onKeyDown = (event) => { if (event.key === 'Escape') onClose?.(); };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [open, onClose]);
  if (!open) return null;
  return <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose?.(); }}><div className={`modal ${wide ? 'modal-wide' : ''}`} role="dialog" aria-modal="true" aria-label={title}><div className="modal-header"><div><h2>{title}</h2>{description && <p>{description}</p>}</div><button className="icon-button" onClick={onClose} aria-label="Close dialog"><X size={18} /></button></div><div className="modal-body">{children}</div>{footer && <div className="modal-footer">{footer}</div>}</div></div>;
}

export function Field({ label, help, required, children, className = '' }) {
  return <label className={`field ${className}`}><span className="field-label">{label}{required && <em> *</em>}</span>{children}{help && <small className="field-help">{help}</small>}</label>;
}

export function Alert({ children, tone = 'info', onDismiss }) {
  return <div className={`alert alert-${tone}`}>{tone === 'success' ? <CheckCircle2 size={18} /> : tone === 'info' ? <Info size={18} /> : <AlertCircle size={18} />}<div>{children}</div>{onDismiss && <button onClick={onDismiss} className="icon-button" aria-label="Dismiss"><X size={15} /></button>}</div>;
}

export function InlineSpinner() {
  return <LoaderCircle size={15} className="spin" />;
}

export function DataList({ items, empty = 'No details available.' }) {
  if (!items || Object.keys(items).length === 0) return <p className="muted-text">{empty}</p>;
  return <dl className="data-list">{Object.entries(items).map(([key, value]) => <div key={key}><dt>{key.replaceAll('_', ' ')}</dt><dd>{typeof value === 'object' && value !== null ? <code className="inline-code">{JSON.stringify(value)}</code> : String(value ?? '—')}</dd></div>)}</dl>;
}

export function JsonBlock({ value }) {
  return <pre className="json-block">{JSON.stringify(value ?? {}, null, 2)}</pre>;
}

export function formatDate(value, includeTime = true) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat(undefined, includeTime ? { dateStyle: 'medium', timeStyle: 'short' } : { dateStyle: 'medium' }).format(date);
}

export function formatNumber(value) {
  if (value === null || value === undefined || value === '') return '—';
  return new Intl.NumberFormat().format(value);
}

export function ErrorInline({ message }) {
  if (!message) return null;
  return <div className="inline-error"><AlertCircle size={15} />{message}</div>;
}
