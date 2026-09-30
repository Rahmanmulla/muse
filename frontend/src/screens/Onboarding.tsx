import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { api, ApiError, apiErrorMessage, setAuth } from '../api';
import { useApp } from '../store';
import { Avatar, CosmeticThumb, Empty, Loading, RarityBadge } from '../components/ui';
import { prettyCategory, type AuthResult, type CollectionBook, type Cosmetic, type Loadout, type Profile } from '../types';

// v3 signup state machine:
// Welcome → Email/Phone → Verify → Username → Password → Display name →
// Identity → Starter cosmetics → Referral (optional) → Find people → First chat.
// Personalization steps are skippable. Existing users keep the login screen.

type Step =
  | 'welcome' | 'identifier' | 'verify' | 'username' | 'password'
  | 'displayname' | 'identity' | 'cosmetics' | 'referral' | 'find';

const STEP_LABELS: Record<Step, string> = {
  welcome: 'Welcome',
  identifier: 'Verify your contact',
  verify: 'Enter the code',
  username: 'Choose a username',
  password: 'Set a password',
  displayname: 'Display name',
  identity: 'Pick your identity',
  cosmetics: 'Starter kit',
  referral: 'Referral code',
  find: 'Find people',
};

const STEP_ORDER: Step[] = ['welcome', 'identifier', 'verify', 'username', 'password', 'displayname', 'identity', 'cosmetics', 'referral', 'find'];
const PROGRESS_DOTS: Step[] = ['welcome', 'identifier', 'username', 'password', 'identity', 'find'];

function stepIndex(s: Step): number {
  return STEP_ORDER.indexOf(s);
}

export function Onboarding({ onDone }: { onDone: () => void }) {
  const { refreshMe, refreshWallet, refreshSettings, toast } = useApp();
  const [step, setStep] = useState<Step>('welcome');
  const [signupToken, setSignupToken] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const go = (s: Step) => { setErr(null); setStep(s); };

  const finishAuth = async (a: AuthResult) => {
    setAuth(a);
    try {
      await Promise.all([refreshMe(), refreshWallet(), refreshSettings()]);
    } catch { /* boot continues anyway */ }
  };

  const progress = stepIndex(step);

  return (
    <div className="auth-wrap">
      <div className="auth-logo" aria-hidden="true">✨</div>
      <h1><span className="brand">STIP</span></h1>
      <p className="auth-tag">Make every chat yours.</p>

      <div className="ob-progress" aria-hidden="true">
        {PROGRESS_DOTS.map((s) => (
          <span key={s} className={'ob-dot' + (stepIndex(s) <= progress ? ' on' : '')} />
        ))}
      </div>
      <p className="muted small" style={{ textAlign: 'center', margin: '0 0 18px' }}>
        {STEP_LABELS[step]}
      </p>

      {err && <div className="auth-err" role="alert">{err}</div>}

      {step === 'welcome' && (
        <WelcomeStep onStart={() => go('identifier')} onLogin={() => { window.location.hash = '#/login'; }} />
      )}
      {step === 'identifier' && (
        <IdentifierStep busy={busy} setBusy={setBusy} setErr={setErr}
          onSent={(token) => { setSignupToken(token); go('verify'); }} />
      )}
      {step === 'verify' && signupToken && (
        <VerifyStep token={signupToken} busy={busy} setBusy={setBusy} setErr={setErr}
          onVerified={() => go('username')} onBack={() => go('identifier')} />
      )}
      {step === 'username' && signupToken && (
        <UsernameStep token={signupToken} busy={busy} setBusy={setBusy} setErr={setErr}
          onDone={() => go('password')} />
      )}
      {step === 'password' && signupToken && (
        <PasswordStep token={signupToken} busy={busy} setBusy={setBusy} setErr={setErr}
          onDone={async (a) => { await finishAuth(a); go('displayname'); }} />
      )}
      {step === 'displayname' && (
        <DisplayNameStep onDone={() => go('identity')} onSkip={() => go('identity')} />
      )}
      {step === 'identity' && (
        <IdentityStep onDone={() => go('cosmetics')} onSkip={() => go('cosmetics')} toast={toast} />
      )}
      {step === 'cosmetics' && (
        <StarterCosmeticsStep onDone={() => go('referral')} onSkip={() => go('referral')} toast={toast} />
      )}
      {step === 'referral' && (
        <ReferralStep onDone={() => go('find')} onSkip={() => go('find')} />
      )}
      {step === 'find' && (
        <FindPeopleStep onDone={onDone} onSkip={onDone} />
      )}
    </div>
  );
}

