# STIP API Contract

Base URL (dev): `http://127.0.0.1:8772`
WebSocket: `ws://127.0.0.1:8772/ws?token=<access_token>`

Auth: `Authorization: Bearer <access_token>` on all endpoints except
`/auth/*` signup/login/recovery/preview, `/health`. Access tokens last 6h
and are bound to a device row (created at signup/login; revoked on
logout/device-revoke). There is no separate refresh endpoint — re-login to
get a new token.

Conventions: JSON bodies; errors are `{"detail": "..."}`; timestamps are
ISO-8601 UTC. Money is integer minor units. **Never trust client balances —
the server is authoritative.**

---

## Auth: signup (v3), login, devices

### v3 signup state machine (email/phone-first)

- `POST /auth/signup/start` `{identifier}` (email or phone) → `{ok, signup_token, dev_code}` (dev mode returns code in-band; resends are fine; 400 if the identifier is already registered). 30 min to finish.
- `POST /auth/signup/verify` `{signup_token, code}` → `{ok, verified}`. 6-digit OTP, single-use, 10-min TTL, max 5 sends/hour per channel+address+purpose.
- `POST /auth/signup/username` `{signup_token, username}` → `{ok, username}`. Reserves the name.
- `POST /auth/signup/complete` `{signup_token, password, display_name?, platform?, device_name?}` → `{access_token, token_type, expires_in, user_id, username, new_device, jti}`. Creates the real user, flips `identifier_verified`, grants the starter kit + 100-shard welcome bonus, and the completing device starts **trusted**.
- The legacy `POST /auth/signup` `{username, display_name?, password?, email?, phone?, utc_offset_minutes?}` still works (grandfathered verified) but is **deprecated** — new clients should use the v3 machine.

### Account recovery (access only — never changes anything else)

- `POST /auth/recovery/start` `{identifier}` → `{ok, dev_code?}`. Generic "if an account exists" answer for unknown identifiers (no code leaked). 5 sends/hour limit.
- `POST /auth/recovery/reset` `{identifier, code, new_password}` → `{access_token, ...}`. Resets the password, **revokes all devices** (everyone gets logged out), and clears any lockout. Rate-limited: 8 bad tries → 403 lock 15 min.

### Username policy

`^[a-z0-9_]{3,20}$` (NFKC-normalized, lowercase). Reserved: admin, support,
stip, system, official, staff, help, security. **30-day cooldown** between
changes; a released name is held 30 days (tombstone) before anyone else can
claim it. Shell (unfinished-signup) usernames are never searchable.

- `GET /users/me/username/check?username=` → `{available: true}` or 400 with reason
- `POST /users/me/username` `{username}` → `{ok, username}` (dedicated rename endpoint)
- `PATCH /users/me` `{display_name?, username?}` — username changes go through the same v3 policy/cooldown/tombstone.

### Referrals

- `GET /referrals/mine` → `{code, credited_last_30d, total_credited, reward_shards, credit_limit_30d}`. Code format `STIP-<user_id>-<hex>`.
- `POST /referrals/apply` `{code}` → `{ok, rewarded_shards: 50}`. **Both sides get 50 shards.** Rules: referee account ≤ 7 days old; one code per account; no self-referral; referrer can pay out at most 20 rewards per 30 days.

### Login & devices

