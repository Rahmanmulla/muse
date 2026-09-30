import { useCallback, useEffect, useState } from 'react';
import { api, apiErrorMessage } from '../api';
import { useApp } from '../store';
import { Avatar, Empty, ErrorState, Loading, Modal, SectionTitle, fmtDate, useToggle } from '../components/ui';
import type { Device, Profile, ReferralInfo } from '../types';

export function Settings({ onBack }: { onBack: () => void }) {
  const { me, settings, refreshSettings, logout, lowEffects, setLowEffects, toast } = useApp();
  const [blocks, setBlocks] = useState<Profile[]>([]);
  const [devices, setDevices] = useState<Device[]>([]);
  const [adminOpen, , setAdminOpen] = useToggle(false);

  const loadBlocks = useCallback(async () => {
    try { setBlocks(await api.get<Profile[]>('/users/me/blocks')); } catch { /* ignore */ }
  }, []);
  const loadDevices = useCallback(async () => {
    try { setDevices(await api.get<Device[]>('/auth/devices')); } catch { /* ignore */ }
  }, []);
  useEffect(() => { loadBlocks(); loadDevices(); }, [loadBlocks, loadDevices]);

  const setSetting = async (key: string, value: unknown) => {
    try {
      await api.put(`/users/me/settings/${key}`, { value });
      refreshSettings();
      toast('✅ Saved');
    } catch (e) {
      toast(apiErrorMessage(e));
    }
  };

  const unblock = async (id: number) => {
    try {
      await api.post('/users/unblock', { user_id: id });
      loadBlocks();
      toast('✅ Unblocked');
    } catch (e) { toast(apiErrorMessage(e)); }
  };

  const revokeDevice = async (id: number) => {
    if (!window.confirm('Revoke this device? It will be signed out.')) return;
    try {
      await api.post(`/auth/devices/${id}/revoke`, {});
      loadDevices();
      toast('✅ Device revoked');
    } catch (e) { toast(apiErrorMessage(e)); }
  };

  const revokeOthers = async () => {
    if (!window.confirm('Sign out all other devices?')) return;
    try {
      await api.post('/auth/devices/revoke-others', {});
      loadDevices();
      toast('✅ Other devices signed out');
    } catch (e) { toast(apiErrorMessage(e)); }
  };

  return (
    <div>
      <div className="topbar">
        <button className="icon-btn" onClick={onBack} aria-label="Back">←</button>
        <h1>⚙️ Settings</h1>
      </div>
      <div className="screen">
        <SectionTitle>Notifications</SectionTitle>
        <div className="card">
          <label className="field">
            <span>Notification preview</span>
            <select className="input" value={(settings.notification_preview as string) ?? 'full'}
              onChange={(e) => setSetting('notification_preview', e.target.value)}>
              <option value="full">Full preview</option>
              <option value="sender">Sender only</option>
              <option value="none">No preview</option>
            </select>
          </label>
        </div>

        <SectionTitle>Accessibility & motion</SectionTitle>
        <div className="card">
          <div className="list-row">
            <span className="grow"><strong>Reduce motion</strong><div className="muted small">Disables animations across the app</div></span>
            <button className={'toggle' + (settings.reduced_motion === true ? ' on' : '')} role="switch"
              aria-checked={settings.reduced_motion === true} aria-label="Reduce motion"
              onClick={() => setSetting('reduced_motion', settings.reduced_motion !== true)} />
          </div>
          <div className="list-row">
            <span className="grow"><strong>Low effects</strong><div className="muted small">Static fallbacks instead of cosmic effects</div></span>
            <button className={'toggle' + (lowEffects ? ' on' : '')} role="switch"
              aria-checked={lowEffects} aria-label="Low effects"
              onClick={() => setLowEffects(!lowEffects)} />
          </div>
          <label className="field" style={{ marginTop: 8 }}>
            <span>Theme</span>
            <select className="input" value={(settings.theme as string) ?? 'system'}
              onChange={(e) => setSetting('theme', e.target.value)}>
              <option value="system">System (follow device)</option>
              <option value="dark">Dark (cosmic)</option>
              <option value="light">Light</option>
            </select>
          </label>
        </div>

        <SectionTitle>Privacy</SectionTitle>
        <div className="card">
          <div className="list-row">
            <span className="grow"><strong>Message requests</strong><div className="muted small">Strangers land in an inbox you approve first</div></span>
            <button className={'toggle' + (settings.message_requests !== false ? ' on' : '')} role="switch"
              aria-checked={settings.message_requests !== false} aria-label="Message requests"
              onClick={() => setSetting('message_requests', settings.message_requests === false)} />
          </div>
          <div className="list-row">
            <span className="grow"><strong>Link previews</strong><div className="muted small">Show rich cards for links in chat</div></span>
            <button className={'toggle' + (settings.link_previews !== false ? ' on' : '')} role="switch"
              aria-checked={settings.link_previews !== false} aria-label="Link previews"
              onClick={() => setSetting('link_previews', settings.link_previews === false)} />
          </div>
        </div>

        <SectionTitle>Referrals</SectionTitle>
        <ReferralCard />

        <SectionTitle>Blocked users</SectionTitle>
        <div className="card">
          {blocks.length === 0 ? <p className="muted small">Nobody blocked.</p> :
            blocks.map((u) => (
              <div key={u.id} className="list-row">
                <Avatar profile={u} size={36} />
                <span className="grow">@{u.username}</span>
                <button className="btn small secondary" onClick={() => unblock(u.id)}>Unblock</button>
              </div>
            ))}
        </div>

        <SectionTitle>Devices</SectionTitle>
        <div className="card">
          {devices.map((d) => (
            <div key={d.id} className="list-row">
              <div className="grow">
                <strong>{d.device_name ?? `Device ${d.id}`}</strong>{' '}
                {d.trusted && <span className="pill ok">🛡️ trusted</span>}{' '}
                {d.revoked && <span className="muted">(revoked)</span>}
                <div className="muted small">
                  {d.platform ?? 'Unknown platform'} · added {fmtDate(d.created_at)}
                  {d.verified_at ? ` · verified ${fmtDate(d.verified_at)}` : ''}
                </div>
              </div>
              {!d.revoked && <button className="btn small secondary" onClick={() => revokeDevice(d.id)}>Revoke</button>}
            </div>
          ))}
          {devices.length === 0 && <p className="muted small">No devices on record.</p>}
          <button className="btn small secondary" style={{ marginTop: 8 }} onClick={revokeOthers}>Sign out other devices</button>
        </div>

        <SectionTitle>Change password</SectionTitle>
        <div className="card">
          <PasswordForm />
        </div>

        <SectionTitle>Account</SectionTitle>
        <div className="card">
          <div className="row wrap" style={{ gap: 8 }}>
            <button className="btn small danger" onClick={logout}>Log out</button>
          </div>
          <p className="muted small" style={{ marginTop: 10 }}>
            Payments: dev provider only (no real billing). Messages are transport-encrypted; end-to-end encryption is a documented upgrade path, not yet implemented. Voice/video calls and voice messages are out of scope.
          </p>
        </div>

        {me?.is_admin && (
          <button className="btn" style={{ width: '100%', marginTop: 8 }} onClick={() => setAdminOpen(true)}>
            🛠️ Admin panel
          </button>
        )}
      </div>
      {adminOpen && <AdminPanel onClose={() => setAdminOpen(false)} />}
    </div>
  );
}