function WelcomeStep({ onStart, onLogin }: { onStart: () => void; onLogin: () => void }) {
  return (
    <div style={{ textAlign: 'center' }}>
      <p className="muted" style={{ marginBottom: 20 }}>
        A messenger where your chats look like <em>you</em> — bubbles, frames,
        wallpapers, effects. Messaging stays free and instant; style is yours to collect.
      </p>
      <button className="btn" style={{ width: '100%', marginBottom: 10 }} onClick={onStart}>
        Create account
      </button>
      <button className="btn secondary" style={{ width: '100%' }} onClick={onLogin}>
        I already have an account
      </button>
      <p className="muted small" style={{ marginTop: 16 }}>
        New accounts get a starter cosmetic kit + 100 🔷 welcome bonus.
      </p>
    </div>
  );
}

function IdentifierStep({ busy, setBusy, setErr, onSent }: {
  busy: boolean; setBusy: (b: boolean) => void; setErr: (e: string | null) => void;
  onSent: (token: string, devCode: string | null) => void;
}) {
  const [channel, setChannel] = useState<'phone' | 'email'>('phone');
  const [identifier, setIdentifier] = useState('');
  const [devCode, setDevCode] = useState<string | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true); setErr(null);
    try {
      const r = await api.post<{ ok: boolean; signup_token: string; dev_code?: string }>(
        '/auth/signup/start', { identifier: identifier.trim() });
      setDevCode(r.dev_code ?? null);
      onSent(r.signup_token, r.dev_code ?? null);
    } catch (e2) {
      setErr(apiErrorMessage(e2));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit}>
      <div className="auth-tabs" role="tablist" aria-label="Channel">
        <button type="button" className={'btn small' + (channel === 'phone' ? '' : ' secondary')} onClick={() => setChannel('phone')}>Phone</button>
        <button type="button" className={'btn small' + (channel === 'email' ? '' : ' secondary')} onClick={() => setChannel('email')}>Email</button>
      </div>
      <label className="field">
        <span>{channel === 'phone' ? 'Phone number' : 'Email address'}</span>
        <input className="input" value={identifier} onChange={(e) => setIdentifier(e.target.value)} required
          inputMode={channel === 'phone' ? 'tel' : 'email'}
          autoComplete={channel === 'phone' ? 'tel' : 'email'}
          placeholder={channel === 'phone' ? '+15551234567' : 'you@example.com'} />
      </label>
      {devCode && <p className="muted small">Dev mode code: <strong>{devCode}</strong> (shown in-band)</p>}
      <button className="btn" style={{ width: '100%' }} disabled={busy || !identifier.trim()}>
        {busy ? '…' : 'Send verification code'}
      </button>
    </form>
  );
}

function VerifyStep({ token, busy, setBusy, setErr, onVerified, onBack }: {
  token: string; busy: boolean; setBusy: (b: boolean) => void; setErr: (e: string | null) => void;
  onVerified: () => void; onBack: () => void;
}) {
  const [code, setCode] = useState('');
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true); setErr(null);
    try {
      const r = await api.post<{ ok: boolean; verified: boolean }>('/auth/signup/verify', { signup_token: token, code: code.trim() });
      if (r.verified) onVerified();
      else setErr('Code not verified — try again.');
    } catch (e2) {
      setErr(apiErrorMessage(e2));
    } finally {
      setBusy(false);
    }
  };
  return (
    <form onSubmit={submit}>
      <label className="field">
        <span>6-digit verification code</span>
        <input className="input" value={code} onChange={(e) => setCode(e.target.value)} required
          inputMode="numeric" autoComplete="one-time-code" placeholder="••••••" maxLength={6} />
      </label>
      <button className="btn" style={{ width: '100%', marginBottom: 8 }} disabled={busy || code.trim().length < 4}>
        {busy ? '…' : 'Verify'}
      </button>
      <button type="button" className="btn small secondary" style={{ width: '100%' }} onClick={onBack}>← Change number/email</button>
    </form>
  );
}