- `POST /auth/login` `{login, password, device_name?, platform?}` → tokens + `new_device` flag. Logging in from an **unrecognized device name** sets `new_device: true`, records an audit entry, and sends the user a "New sign-in" security notification. 8 bad tries → 403 lockout 15 min.
- `POST /auth/logout` → revokes current device.
- `GET /auth/devices` → `[{id, device_name, platform, trusted, verified_at, created_at, revoked}]`. Signup-completed devices are trusted; legacy logins are not.
- `POST /auth/devices/{id}/revoke`, `POST /auth/devices/revoke-others`
- `POST /auth/devices/verify` `{channel, address, code}` → `{ok, trusted: true}`. Marks the current device trusted after an OTP to the email/phone on record (purpose `device`).
- `POST /auth/password` `{current_password, new_password, otp_channel?, otp_address?, otp_code?}`. On an **untrusted** device for an account with an email/phone on record, a fresh `password_change`-purpose OTP to the account's own address is required in the same request (request one via `POST /auth/otp/request`); the OTP must go to *your* address, not someone else's. A successful gated change also marks the device trusted. Accounts with no email/phone on record fall back to current-password only.
- `POST /auth/otp/request` `{channel: phone|email, address, purpose: signup|recovery|device|password_change}` → `{ok, dev_code}` (dev mode returns code in-band)
- `POST /auth/otp/verify` `{channel, address, code, purpose}` → `{ok, verified}` (single-use; the channel/address pair must match a user for recovery/device/password_change)
- `GET /health` → `{ok: true}`

## Users, settings, safety

- `GET /users/me` → profile (display_name, equipped cosmetics resolved as `avatar`, `frame`, `banner`, `nameplate`, `profile_effect` objects) + `wallets`, `is_admin`, `online`
- `GET /users/search?q=` → profiles (blocked users excluded; pending shells excluded)
- `GET /users/{username}` → public profile
- `GET /users/me/settings` / `PUT /users/me/settings/{key}` `{value}` — keys: `notification_preview` (full|sender|none), `reduced_motion` (bool), `theme` (system|dark|light), `message_requests` (bool, default true — see Message requests)
- `POST /users/block` `{user_id}` / `POST /users/unblock` `{user_id}` / `GET /users/me/blocks`
- `POST /reports` `{target_type, target_id, reason}`

## Conversations, message requests & messaging (1:1; groups structurally supported)

### Message requests (explicit gate)

- `POST /requests` `{username? | user_id?, body}` → `{direct: false, request: {id, conversation_id, status, created_at}}`. Fails 400 for self / blank body / already have a visible conversation / already pending; 403 if blocked either way; 429 at 10 new requests/day per sender. If the recipient set `message_requests=false`, returns `{direct: true, conversation_id, message_id}` — a normal conversation + visible message, no request.
- `GET /requests/inbox` → `[{id, conversation_id, sender:{...}, body, status, created_at}]` (pending only, newest first)
- `POST /requests/{id}/accept` → `{ok, conversation_id}` — the hidden conversation and messages become visible; friendship bumps fire (achievements, event points, streaks). Notifies the requester via WS `request.accepted`.
- `POST /requests/{id}/reject` `{report?, reason?}` → `{ok}` — the shadow conversation is deleted; optionally files a safety report. Notifies via WS `request.rejected`.
- While pending, messages sent into the shadow conversation are **hidden from the recipient** (visible only to the sender) until accept. Pending conversations never appear in `GET /conversations`.

### Messaging

- `POST /conversations` `{username? | user_id? | member_ids?, title?}` → convo. 403 if blocked either way. Reuses existing 1:1.
- `GET /conversations` → `[{id, is_group, title, members:[profiles], last_message, unread_count, updated_at}]`. Conversation responses include a `request` object (`{status, id}`) while a message request is pending.
- `POST /conversations/{id}/messages` `{body?, kind?, client_msg_id?, reply_to_id?, cosmetic_id?, send_effect_id?, sticker_pack_id?, sticker_id?, media_path?, media_mime?, media_size?}` → message. **`client_msg_id` (uuid) makes sends idempotent**: retrying with the same id returns `200 {duplicate: true}` and the original message — no double-send. Server snapshots sender's active BUBBLE slot into `cosmetic_id` when not supplied. Every message carries `server_sequence` (monotonic per conversation). Awards XP, bumps `message_sent` (achievements, event challenges, event points), updates streaks, friendship milestones, notifies members.
- `GET /conversations/{id}/messages?before&limit` → newest-first page
- `PATCH /conversations/{id}/messages/{mid}` `{body}` (own messages only)
- `DELETE /conversations/{id}/messages/{mid}` (tombstone; body nulled)
- `POST .../messages/{mid}/reactions` `{emoji, effect_id?}` / `DELETE .../messages/{mid}/reactions?emoji=` → `{ok: true}`
- `POST .../messages/{mid}/forward` `{target_conv_id}`
- `POST .../messages/{mid}/pin` / `GET .../pins`
- `POST /conversations/{id}/read` `{message_id}` → read cursors + receipts
- `POST /conversations/{id}/typing` `{typing: bool}` → WS `typing` event
- `GET /conversations/{id}/search?q=`
- `GET|PUT /conversations/{id}/draft` `{body}` — server-persisted drafts
- `POST /media/upload` multipart `file` → `{media_path, media_url, media_mime, media_size}` (10MB cap; served at `/media/*`)

