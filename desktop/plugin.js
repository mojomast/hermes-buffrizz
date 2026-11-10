import React, {useEffect, useRef, useState} from 'react';
import {host, useValue} from '@hermes/plugin-sdk';

const h = React.createElement;
const C = {
  bg: '#101216', panel: '#191d23', line: '#303640', text: '#f4f0e8',
  muted: '#9fa8b7', accent: '#7fd6a8', warn: '#e8b968', danger: '#eeaca2',
};
const button = {
  border: `1px solid ${C.line}`, background: C.panel, color: C.text,
  borderRadius: 8, padding: '8px 12px', cursor: 'pointer', font: 'inherit',
};
const field = {...button, width: '100%', boxSizing: 'border-box', textAlign: 'left'};
const row = {display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap'};
const errorText = error => error?.message || error?.error || String(error);
const checked = value => {
  if (!value?.ok) throw Error(value?.message || value?.error || 'Buffrizz backend unavailable');
  return value;
};

function keyPayload(e) {
  if (e.ctrlKey && e.key.toLowerCase() === 'c') return {data: '\x03'};
  if (e.ctrlKey && e.key.toLowerCase() === 'd') return {data: '\x04'};
  if (e.key === 'Enter') return {data: '\r'};
  if (e.key === 'Backspace') return {data: '\x7f'};
  if (e.key === 'Tab') return {data: '\t'};
  if (e.key === 'Escape') return {data: '\x1b'};
  if (e.key === 'ArrowUp') return {data: '\x1b[A'};
  if (e.key === 'ArrowDown') return {data: '\x1b[B'};
  if (e.key === 'ArrowRight') return {data: '\x1b[C'};
  if (e.key === 'ArrowLeft') return {data: '\x1b[D'};
  if (e.key === 'Home') return {data: '\x1b[H'};
  if (e.key === 'End') return {data: '\x1b[F'};
  if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) return {data: e.key};
  return null;
}