function UsernameStep({ token, busy, setBusy, setErr, onDone }: {
  token: string; busy: boolean; setBusy: (b: boolean) => void; setErr: (e: string | null) => void;
  onDone: () => void;
}) {
  const [username, setUsername] = useState('');
  const [avail, setAvail] = useState<'idle' | 'checking' | 'yes' | 'no' | 'unknown'>('idle');
  const [availMsg, setAvailMsg] = useState('');

  // Live availability check (endpoint needs auth; pre-signup it 401s — then we
  // just confirm on submit via the reserve call).
  useEffect(() => {
    const u = username.trim().toLowerCase();
    if (!/^[a-z0-9_]{3,20}$/.test(u)) { setAvail('idle'); return; }
    setAvail('checking');
    const t = window.setTimeout(async () => {
      try {
        await api.get(`/users/me/username/check?username=${encodeURIComponent(u)}`);
        setAvail('yes'); setAvailMsg('Available ✓');
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) { setAvail('unknown'); setAvailMsg(''); }
        else { setAvail('no'); setAvailMsg(apiErrorMessage(e)); }
      }
    }, 450);
    return () => window.clearTimeout(t);
  }, [username]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true); setErr(null);
    try {
      await api.post('/auth/signup/username', { signup_token: token, username: username.trim().toLowerCase() });
      onDone();
    } catch (e2) {
      setErr(apiErrorMessage(e2));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit}>
      <label className="field">
        <span>Choose your username</span>
        <input className="input" value={username} onChange={(e) => setUsername(e.target.value.toLowerCase())}
          required minLength={3} maxLength={20} placeholder="3–20 chars: a–z, 0–9, _" autoComplete="username" />
      </label>
      {avail === 'checking' && <p className="muted small">Checking…</p>}
      {avail === 'yes' && <p className="small" style={{ color: 'var(--good)' }}>{availMsg}</p>}
      {avail === 'no' && <p className="small" style={{ color: 'var(--bad)' }}>{availMsg}</p>}
      <p className="muted small">Usernames are globally unique. Your login stays your email/phone — the username is your identity.</p>
      <button className="btn" style={{ width: '100%' }} disabled={busy || !/^[a-z0-9_]{3,20}$/.test(username.trim())}>
        {busy ? '…' : 'Claim username'}
      </button>
    </form>
  );
}

function PasswordStep({ token, busy, setBusy, setErr, onDone }: {
  token: string; busy: boolean; setBusy: (b: boolean) => void; setErr: (e: string | null) => void;
  onDone: (a: AuthResult) => Promise<void>;
}) {
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (password !== confirm) { setErr('Passwords do not match.'); return; }
    setBusy(true); setErr(null);
    try {
      const a = await api.post<AuthResult>('/auth/signup/complete', {
        signup_token: token,
        password,
        platform: 'web',
        device_name: typeof navigator !== 'undefined' ? navigator.userAgent.slice(0, 80) : 'web',
      });
      await onDone(a);
    } catch (e2) {
      setErr(apiErrorMessage(e2));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit}>
      <label className="field">
        <span>Create a password</span>
        <input className="input" type="password" value={password} onChange={(e) => setPassword(e.target.value)}
          required minLength={6} autoComplete="new-password" />
      </label>
      <label className="field">
        <span>Confirm password</span>
        <input className="input" type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)}
          required minLength={6} autoComplete="new-password" />
      </label>
      <button className="btn" style={{ width: '100%' }} disabled={busy || password.length < 6}>
        {busy ? '…' : 'Create my account'}
      </button>
    </form>
  );
}

function DisplayNameStep({ onDone, onSkip }: { onDone: () => void; onSkip: () => void }) {
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true); setErr(null);
    try {
      if (name.trim()) await api.patch('/users/me', { display_name: name.trim() });
      onDone();
    } catch (e2) {
      setErr(apiErrorMessage(e2));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit}>
      <p className="muted" style={{ textAlign: 'center' }}>What should friends call you?</p>
      {err && <div className="auth-err" role="alert">{err}</div>}
      <label className="field">
        <span>Display name (optional)</span>
        <input className="input" value={name} onChange={(e) => setName(e.target.value)} maxLength={64} placeholder="e.g. Nova" />
      </label>
      <button className="btn" style={{ width: '100%', marginBottom: 8 }} disabled={busy}>{busy ? '…' : 'Continue'}</button>
      <button type="button" className="btn small secondary" style={{ width: '100%' }} onClick={onSkip}>Skip for now</button>
    </form>
  );
}