/* ---------------- password change with OTP gate ---------------- */

// Changing the password from an untrusted device is OTP-gated server-side.
// The code goes to the account's own email/phone (never typed from a stranger's device).
function PasswordForm() {
  const { me, toast } = useApp();
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [otpChannel, setOtpChannel] = useState<'email' | 'phone'>(me?.email ? 'email' : 'phone');
  const [otpAddress, setOtpAddress] = useState(me?.email ?? me?.phone ?? '');
  const [otpCode, setOtpCode] = useState('');
  const [otpSent, setOtpSent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const requestCode = async () => {
    if (!otpAddress.trim()) { setErr('Enter the email or phone on your account.'); return; }
    setBusy(true); setErr(null);
    try {
      await api.post('/auth/otp/request', {
        channel: otpChannel, address: otpAddress.trim(), purpose: 'password_change',
      });
      setOtpSent(true);
      toast('📨 Code sent to your email/phone');
    } catch (e) {
      setErr(apiErrorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true); setErr(null);
    try {
      await api.post('/auth/password', {
        current_password: currentPassword,
        new_password: newPassword,
        otp_channel: otpSent ? otpChannel : undefined,
        otp_address: otpSent ? otpAddress.trim() : undefined,
        otp_code: otpSent ? otpCode.trim() : undefined,
      });
      toast('✅ Password changed');
      setCurrentPassword(''); setNewPassword(''); setOtpCode(''); setOtpSent(false);
    } catch (e2) {
      setErr(apiErrorMessage(e2));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit}>
      {err && <div className="auth-err" role="alert">{err}</div>}
      <label className="field">
        <span>Current password</span>
        <input className="input" type="password" value={currentPassword} required
          onChange={(e) => setCurrentPassword(e.target.value)} autoComplete="current-password" />
      </label>
      <label className="field">
        <span>New password (min 6 chars)</span>
        <input className="input" type="password" value={newPassword} required minLength={6}
          onChange={(e) => setNewPassword(e.target.value)} autoComplete="new-password" />
      </label>
      <p className="muted small" style={{ marginTop: 6 }}>
        If you're on a new device, the server may ask for a one-time code sent to your email/phone.
      </p>
      {!otpSent ? (
        <div className="row wrap" style={{ gap: 8, alignItems: 'flex-end' }}>
          <label className="field" style={{ flex: '0 0 auto' }}>
            <span>Code via</span>
            <select className="input" value={otpChannel} onChange={(e) => setOtpChannel(e.target.value as 'email' | 'phone')}>
              <option value="email">Email</option>
              <option value="phone">Phone</option>
            </select>
          </label>
          <label className="field grow" style={{ marginBottom: 0 }}>
            <span>Your email / phone</span>
            <input className="input" value={otpAddress} onChange={(e) => setOtpAddress(e.target.value)}
              placeholder={otpChannel === 'email' ? 'you@example.com' : '+15551234567'} />
          </label>
          <button type="button" className="btn small secondary" disabled={busy} onClick={requestCode}>
            Send code
          </button>
        </div>
      ) : (
        <label className="field">
          <span>One-time code</span>
          <input className="input" value={otpCode} onChange={(e) => setOtpCode(e.target.value)}
            inputMode="numeric" autoComplete="one-time-code" placeholder="••••••" />
        </label>
      )}
      <button className="btn" style={{ width: '100%', marginTop: 10 }} disabled={busy}>
        {busy ? '…' : 'Change password'}
      </button>
    </form>
  );
}

/* ---------------- referrals ---------------- */

function ReferralCard() {
  const { toast } = useApp();
  const [info, setInfo] = useState<ReferralInfo | null>(null);
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.get<ReferralInfo>('/referrals/mine')
      .then(setInfo)
      .catch(() => { /* ignore */ });
  }, []);

  const apply = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!code.trim()) return;
    setBusy(true);
    try {
      const r = await api.post<{ ok: boolean; rewarded_shards: number }>('/referrals/apply', { code: code.trim() });
      toast(`🎁 Referral applied! +${r.rewarded_shards} 🔷`);
      setCode('');
    } catch (e2) {
      toast(apiErrorMessage(e2));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card">
      {info && (
        <div className="row" style={{ alignItems: 'center', marginBottom: 8 }}>
          <div className="grow">
            <strong>Your code: <span className="mono">{info.code}</span></strong>
            <div className="muted small">{info.total_credited}/{info.credit_limit_30d} used (30d) · both sides get {info.reward_shards} 🔷</div>
          </div>
          <button className="btn small secondary" onClick={() => { navigator.clipboard?.writeText(info.code); toast('📋 Code copied'); }}>
            Copy
          </button>
        </div>
      )}
      <form onSubmit={apply}>
        <div className="row" style={{ gap: 8 }}>
          <input className="input grow" value={code} onChange={(e) => setCode(e.target.value)}
            placeholder="Apply a friend's code…" aria-label="Referral code" />
          <button className="btn small" disabled={busy || !code.trim()}>Apply</button>
        </div>
      </form>
    </div>
  );
}

