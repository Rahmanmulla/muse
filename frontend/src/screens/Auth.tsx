import { useState } from 'react';
import type { FormEvent } from 'react';
import { api, apiErrorMessage, setAuth } from '../api';
import type { AuthResult } from '../types';

export function AuthLoading() {
  return (
    <div className="auth-wrap">
      <div className="auth-logo" aria-hidden="true">✨</div>
      <h1><span className="brand">STIP</span></h1>
      <p className="auth-tag">Waking up the cosmos…</p>
      <div className="spinner" role="status" aria-label="Loading" />
    </div>
  );
}

type Mode = 'login' | 'otp';

export function Auth({ mode, onDone }: { mode: 'login'; onDone: () => void }) {
  const [tab, setTab] = useState<Mode>(mode);
  const [login, setLogin] = useState('');
  const [password, setPassword] = useState('');
  const [channel, setChannel] = useState<'phone' | 'email'>('phone');
  const [address, setAddress] = useState('');
  const [code, setCode] = useState('');
  const [devCode, setDevCode] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const finish = (a: AuthResult) => {
    setAuth(a);
    onDone();
  };

  const submitPassword = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const a = await api.post<AuthResult>('/auth/login', { login, password });
      finish(a);
    } catch (e2) {
      setErr(apiErrorMessage(e2));
    } finally {
      setBusy(false);
    }
  };

  const requestOtp = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const r = await api.post<{ ok: boolean; dev_code?: string }>('/auth/otp/request', { channel, address });
      setDevCode(r.dev_code ?? null);
    } catch (e2) {
      setErr(apiErrorMessage(e2));
    } finally {
      setBusy(false);
    }
  };

  const verifyOtp = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const r = await api.post<{ ok: boolean; verified: boolean }>('/auth/otp/verify', { channel, address, code });
      if (r.verified) {
        setErr(null);
        // OTP verifies identity; continue into the full onboarding wizard.
        window.location.hash = '#/onboarding';
      }
    } catch (e2) {
      setErr(apiErrorMessage(e2));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="auth-wrap">
      <div className="auth-logo" aria-hidden="true">✨</div>
      <h1><span className="brand">STIP</span></h1>
      <p className="auth-tag">Make every chat yours.</p>

      <div className="auth-tabs" role="tablist" aria-label="Auth method">
        <button className={'btn small' + (tab === 'login' ? '' : ' secondary')} onClick={() => setTab('login')}>Log in</button>
        <button className="btn small secondary" onClick={() => { window.location.hash = '#/onboarding'; }}>Sign up</button>
        <button className={'btn small' + (tab === 'otp' ? '' : ' secondary')} onClick={() => setTab('otp')}>OTP</button>
      </div>

      {err && <div className="auth-err" role="alert">{err}</div>}

      {tab === 'otp' ? (
        <form onSubmit={devCode ? verifyOtp : requestOtp}>
          <label className="field">
            <span>Channel</span>
            <select className="input" value={channel} onChange={(e) => setChannel(e.target.value as 'phone' | 'email')}>
              <option value="phone">Phone</option>
              <option value="email">Email</option>
            </select>
          </label>
          <label className="field">
            <span>{channel === 'phone' ? 'Phone number' : 'Email address'}</span>
            <input className="input" value={address} onChange={(e) => setAddress(e.target.value)} required
              inputMode={channel === 'phone' ? 'tel' : 'email'} autoComplete={channel === 'phone' ? 'tel' : 'email'} />
          </label>
          {devCode && (
            <label className="field">
              <span>Code {devCode && <em className="muted">(dev: {devCode})</em>}</span>
              <input className="input" value={code} onChange={(e) => setCode(e.target.value)} required
                inputMode="numeric" autoComplete="one-time-code" placeholder="6-digit code" />
            </label>
          )}
          <button className="btn" style={{ width: '100%' }} disabled={busy}>
            {busy ? '…' : devCode ? 'Verify code' : 'Send code'}
          </button>
          <p className="muted small" style={{ textAlign: 'center', marginTop: 12 }}>
            Dev mode: the code is shown in-band. Production would send it via SMS/email.
          </p>
        </form>
      ) : (
        <form onSubmit={submitPassword}>
          <label className="field">
            <span>Username, email or phone</span>
            <input className="input" value={login} onChange={(e) => setLogin(e.target.value)} required autoComplete="username" />
          </label>
          <label className="field">
            <span>Password</span>
            <input className="input" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required
              autoComplete="current-password" minLength={6} />
          </label>
          <button className="btn" style={{ width: '100%' }} disabled={busy}>
            {busy ? '…' : 'Log in'}
          </button>
        </form>
      )}
    </div>
  );
}