async function equipCosmetic(toast: (t: string) => void, cosmetic: Cosmetic, slot: string): Promise<boolean> {
  try {
    const loadouts = await api.get<Loadout[]>('/loadouts');
    const active = loadouts.find((l) => l.is_active) ?? loadouts[0];
    if (!active) { toast('No loadout found.'); return false; }
    await api.put(`/loadouts/${active.id}`, { slot, cosmetic_id: cosmetic.id });
    return true;
  } catch (e) {
    toast(apiErrorMessage(e));
    return false;
  }
}

function IdentityStep({ onDone, onSkip, toast }: { onDone: () => void; onSkip: () => void; toast: (t: string) => void }) {
  const [avatars, setAvatars] = useState<Cosmetic[] | null>(null);
  const [picked, setPicked] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.get<CollectionBook>('/collection')
      .then((b) => setAvatars(b.items.filter((i) => i.category === 'profile.avatar' && i.owned)))
      .catch(() => setAvatars([]));
  }, []);

  const choose = async (c: Cosmetic) => {
    setPicked(c.id);
    setBusy(true);
    const ok = await equipCosmetic(toast, c, 'AVATAR');
    setBusy(false);
    if (ok) { toast(`✨ ${c.name} equipped`); onDone(); }
  };

  return (
    <div>
      <p className="muted" style={{ textAlign: 'center' }}>Pick your first identity — a 2D avatar from your starter kit.</p>
      {avatars === null ? <Loading label="Opening your starter kit…" /> :
        avatars.length === 0 ? (
          <Empty icon="🪞" title="No avatars yet" hint="Your starter kit is on its way — you can pick one later in Collection." />
        ) : (
          <div className="grid">
            {avatars.map((c) => (
              <div key={c.id} className="cos-card" onClick={() => choose(c)} role="button" tabIndex={0}
                onKeyDown={(e) => { if (e.key === 'Enter') choose(c); }}
                style={picked === c.id ? { borderColor: 'var(--accent)' } : undefined}>
                <CosmeticThumb cosmetic={c} size={52} />
                <span className="nm">{c.name}</span>
                <RarityBadge rarity={c.rarity} />
              </div>
            ))}
          </div>
        )}
      <button className="btn small secondary" style={{ width: '100%', marginTop: 16 }} disabled={busy} onClick={onSkip}>
        Skip for now
      </button>
      <p className="muted small" style={{ textAlign: 'center', marginTop: 8 }}>
        Photo identities aren't supported yet — avatar cosmetics are the identity system for now.
      </p>
    </div>
  );
}

function StarterCosmeticsStep({ onDone, onSkip, toast }: { onDone: () => void; onSkip: () => void; toast: (t: string) => void }) {
  const [items, setItems] = useState<Cosmetic[] | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  useEffect(() => {
    api.get<CollectionBook>('/collection')
      .then((b) => setItems(b.items.filter((i) => i.owned && i.category !== 'profile.avatar').slice(0, 12)))
      .catch(() => setItems([]));
  }, []);

  const SLOT_FOR: Record<string, string> = {
    'profile.frame': 'FRAME', 'profile.banner': 'BANNER', 'profile.nameplate': 'NAMEPLATE',
    'chat.wallpaper': 'WALLPAPER', 'chat.bubble': 'BUBBLE',
  };

  const equip = async (c: Cosmetic) => {
    const slot = SLOT_FOR[c.category];
    if (!slot) { toast('This one equips from the Collection screen.'); return; }
    setBusyId(c.id);
    const ok = await equipCosmetic(toast, c, slot);
    setBusyId(null);
    if (ok) toast(`✨ ${c.name} equipped`);
  };

  return (
    <div>
      <p className="muted" style={{ textAlign: 'center' }}>Your starter kit — tap anything to equip it.</p>
      {items === null ? <Loading label="Opening your starter kit…" /> :
        items.length === 0 ? (
          <Empty icon="🎒" title="Starter kit is empty" hint="Claim free items in the Shop to get started." />
        ) : (
          <div className="grid">
            {items.map((c) => (
              <div key={c.id} className="cos-card" onClick={() => equip(c)} role="button" tabIndex={0}
                onKeyDown={(e) => { if (e.key === 'Enter') equip(c); }}>
                <CosmeticThumb cosmetic={c} size={52} />
                <span className="nm">{c.name}</span>
                <span className="muted small">{busyId === c.id ? 'Equipping…' : prettyCategory(c.category)}</span>
              </div>
            ))}
          </div>
        )}
      <button className="btn" style={{ width: '100%', marginTop: 16 }} onClick={onDone}>Continue</button>
      <button className="btn small secondary" style={{ width: '100%', marginTop: 8 }} onClick={onSkip}>Skip</button>
    </div>
  );
}