/* ---------------- admin panel ---------------- */

type AdminTab = 'flags' | 'cosmetics' | 'events' | 'economy' | 'audit' | 'reports' | 'users';

function AdminPanel({ onClose }: { onClose: () => void }) {
  const { toast } = useApp();
  const [tab, setTab] = useState<AdminTab>('flags');
  return (
    <Modal title="🛠️ Admin" onClose={onClose}>
      <div className="filter-row">
        {(['flags', 'cosmetics', 'events', 'economy', 'audit', 'reports', 'users'] as AdminTab[]).map((t) => (
          <button key={t} className={'chip' + (tab === t ? ' active' : '')} onClick={() => setTab(t)}>{t}</button>
        ))}
      </div>
      {tab === 'flags' && <AdminFlags toast={toast} />}
      {tab === 'cosmetics' && <AdminCosmetics toast={toast} />}
      {tab === 'events' && <AdminEvents toast={toast} />}
      {tab === 'economy' && <AdminEconomy toast={toast} />}
      {tab === 'audit' && <AdminAudit />}
      {tab === 'reports' && <AdminReports toast={toast} />}
      {tab === 'users' && <AdminUsers toast={toast} />}
    </Modal>
  );
}

function AdminFlags({ toast }: { toast: (t: string) => void }) {
  const [flags, setFlags] = useState<Record<string, boolean> | null>(null);
  const load = useCallback(async () => {
    try { setFlags(await api.get<Record<string, boolean>>('/admin/flags')); }
    catch (e) { toast(apiErrorMessage(e)); }
  }, [toast]);
  useEffect(() => { load(); }, [load]);
  const toggle = async (key: string, v: boolean) => {
    try {
      await api.put(`/admin/flags/${encodeURIComponent(key)}`, { value: v });
      load();
    } catch (e) { toast(apiErrorMessage(e)); }
  };
  if (flags === null) return <Loading label="Loading flags…" />;
  return (
    <>
      {Object.entries(flags).map(([k, v]) => (
        <div key={k} className="list-row">
          <span className="grow mono">{k}</span>
          <button className={'toggle' + (v ? ' on' : '')} role="switch" aria-checked={v} aria-label={k}
            onClick={() => toggle(k, !v)} />
        </div>
      ))}
    </>
  );
}