Message shape: `{id, conversation_id, sender_id, sender_username, kind, body, media_url, media_mime, sticker_pack_id, sticker_id, reply_to:{...}, forwarded, reactions:[{emoji,count,users,effect_id}], cosmetic_id, send_effect_id, client_msg_id, server_sequence, edited_at, deleted, delivery:{user_id: sent|delivered|read}, created_at}`

### Link previews (SSRF-guarded)

- `GET /preview?url=` → `{url, title, description, image, site_name, cached}`. SSRF guard: http(s) only, no credentials in URL, hostname must resolve to a **public** IP (re-checked on every redirect hop), 3 redirects max, 5s timeout, 1MB cap, HTML only. 24h in-memory cache (1000 entries). 400 for blocked URLs (loopback/private/link-local/non-http). 10/min per user.

## Cosmetic engine (visuals only — zero functional advantage)

- `GET /catalog?category&rarity&theme&set_id&q&limit&offset` → items with `owned` flag. Only **live** items are shown, except items you already own (still visible/usable after retirement).
- `GET /catalog/{id}` → detail + `entitlement`, `favorite`, `status`, `publish_at`. Non-live, unowned items → 404.
- `GET /inventory` → owned items with `source`, `granted_at`
- `GET /collection` → `{total, owned_count, items:[{...owned,favorite}], sets:[...], favorites}`
- `POST /favorites/{id}` / `DELETE /favorites/{id}`
- `GET /loadouts` / `POST /loadouts` `{name?, copy_from?}` / `POST /loadouts/{id}/activate` / `PUT /loadouts/{id}` `{slot, cosmetic_id|null}` / `DELETE /loadouts/{id}`. Slots (13): `AVATAR FRAME BACKGROUND BANNER NAMEPLATE STATUS_DECO BADGE PROFILE_EFFECT WALLPAPER BUBBLE SEND_EFFECT REACTION_EFFECT TYPING_EFFECT`. PUT validates slot↔category mapping **and ownership** server-side (403 if unowned).
- `GET /conversations/{id}/theme` / `PUT /conversations/{id}/theme` `{scope: personal|shared, wallpaper_id?, bubble_id?, send_effect_id?, reaction_effect_id?, typing_effect_id?}` / `DELETE .../theme`. Ownership enforced.

### Publishing lifecycle (admin)

Cosmetics have a `status`: `draft → review → scheduled → live → retired`
(re-release via `retired → draft`). New admin-created items start as **draft**.
`scheduled` items flip to `live` lazily on read once `publish_at` passes.
Shop and catalog only show `live` items. Retiring never removes an owner's
copy.

- `POST /admin/cosmetics/{id}/transition` `{to_status, publish_at?}` → `{ok, status}`. `publish_at` required for `scheduled`.

## Economy (server-authoritative)