function ReferralStep({ onDone, onSkip }: { onDone: () => void; onSkip: () => void }) {
  const { toast } = useApp();
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);

  const apply = async (e: FormEvent) => {
    e.preventDefault();
    if (!code.trim()) { onDone(); return; }
    setBusy(true);
    try {
      const r = await api.post<{ ok: boolean; rewarded_shards: number }>('/referrals/apply', { code: code.trim() });
      toast(`🎁 Referral applied! +${r.rewarded_shards} 🔷 for you and your friend.`);
      onDone();
    } catch (e2) {
      toast(apiErrorMessage(e2));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={apply}>
      <p className="muted" style={{ textAlign: 'center' }}>
        Were you invited by a friend? Enter their code — <strong>you both get 50 🔷</strong>.
      </p>
      <label className="field">
        <span>Referral code (optional)</span>
        <input className="input" value={code} onChange={(e) => setCode(e.target.value)} placeholder="STIP-…" />
      </label>
      <button className="btn" style={{ width: '100%', marginBottom: 8 }} disabled={busy}>{busy ? '…' : 'Continue'}</button>
      <button type="button" className="btn small secondary" style={{ width: '100%' }} onClick={onSkip}>Skip</button>
    </form>
  );
}

function FindPeopleStep({ onDone, onSkip }: { onDone: () => void; onSkip: () => void }) {
  const { toast } = useApp();
  const [q, setQ] = useState('');
  const [results, setResults] = useState<Profile[]>([]);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [greet, setGreet] = useState('');

  useEffect(() => {
    if (!q.trim()) { setResults([]); return; }
    const t = window.setTimeout(async () => {
      try {
        setResults(await api.get<Profile[]>(`/users/search?q=${encodeURIComponent(q.trim())}`));
      } catch { /* ignore */ }
    }, 300);
    return () => window.clearTimeout(t);
  }, [q]);

  const openChat = async (u: Profile) => {
    setBusyId(u.id);
    try {
      // Try a direct conversation; if the backend gates strangers behind
      // message requests it will 400/403 — fall back to a request.
      const c = await api.post<{ id: number }>('/conversations', { user_id: u.id });
      window.location.hash = `#/chat/${c.id}`;
      onDone();
    } catch (e) {
      try {
        const r = await api.post<{ direct: boolean; conversation_id?: number; request?: { id: number } }>(
          '/requests', { user_id: u.id, body: greet.trim() || `Hi ${u.display_name}! 👋` });
        if (r.direct && r.conversation_id) {
          window.location.hash = `#/chat/${r.conversation_id}`;
        } else {
          toast('📥 Message request sent — they\'ll see it when they accept.');
        }
        onDone();
      } catch (e2) {
        toast(apiErrorMessage(e2));
      }
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div>
      <p className="muted" style={{ textAlign: 'center' }}>Find someone to talk to — search by username.</p>
      <input className="input" placeholder="Search username…" value={q}
        onChange={(e) => setQ(e.target.value)} autoFocus aria-label="Search users" />
      <label className="field" style={{ marginTop: 10 }}>
        <span>Say hello (sent with a message request if you're not contacts yet)</span>
        <input className="input" value={greet} onChange={(e) => setGreet(e.target.value)}
          placeholder="Hi! 👋" maxLength={160} />
      </label>
      <div style={{ marginTop: 6 }}>
        {results.map((u) => (
          <div key={u.id} className="list-row">
            <Avatar profile={u} size={40} />
            <div className="grow">
              <div style={{ fontWeight: 600 }}>{u.display_name}</div>
              <div className="muted small">@{u.username}</div>
            </div>
            <button className="btn small" disabled={busyId === u.id} onClick={() => openChat(u)}>
              {busyId === u.id ? '…' : 'Chat'}
            </button>
          </div>
        ))}
        {q.trim() && results.length === 0 && (
          <p className="muted small" style={{ textAlign: 'center', padding: 12 }}>No users found.</p>
        )}
      </div>
      <button className="btn small secondary" style={{ width: '100%', marginTop: 16 }} onClick={onSkip}>
        Skip — I'll explore first
      </button>
    </div>
  );
}