function AdminCosmetics({ toast }: { toast: (t: string) => void }) {
  const [id, setId] = useState('');
  const [name, setName] = useState('');
  const [category, setCategory] = useState('BUBBLE');
  const [rarity, setRarity] = useState('common');
  const [emoji, setEmoji] = useState('✨');
  const [retireId, setRetireId] = useState('');

  const create = async () => {
    try {
      await api.post('/admin/cosmetics', {
        id: id.trim(), name: name.trim(), category, rarity,
        asset: { emoji, gradient: ['#2a2a4a', '#1a1a30'] },
        description: name.trim(), obtainable: true, transferable: true,
      });
      toast('✅ Cosmetic created');
      setId(''); setName('');
    } catch (e) { toast(apiErrorMessage(e)); }
  };

  const retire = async () => {
    if (!retireId.trim() || !window.confirm(`Retire ${retireId}?`)) return;
    try {
      await api.post(`/admin/cosmetics/${encodeURIComponent(retireId.trim())}/retire`, {});
      toast('✅ Retired');
      setRetireId('');
    } catch (e) { toast(apiErrorMessage(e)); }
  };

  return (
    <>
      <h4>Create cosmetic</h4>
      <label className="field"><span>ID</span><input className="input" value={id} onChange={(e) => setId(e.target.value)} placeholder="bubble_solar" /></label>
      <label className="field"><span>Name</span><input className="input" value={name} onChange={(e) => setName(e.target.value)} /></label>
      <div className="row">
        <label className="field grow"><span>Category</span>
          <select className="input" value={category} onChange={(e) => setCategory(e.target.value)}>
            {['AVATAR', 'FRAME', 'BANNER', 'WALLPAPER', 'BUBBLE', 'SEND_EFFECT', 'REACTION', 'TYPING', 'STICKER', 'TITLE'].map((c) => <option key={c}>{c}</option>)}
          </select>
        </label>
        <label className="field grow"><span>Rarity</span>
          <select className="input" value={rarity} onChange={(e) => setRarity(e.target.value)}>
            {['common', 'uncommon', 'rare', 'epic', 'legendary', 'mythic'].map((r) => <option key={r}>{r}</option>)}
          </select>
        </label>
        <label className="field"><span>Emoji</span><input className="input" value={emoji} onChange={(e) => setEmoji(e.target.value)} style={{ width: 64 }} /></label>
      </div>
      <button className="btn small" onClick={create} disabled={!id.trim() || !name.trim()}>Create</button>
      <h4 style={{ marginTop: 16 }}>Retire cosmetic</h4>
      <div className="row">
        <input className="input" value={retireId} onChange={(e) => setRetireId(e.target.value)} placeholder="cosmetic id" />
        <button className="btn small danger" onClick={retire}>Retire</button>
      </div>
    </>
  );
}

