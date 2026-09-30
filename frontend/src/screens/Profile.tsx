import { useCallback, useEffect, useState } from 'react';
import { QRCodeSVG } from 'qrcode.react';
import { api, apiErrorMessage } from '../api';
import { useApp } from '../store';
import { Avatar, Empty, ErrorBoundary, ErrorState, Loading, ProgressBar, assetGradient } from '../components/ui';
import { CosmeticSheet } from '../components/CosmeticSheet';
import type { Profile as ProfileType, ProgressSnapshot, ReferralInfo } from '../types';

export function Profile({ username, onSettings, onCollection }: {
  username?: string; onSettings: () => void; onCollection: () => void;
}) {
  const { me, refreshMe, toast } = useApp();
  const [profile, setProfile] = useState<ProfileType | null>(null);
  const [progress, setProgress] = useState<ProgressSnapshot | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [nameEdit, setNameEdit] = useState(false);
  const [displayName, setDisplayName] = useState('');
  const [busy, setBusy] = useState(false);
  const [sheetCosmeticId, setSheetCosmeticId] = useState<string | null>(null);
  const [qrOpen, setQrOpen] = useState(false);
  const [referral, setReferral] = useState<ReferralInfo | null>(null);

  const own = !username || username === me?.username;

  const load = useCallback(async () => {
    setErr(null);
    try {
      const p = own
        ? await api.get<ProfileType>('/users/me')
        : await api.get<ProfileType>(`/users/${encodeURIComponent(username!)}`);
      setProfile(p);
      setDisplayName(p.display_name);
      if (own) {
        try {
          setProgress(await api.get<ProgressSnapshot>('/profile/progress'));
        } catch {
          /* progress is auxiliary */
        }
        try {
          setReferral(await api.get<ReferralInfo>('/referrals/mine'));
        } catch {
          /* referrals are auxiliary */
        }
      }
    } catch (e) {
      setErr(apiErrorMessage(e));
    }
  }, [own, username]);

  useEffect(() => { load(); }, [load]);

  const saveName = async () => {
    const v = displayName.trim();
    if (!v) { toast('Display name cannot be empty.'); return; }
    setBusy(true);
    try {
      await api.patch('/users/me', { display_name: v });
      setNameEdit(false);
      refreshMe();
      load();
      toast('✅ Display name updated');
    } catch (e) {
      toast(apiErrorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const block = async () => {
    if (!profile || !window.confirm(`Block @${profile.username}?`)) return;
    try {
      await api.post('/users/block', { user_id: profile.id });
      toast('🚫 User blocked');
    } catch (e) {
      toast(apiErrorMessage(e));
    }
  };

  const report = async () => {
    if (!profile) return;
    const reason = window.prompt('Report reason:');
    if (!reason) return;
    try {
      await api.post('/reports', { target_type: 'user', target_id: profile.id, reason });
      toast('🛡️ Report submitted');
    } catch (e) {
      toast(apiErrorMessage(e));
    }
  };

  if (err) return (
    <div><div className="topbar"><h1>🙂 Profile</h1></div><div className="screen"><ErrorState message={err} onRetry={load} /></div></div>
  );
  if (!profile) return (
    <div><div className="topbar"><h1>🙂 Profile</h1></div><div className="screen"><Loading label="Loading profile…" /></div></div>
  );

  const bannerAsset = profile.banner?.asset;

  return (
    <div>
      <div className="topbar">
        <h1>🙂 Profile</h1>
        <div className="grow" />
        {own && <button className="icon-btn" onClick={onSettings} aria-label="Settings">⚙️</button>}
      </div>
      <div className="screen">
        <div className="profile-hero">
          <div className="profile-banner" style={bannerAsset ? { background: assetGradient(bannerAsset) } : undefined} />
          <div className="profile-row">
            <Avatar profile={profile} size={72} />
            <div className="grow" style={{ paddingTop: 34 }}>
              {nameEdit ? (
                <div className="row">
                  <input className="input" value={displayName} onChange={(e) => setDisplayName(e.target.value)} maxLength={64} />
                  <button className="btn small" disabled={busy} onClick={saveName}>Save</button>
                  <button className="btn small secondary" onClick={() => setNameEdit(false)}>✕</button>
                </div>
              ) : (
                <div style={{ fontSize: 20, fontWeight: 800 }}>
                  {profile.display_name}
                  {own && <button className="btn small secondary" style={{ marginLeft: 8 }} onClick={() => setNameEdit(true)}>Edit</button>}
                </div>
              )}
              <div className="muted">@{profile.username} · Lv {profile.level}</div>
            </div>
          </div>
          <div style={{ padding: '12px 16px 16px' }}>
            <div className="row wrap" style={{ gap: 6, marginBottom: 8 }}>
              {profile.avatar && <span className="title-pill clickable" title="Avatar — tap to discover" onClick={() => setSheetCosmeticId(profile.avatar!.id)}>🪞 {profile.avatar.name}</span>}
              {profile.frame && <span className="title-pill clickable" title="Frame — tap to discover" onClick={() => setSheetCosmeticId(profile.frame!.id)}>⭕ {profile.frame.name}</span>}
              {profile.nameplate && <span className="title-pill clickable" title="Nameplate — tap to discover" onClick={() => setSheetCosmeticId(profile.nameplate!.id)}>🏷️ {profile.nameplate.name}</span>}
              {profile.profile_effect && <span className="title-pill clickable" title="Effect — tap to discover" onClick={() => setSheetCosmeticId(profile.profile_effect!.id)}>✨ {profile.profile_effect.name}</span>}
            </div>
            <ProgressBar value={profile.xp % 1000} max={1000} label="XP progress" />
            <div className="muted small" style={{ marginTop: 4 }}>{profile.xp} XP · Level {profile.level}</div>
          </div>
        </div>

        {own && (
          <div className="row wrap" style={{ gap: 8, marginBottom: 12 }}>
            <button className="btn small secondary" onClick={onCollection}>🎒 Collection</button>
            <button className="btn small secondary" onClick={onSettings}>⚙️ Settings</button>
            <button className="btn small secondary" onClick={() => setQrOpen(true)}>📱 Share</button>
            {profile.is_admin && <span className="title-pill">ADMIN</span>}
          </div>
        )}

        {!own && (
          <div className="row wrap" style={{ gap: 8, marginBottom: 12 }}>
            <button className="btn small secondary" onClick={block}>🚫 Block</button>
            <button className="btn small secondary" onClick={report}>🛡️ Report</button>
          </div>
        )}

        {own && progress && (
          <>
            <div className="card">
              <h3 style={{ marginTop: 0 }}>📊 Stats</h3>
              {Object.entries(progress.stats ?? {}).map(([k, v]) => (
                <div key={k} className="kv"><span className="muted">{k.replace(/_/g, ' ')}</span><strong>{v}</strong></div>
              ))}
            </div>
            <div className="card">
              <h3 style={{ marginTop: 0 }}>🖼️ Collection</h3>
              <div className="row">
                <span className="grow"><strong>{progress.collection.owned}</strong> <span className="muted">/ {progress.collection.total} ({progress.collection.percent}%)</span></span>
                <span>🌟 {progress.legendary_count} legendary+</span>
              </div>
              <ProgressBar value={progress.collection.owned} max={progress.collection.total} label="Collection" />
            </div>
            {progress.titles.length > 0 && (
              <div className="card">
                <h3 style={{ marginTop: 0 }}>🏷️ Titles</h3>
                {progress.titles.map((t) => <span key={t} className="title-pill">{t}</span>)}
              </div>
            )}
          </>
        )}

        {!own && <p className="muted small" style={{ textAlign: 'center' }}>Cosmetics are style only — zero gameplay advantage. ✨</p>}

        {own && referral && (
          <div className="card">
            <h3 style={{ marginTop: 0 }}>🎁 Your referral code</h3>
            <div className="row" style={{ alignItems: 'center' }}>
              <div className="grow">
                <strong className="mono" style={{ fontSize: 18 }}>{referral.code}</strong>
                <div className="muted small">{referral.total_credited}/{referral.credit_limit_30d} used (30d) · both sides get {referral.reward_shards} 🔷</div>
              </div>
              <button className="btn small secondary" onClick={() => {
                navigator.clipboard?.writeText(referral.code);
                toast('📋 Code copied');
              }}>Copy</button>
            </div>
          </div>
        )}
      </div>

      {sheetCosmeticId && (
        <CosmeticSheet cosmeticId={sheetCosmeticId} onClose={() => setSheetCosmeticId(null)} />
      )}
      {qrOpen && (
        <ShareQR username={profile.username} displayName={profile.display_name} onClose={() => setQrOpen(false)} />
      )}
    </div>
  );
}

// Share card: QR encoding STIP:{username}, addable via Chats → New chat → Add by code.
function ShareQR({ username, displayName, onClose }: { username: string; displayName: string; onClose: () => void }) {
  const { toast } = useApp();
  const payload = `STIP:${username}`;
  return (
    <div className="modal-overlay" onClick={onClose} role="presentation">
      <div className="modal" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-label="Share your profile">
        <div className="modal-head">
          <h2>📱 Add me on STIP</h2>
          <button className="icon-btn" onClick={onClose} aria-label="Close">✕</button>
        </div>
        <div style={{ textAlign: 'center' }}>
          <div className="qr-box">
            <QRCodeSVG value={payload} size={200} bgColor="transparent" fgColor="currentColor" />
          </div>
          <p style={{ fontWeight: 700, margin: '10px 0 2px' }}>{displayName}</p>
          <p className="muted small" style={{ marginTop: 0 }}>@{username}</p>
          <p className="muted small">They scan this in <strong>Chats → + → Add by code</strong> to message you.</p>
          <div className="row" style={{ justifyContent: 'center', gap: 8 }}>
            <button className="btn small secondary" onClick={() => { navigator.clipboard?.writeText(payload); toast('📋 Code copied'); }}>
              Copy code
            </button>
            <button className="btn small" onClick={onClose}>Done</button>
          </div>
        </div>
      </div>
    </div>
  );
}

// Wrap in an error boundary guard so cosmetic rendering never breaks the profile.
export function SafeProfile(props: Parameters<typeof Profile>[0]) {
  return (
    <ErrorBoundary fallback={<div className="screen"><Empty icon="🙂" title="Profile unavailable" hint="Something went wrong rendering this profile." /></div>}>
      <Profile {...props} />
    </ErrorBoundary>
  );
}