- `GET /wallet` → `{balances: {shards, gems, event_tokens}}`
- `GET /wallet/transactions?limit`
- `GET /shop` → `{featured, new, by_rarity:{...}, bundles, currency_packs, free}`
- `POST /shop/purchase` `{item_type: cosmetic|bundle|currency_pack, item_id, idempotency_key, recipient_id?}` → `{ok, purchase_id, status, balances, duplicate?}`. Flow: created → pending → verified → granted (dev provider verifies instantly; swap for real billing in prod). `recipient_id` = gift-purchase. Free items (`acquisition == "free"`) are claimed through this endpoint at zero cost.
- `POST /gifts` `{cosmetic_id, recipient_id, message?}` → transfers an **owned, transferable** cosmetic. `GET /gifts` → history.
- `GET /rewards/daily` → `{today, claimed, next_day, ladder:[{day,shards,gems,cosmetic_id}]}`
- `POST /rewards/daily/claim` → `{ok, day_number, granted, balances, leveled_up}`. Idempotent per local day; streak-aware (30-day ladder).

## Engagement

- `GET /streaks` / `GET /streaks/{user_id}` → `{count, longest, last_active_day, message_count, milestones}`
- `GET /notifications?unread_only&limit` / `POST /notifications/read` `{ids:[...]|"all"}`
- `GET /events` / `GET /events/{id}` → `{is_live, challenges:[{id,name,rule,reward,progress,target,completed}], shop_items, points, tiers_claimed, progression_track}`. Event points now accrue **server-side** while the event is live (bumped by the same achievements/challenge events — messaging, friendships, purchases). No client can grant points.
- `POST /events/{id}/tiers/claim` `{tier_index}` → `{ok, tier, granted, balances}`. Tier grants are idempotent (already-claimed → 400); unmet thresholds → 400.
- `GET /achievements` → `{id,name,description,target,progress,unlocked,unlocked_at,reward}`
- `GET /profile/progress` → `{level, xp, xp_for_next, collection:{owned,total,percent}, legendary_count, titles, stats}`
- `GET /flags` → `{key: bool}` (rollout-aware)

## Admin (`is_admin` only)

- `POST /admin/cosmetics` (defaults `status: "draft"`), `PATCH /admin/cosmetics/{id}` (asset change bumps `version`; ownership never removed), `POST /admin/cosmetics/{id}/transition` (publishing lifecycle; see above)
- `POST /admin/events`, `PATCH /admin/events/{id}`
- `GET|PUT /admin/flags`, `PUT /admin/flags/{key}`
- `GET /admin/economy/overview`, `POST /admin/economy/grant` (audited)
- `POST /admin/purchases/{id}/refund` → revokes entitlements, reconciles wallet
- `GET /admin/reconciliation` → `{ok, issues}` (wallet == Σ ledger)
- `GET /admin/users?q=`, `POST /admin/users/{id}/suspend|unsuspend`, `GET /admin/users/{id}/economy` (ownership/purchases only — never message content)
- `GET /admin/audit?action=&limit=`, `GET /admin/reports`, `POST /admin/reports/{id}` `{status}`

## Realtime (`/ws?token=`)

Server→client JSON with `type`: `message.new` `{message, style}`, `message.edit` `{message}`, `message.delete` `{conversation_id, message_id}`, `message.read` `{conversation_id, user_id}`, `reaction.added|removed` `{message_id, emoji, user_id}`, `typing.started|stopped` `{conversation_id, user_id}`, `presence.changed` `{user_id, online}`, `request.new` `{request, from_user}`, `request.accepted` `{request_id, conversation_id}`, `request.rejected` `{request_id}`. Client→server: any text = keepalive ping.

## Honest placeholders (do not present as production)

- Payments: dev provider only — instant verify, no real billing.
- E2EE: not implemented — transport is TLS to the server; E2EE is a documented upgrade path. Message `ciphertext` column is reserved for it.
- Push: in-app notifications only.
- Voice/video calls & voice messages: out of scope per spec.