function AdminEvents({ toast }: { toast: (t: string) => void }) {
  const [id, setId] = useState('');
  const [name, setName] = useState('');
  const create = async () => {
    try {
      await api.post('/admin/events', {
        id: id.trim(), name: name.trim(), description: name.trim(), theme: 'cosmic',
        status: 'draft', banner_asset: { emoji: '🎪' },
      });
      toast('✅ Event created (draft)');
      setId(''); setName('');
    } catch (e) { toast(apiErrorMessage(e)); }
  };
  return (
    <>
      <h4>Create event (draft)</h4>
      <label className="field"><span>ID</span><input className="input" value={id} onChange={(e) => setId(e.target.value)} /></label>
      <label className="field"><span>Name</span><input className="input" value={name} onChange={(e) => setName(e.target.value)} /></label>
      <button className="btn small" onClick={create} disabled={!id.trim() || !name.trim()}>Create</button>
      <p className="muted small">Manage challenges and status via PATCH /admin/events/:id.</p>
    </>
  );
}

function AdminEconomy({ toast }: { toast: (t: string) => void }) {
  const [overview, setOverview] = useState<Record<string, unknown> | null>(null);
  const [recon, setRecon] = useState<{ ok: boolean; issues: unknown[] } | null>(null);
  const [grantUid, setGrantUid] = useState('');
  const [grantCur, setGrantCur] = useState('shards');
  const [grantAmt, setGrantAmt] = useState('100');
  const load = useCallback(async () => {
    try { setOverview(await api.get<Record<string, unknown>>('/admin/economy/overview')); }
    catch (e) { toast(apiErrorMessage(e)); }
  }, [toast]);
  useEffect(() => { load(); }, [load]);

  const runRecon = async () => {
    try {
      const r = await api.get<{ ok: boolean; issues: unknown[] }>('/admin/reconciliation');
      setRecon(r);
      toast(r.ok ? '✅ Ledger reconciles' : `⚠️ ${r.issues.length} issues found`);
    } catch (e) { toast(apiErrorMessage(e)); }
  };

  const grant = async () => {
    try {
      await api.post('/admin/economy/grant', {
        user_id: parseInt(grantUid, 10), currency: grantCur, amount: parseInt(grantAmt, 10), reason: 'admin grant',
      });
      toast('✅ Granted (audited)');
      load();
    } catch (e) { toast(apiErrorMessage(e)); }
  };

  return (
    <>
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <h4>Overview</h4>
        <button className="btn small secondary" onClick={runRecon}>Run reconciliation</button>
      </div>
      {overview === null ? <Loading label="Loading…" /> : (
        <pre className="muted small" style={{ whiteSpace: 'pre-wrap', fontSize: 11 }}>{JSON.stringify(overview, null, 1).slice(0, 1500)}</pre>
      )}
      {recon && (
        <div className="card" style={{ borderColor: recon.ok ? 'var(--good)' : 'var(--bad)' }}>
          <strong>{recon.ok ? '✅ All wallets reconcile' : `⚠️ ${recon.issues.length} issues`}</strong>
          {!recon.ok && <pre className="small" style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify(recon.issues, null, 1).slice(0, 1000)}</pre>}
        </div>
      )}
      <h4>Audited grant</h4>
      <div className="row">
        <input className="input" placeholder="user id" value={grantUid} onChange={(e) => setGrantUid(e.target.value)} style={{ width: 90 }} />
        <select className="input" value={grantCur} onChange={(e) => setGrantCur(e.target.value)} style={{ width: 110 }}>
          <option value="shards">shards</option><option value="gems">gems</option><option value="event_tokens">event_tokens</option>
        </select>
        <input className="input" value={grantAmt} onChange={(e) => setGrantAmt(e.target.value)} style={{ width: 80 }} />
        <button className="btn small" onClick={grant}>Grant</button>
      </div>
    </>
  );
}

