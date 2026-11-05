import React, {useEffect, useId, useRef, useState} from "react";
import type {ReactNode, AnchorHTMLAttributes} from "react";
import {api} from "./api";
import "./runtime.css";

export function navigate(path: string, replace = false) {
  if (!path.startsWith("/") || path.startsWith("//")) throw new Error("Use a same-origin route");
  history[replace ? "replaceState" : "pushState"]({}, "", path);
  dispatchEvent(new PopStateEvent("popstate"));
}
export function useLocation() {
  const [value, setValue] = useState(location.pathname + location.search + location.hash);
  useEffect(() => {const listener = () => setValue(location.pathname + location.search + location.hash);
    addEventListener("popstate", listener); return () => removeEventListener("popstate", listener);}, []);
  return {path: value.split(/[?#]/)[0], search: new URLSearchParams(value.split("?")[1]?.split("#")[0] ?? ""), url: value};
}
export function Link({href = "/", onClick, children, ...props}: AnchorHTMLAttributes<HTMLAnchorElement>) {
  return <a href={href} {...props} onClick={event => {
    onClick?.(event);
    if (!event.defaultPrevented && event.button === 0 && !event.ctrlKey && !event.metaKey && !event.shiftKey
      && !event.altKey && !props.download && (!props.target || props.target === "_self") && href.startsWith("/") && !href.startsWith("//")) {
      event.preventDefault(); navigate(href);
    }
  }}>{children}</a>;
}
export function useResource<T>(path: string | null) {
  const [state, setState] = useState<{key: string | null; data?: T; error?: string; loading: boolean}>({key: path, loading: !!path});
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    if (!path) {setState({key: null, loading: false}); return;}
    const controller = new AbortController(); setState({key: path, loading: true});
    api<T>(path, {signal: controller.signal}).then(data => {if (!controller.signal.aborted) setState({key: path, data, loading: false});})
      .catch(error => {if (!controller.signal.aborted) setState({key: path, error: String(error.message ?? error), loading: false});});
    return () => controller.abort();
  }, [path, revision]);
  const current = state.key === path ? state : {key: path, loading: !!path};
  return {...current, reload: () => setRevision(value => value + 1)};
}
export function Layout({title, navigation, actions, children}: {title: ReactNode; navigation?: ReactNode; actions?: ReactNode; children: ReactNode}) {
  return <div className="arc-layout"><header><Link href="/" className="arc-brand">{title}</Link><nav>{navigation}</nav></header>
    <main><div className="arc-actions">{actions}</div>{children}</main></div>;
}
export function Field({label, error, children}: {label: string; error?: string; children: ReactNode}) {
  const id = useId(), control = React.isValidElement(children) ? React.cloneElement(children as React.ReactElement<Record<string, unknown>>,
    {id: (children.props as {id?: string}).id ?? id, "aria-invalid": !!error, "aria-describedby": error ? id + "-error" : undefined}) : children;
  const controlId = React.isValidElement(control) ? (control.props as {id?: string}).id : id;
  return <div className="arc-field"><label htmlFor={controlId}>{label}</label>{control}
    {error && <span id={id + "-error"} role="alert">{error}</span>}</div>;
}
export function Notice({error, children}: {error?: boolean; children?: ReactNode}) {
  return children ? <div className={error ? "arc-error" : "arc-notice"} role={error ? "alert" : "status"}>{children}</div> : null;
}
export interface Column<T> {key: string; title: ReactNode; render: (row: T) => ReactNode}
export function DataTable<T>({rows, columns, rowKey, empty = "No items"}: {
  rows: T[]; columns: Column<T>[]; rowKey: (row: T) => string; empty?: ReactNode;
}) {
  return rows.length ? <table className="arc-table"><thead><tr>{columns.map(column => <th key={column.key}>{column.title}</th>)}</tr></thead>
    <tbody>{rows.map(row => <tr key={rowKey(row)}>{columns.map(column => <td key={column.key}>{column.render(row)}</td>)}</tr>)}</tbody></table>
    : <p className="arc-empty">{empty}</p>;
}
export function ConfirmDialog({open, title, children, confirmLabel, cancelLabel, busy = false, onConfirm, onCancel}: {
  open: boolean; title: string; children?: ReactNode; confirmLabel: string; cancelLabel: string;
  busy?: boolean; onConfirm: () => void; onCancel: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null), heading = useId();
  useEffect(() => {if (open && !dialog.current?.open) dialog.current?.showModal();
    if (!open && dialog.current?.open) dialog.current.close();}, [open]);
  return <dialog ref={dialog} aria-labelledby={heading} onCancel={event => {event.preventDefault(); if (!busy) onCancel();}}>
    <h2 id={heading}>{title}</h2>{children}<div className="arc-actions"><button type="button" disabled={busy} onClick={onCancel}>{cancelLabel}</button>
    <button type="button" disabled={busy} onClick={onConfirm}>{confirmLabel}</button></div></dialog>;
}