function Pane({ctx}) {
  const session = useValue(host.state.focusedSessionId);
  const [state, setState] = useState(null);
  const [screen, setScreen] = useState(null);
  const [cwd, setCwd] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('Open a conversation, choose an allowlisted project, and start the official Freebuff TUI.');
  const term = useRef(null);
  const api = async (path, opts) => checked(await ctx.rest(path, opts));

  useEffect(() => {
    let live = true, timer;
    async function refresh() {
      try {
        const next = await api(`/state?session=${encodeURIComponent(session || '')}&detail=full`);
        if (!live) return;
        setState(next);
        if (next.cwd && !cwd) setCwd(next.cwd);
        if (next.running) {
          const shot = await api(`/screen?session=${encodeURIComponent(session || '')}`);
          if (live) setScreen(shot);
        } else if (live) {
          setScreen(null);
        }
        setError('');
      } catch (e) {
        if (live) setError(errorText(e));
      }
      if (live) timer = setTimeout(refresh, 400);
    }
    refresh();
    return () => { live = false; clearTimeout(timer); };
  }, [session, ctx]);

  async function action(fn) {
    setBusy(true); setError('');
    try { await fn(); }
    catch (e) { setError(errorText(e)); }
    finally { setBusy(false); }
  }

  async function start() {
    if (!session) throw Error('Open a Hermes conversation before starting Freebuff.');
    if (!cwd.trim()) throw Error('Enter an allowlisted project path.');
    const result = await api('/connect', {method: 'POST', body: {action: 'start', session_id: session, cwd: cwd.trim()}});
    setNotice('The official Freebuff TUI is running. Sign in in this pane if asked, then click Run for a queued job.');
    return result;
  }

  async function stop() {
    if (!session) return;
    await api('/connect', {method: 'POST', body: {action: 'stop', session_id: session}});
    setScreen(null);
    setNotice('Session stopped.');
  }

  async function runJob(jobId) {
    await api(`/jobs/${jobId}/run`, {method: 'POST', body: {session_id: session}});
    setNotice('Prompt pasted into the official session. Ads stay visible. Stay present while it works.');
  }

  function onKey(e) {
    const payload = keyPayload(e);
    if (!payload || !session) return;
    e.preventDefault();
    api('/input', {method: 'POST', body: {session_id: session, ...payload}}).catch(err => setError(errorText(err)));
  }

  function onPaste(e) {
    const text = e.clipboardData?.getData('text') || '';
    if (!text || !session) return;
    e.preventDefault();
    api('/input', {method: 'POST', body: {session_id: session, text}}).catch(err => setError(errorText(err)));
  }

  const jobs = state?.jobs || [];
  const queued = jobs.filter(j => j.status === 'queued');
  const signed = state?.signed_in;
  const roots = state?.allowlist_roots || [];

  return h('div', {style: {height: '100%', overflow: 'auto', background: C.bg, color: C.text, fontFamily: 'system-ui,sans-serif', fontSize: 13, padding: 16, boxSizing: 'border-box'}},
    h('header', {style: {...row, justifyContent: 'space-between', marginBottom: 12}},
      h('div', {},
        h('div', {style: {fontSize: 11, letterSpacing: 3, color: C.accent, fontWeight: 700}}, 'BUFFRIZZ'),
        h('h2', {style: {fontSize: 20, letterSpacing: -0.5, margin: '4px 0'}}, 'Official Freebuff, shared with Hermes')
      ),
      h('span', {style: {color: C.muted, fontSize: 11}}, signed === 'true' ? 'signed in' : signed === 'false' ? 'sign in required' : 'session unknown')
    ),
    error && h('div', {role: 'alert', style: {marginBottom: 12, padding: 12, border: `1px solid #865258`, background: '#2a1e24', borderRadius: 8}}, error),
    h('div', {style: {...row, marginBottom: 10}},
      h('input', {
        'aria-label': 'Allowlisted project',
        placeholder: roots[0] || 'Allowlisted project path',
        value: cwd,
        list: 'buffrizz-roots',
        style: {...field, flex: 1},
        onChange: e => setCwd(e.target.value),
      }),
      h('datalist', {id: 'buffrizz-roots'}, ...roots.map(r => h('option', {key: r, value: r}))),
      h('button', {style: {...button, borderColor: C.accent}, disabled: busy || !session, onClick: () => action(start)}, 'Start official TUI'),
      h('button', {style: button, disabled: busy || !state?.running, onClick: () => action(stop)}, 'Stop')
    ),
    h('p', {style: {color: C.muted, fontSize: 12, lineHeight: 1.55, margin: '0 0 10px'}}, notice),
    h('div', {
      ref: term,
      tabIndex: 0,
      role: 'application',
      'aria-label': 'Official Freebuff terminal',
      onKeyDown: onKey,
      onPaste,
      style: {
        background: '#080a0d',
        border: `1px solid ${C.line}`,
        borderRadius: 10,
        padding: 10,
        minHeight: 260,
        fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
        fontSize: 12,
        lineHeight: 1.35,
        whiteSpace: 'pre',
        overflow: 'auto',
        outline: 'none',
      },
    }, screen?.lines ? screen.lines.join('\n') : (state?.running ? 'Starting the official Freebuff CLI…' : 'The official TUI appears here after Start. Sign in yourself. Buffrizz will not script login.')),
    queued.length > 0 && h('section', {style: {marginTop: 16}},
      h('strong', {}, 'Queued jobs'),
      ...queued.map(job => h('div', {key: job.id, style: {...row, marginTop: 8, padding: 10, background: C.panel, borderRadius: 8}},
        h('span', {style: {flex: 1}}, job.id),
        h('button', {
          style: {...button, background: C.accent, color: '#102018', fontWeight: 650},
          disabled: busy || !state?.running,
          onClick: () => action(() => runJob(job.id)),
        }, 'Run')
      ))
    ),
    jobs.some(j => j.status !== 'queued') && h('section', {style: {marginTop: 14}},
      h('strong', {}, 'Recent jobs'),
      ...jobs.filter(j => j.status !== 'queued').slice(0, 8).map(job =>
        h('div', {key: job.id, style: {padding: '6px 0', color: C.muted, borderBottom: `1px solid ${C.line}`}},
          `${job.id} · ${job.status}${job.branch ? ' · ' + job.branch : ''}`
        )
      )
    ),
    h('p', {style: {color: C.muted, fontSize: 11, lineHeight: 1.5, marginTop: 18}},
      'This pane hosts the official freebuff binary. Ads and notices stay visible. ' +
      'A human starts each free-tier session and remains present. ' +
      'The agent only queues work; clicking Run pastes the prompt into the official TUI. ' +
      'Add project roots in Buffrizz plugin settings. The model cannot add a root.'
    )
  );
}

export default {
  id: 'buffrizz',
  name: 'Buffrizz',
  register(ctx) {
    ctx.register({
      id: 'session',
      area: 'panes',
      title: 'Buffrizz',
      data: {placement: 'right', width: '640px'},
      render: () => h(Pane, {ctx}),
    });
  },
};