function AdminAudit() {
  const [rows, setRows] = useState<{ id: number; action: string; actor_id?: number; created_at: string }[]>([]);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    api.get<{ id: number; action: string; actor_id?: number; created_at: string }[]>('/admin/audit?limit=50')
      .then(setRows).catch((e) => setErr(apiErrorMessage(e)));
  }, []);
  if (err) return <ErrorState message={err} />;
  if (!rows.length) return <Empty icon="📋" title="No audit entries" hint="Admin actions will appear here." />;
  return (
    <table className="admin-table">
      <thead><tr><th>Time</th><th>Action</th><th>Actor</th></tr></thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.id}><td>{fmtDate(r.created_at)}</td><td className="mono">{r.action}</td><td>{r.actor_id ?? '—'}</td></tr>
        ))}
      </tbody>
    </table>
  );
}

function AdminReports({ toast }: { toast: (t: string) => void }) {
  const [rows, setRows] = useState<{ id: number; target_type: string; target_id: number; reason: string; status: string; created_at: string }[]>([]);
  const load = useCallback(async () => {
    try { setRows(await api.get('/admin/reports')); } catch (e) { toast(apiErrorMessage(e)); }
  }, [toast]);
  useEffect(() => { load(); }, [load]);
  const setStatus = async (id: number, status: string) => {
    try {
      await api.post(`/admin/reports/${id}`, { status });
      load();
    } catch (e) { toast(apiErrorMessage(e)); }
  };
  if (!rows.length) return <Empty icon="🛡️" title="No reports" hint="User reports will appear here." />;
  return (
    <>
      {rows.map((r) => (
        <div key={r.id} className="card">
          <div className="row">
            <div className="grow">
              <strong>#{r.id} {r.target_type} {r.target_id}</strong>
              <div className="muted small">{r.reason}</div>
              <div className="muted small">{fmtDate(r.created_at)} · {r.status}</div>
            </div>
          </div>
          <div className="row" style={{ gap: 6, marginTop: 8 }}>
            <button className="btn small secondary" onClick={() => setStatus(r.id, 'reviewed')}>Reviewed</button>
            <button className="btn small secondary" onClick={() => setStatus(r.id, 'actioned')}>Actioned</button>
            <button className="btn small secondary" onClick={() => setStatus(r.id, 'dismissed')}>Dismiss</button>
          </div>
        </div>
      ))}
    </>
  );
}

function AdminUsers({ toast }: { toast: (t: string) => void }) {
  const [q, setQ] = useState('');
  const [rows, setRows] = useState<Profile[]>([]);
  const search = async () => {
    try { setRows(await api.get<Profile[]>(`/admin/users?q=${encodeURIComponent(q)}`)); }
    catch (e) { toast(apiErrorMessage(e)); }
  };
  const suspend = async (u: Profile, on: boolean) => {
    if (!window.confirm(`${on ? 'Suspend' : 'Unsuspend'} @${u.username}?`)) return;
    try {
      await api.post(`/admin/users/${u.id}/${on ? 'suspend' : 'unsuspend'}`, {});
      toast(`✅ ${on ? 'Suspended' : 'Unsuspended'}`);
      search();
    } catch (e) { toast(apiErrorMessage(e)); }
  };
  return (
    <>
      <div className="row">
        <input className="input" placeholder="Search users…" value={q} onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') search(); }} />
        <button className="btn small" onClick={search}>Search</button>
      </div>
      <div style={{ marginTop: 8 }}>
        {rows.map((u) => (
          <div key={u.id} className="list-row">
            <Avatar profile={u} size={36} />
            <div className="grow">
              <strong>{u.display_name}</strong> <span className="muted small">@{u.username} · Lv{u.level}</span>
            </div>
            <button className="btn small danger" onClick={() => suspend(u, true)}>Suspend</button>
            <button className="btn small secondary" onClick={() => suspend(u, false)}>Unsuspend</button>
          </div>
        ))}
      </div>
      <p className="muted small">Admin user endpoints expose ownership/purchases only — never message content.</p>
    </>
  );
}
