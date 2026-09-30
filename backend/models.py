"""STIP backend — data model.

Covers the spec's database section (72) plus the cosmetic/identity layer:
users, devices, conversations, messages, receipts, cosmetics catalog,
sets, entitlements, loadouts, chat themes, wallet ledger, purchases,
gifts, daily rewards, streaks, achievements, events, notifications,
feature flags, audit logs, blocks, reports, settings, drafts.

Timestamps: naive UTC everywhere (SQLite returns naive datetimes).
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from db import Base


def _now():
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


# ------------------------------------------------------------------ identity

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String(32), unique=True, nullable=False)  # stored lowercase
    display_name = Column(String(64), nullable=False)
    email = Column(String(255), unique=True, nullable=True)
    phone = Column(String(32), unique=True, nullable=True)
    password_hash = Column(String(255), nullable=False)
    is_admin = Column(Boolean, default=False, nullable=False)
    is_suspended = Column(Boolean, default=False, nullable=False)
    failed_logins = Column(Integer, default=0, nullable=False)
    locked_until = Column(DateTime(timezone=True), nullable=True)
    last_seen = Column(DateTime(timezone=True), nullable=True)
    # local day for daily rewards / streak grace (minutes offset from UTC)
    utc_offset_minutes = Column(Integer, default=0, nullable=False)
    # progression
    xp = Column(Integer, default=0, nullable=False)
    level = Column(Integer, default=1, nullable=False)
    username_changed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)
    # v3 signup state machine: verified when the signup OTP step completed
    # (legacy accounts are backfilled verified).
    identifier_verified = Column(Boolean, default=False, nullable=False)


Index("ix_users_username", User.username)


class Device(Base):
    __tablename__ = "devices"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    device_name = Column(String(128), default="unknown")
    token_jti = Column(String(64), unique=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)
    revoked = Column(Boolean, default=False, nullable=False)
    last_active = Column(DateTime(timezone=True), default=_now, nullable=False)
    # v3 device trust: platform label (ios|android|web|desktop), trusted once the
    # identity was verified on it (v3 signup or OTP re-verification).
    platform = Column(String(64), nullable=True)
    trusted = Column(Boolean, default=False, nullable=False)
    verified_at = Column(DateTime(timezone=True), nullable=True)


class OtpCode(Base):
    __tablename__ = "otp_codes"

    id = Column(Integer, primary_key=True)
    channel = Column(String(16), nullable=False)  # "phone" | "email"
    address = Column(String(255), nullable=False)
    code = Column(String(8), nullable=False)
    purpose = Column(String(32), default="signup")
    expires_at = Column(DateTime(timezone=True), nullable=False)
    consumed = Column(Boolean, default=False, nullable=False)


# ----------------------------------------------------------------- messaging

class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True)
    is_group = Column(Boolean, default=False, nullable=False)
    title = Column(String(128), nullable=True)
    image = Column(String(512), nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=_now, nullable=False)
    # server-side message counter; messages take server_sequence = seq+1
    seq = Column(Integer, default=0, nullable=False)


class ConversationMember(Base):
    __tablename__ = "conversation_members"

    id = Column(Integer, primary_key=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(16), default="member", nullable=False)  # admin | member
    joined_at = Column(DateTime(timezone=True), default=_now, nullable=False)
    # message-request shadow membership: recipient can't see the conversation until accept
    hidden = Column(Boolean, default=False, nullable=False)

    __table_args__ = (
        UniqueConstraint("conversation_id", "user_id", name="uq_member"),
        Index("ix_members_user", "user_id"),
    )


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    sender_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    # text | image | video | sticker | gif | file — no voice, no calls (spec 117-119)
    kind = Column(String(16), default="text", nullable=False)
    body = Column(Text, nullable=True)
    media_path = Column(String(512), nullable=True)
    media_mime = Column(String(128), nullable=True)
    media_size = Column(Integer, nullable=True)
    sticker_pack_id = Column(String(64), nullable=True)
    sticker_id = Column(String(64), nullable=True)
    reply_to_id = Column(Integer, ForeignKey("messages.id"), nullable=True)
    forwarded = Column(Boolean, default=False, nullable=False)
    # minimal cosmetic metadata — visual assets resolve client-side from catalog
    cosmetic_id = Column(String(64), nullable=True)  # bubble cosmetic at send time
    send_effect_id = Column(String(64), nullable=True)
    edited_at = Column(DateTime(timezone=True), nullable=True)
    deleted = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)
    # server-defined ordering (spec 244)
    server_sequence = Column(Integer, nullable=True)
    # v3: client-supplied idempotency id (uuid) — dedupe key (conversation_id, sender_id, client_msg_id)
    client_msg_id = Column(String(64), nullable=True)
    # v3: hidden messages belong to a pending message request; the recipient
    # can't see them until they accept.
    hidden = Column(Boolean, default=False, nullable=False)
    # reserved for future end-to-end encryption (ADR-003): opaque ciphertext
    # envelope; unused while the MVP ships without E2EE.
    ciphertext = Column(Text, nullable=True)


Index("ix_messages_conv_created", Message.conversation_id, Message.created_at)
# idempotent-send dedupe key (NULLs are distinct in SQLite, so sends without
# a client_msg_id are unaffected)
Index("uq_msg_client_id", Message.conversation_id, Message.sender_id, Message.client_msg_id,
      unique=True)


class MessageStatus(Base):
    """Per-recipient delivery state (spec 49): server_accepted → delivered → read."""

    __tablename__ = "message_status"

    id = Column(Integer, primary_key=True)
    message_id = Column(Integer, ForeignKey("messages.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)  # recipient
    state = Column(String(16), default="server_accepted", nullable=False)  # server_accepted|delivered|read
    updated_at = Column(DateTime(timezone=True), default=_now, nullable=False)

    __table_args__ = (UniqueConstraint("message_id", "user_id", name="uq_msgstatus"),)


class Reaction(Base):
    __tablename__ = "reactions"

    id = Column(Integer, primary_key=True)
    message_id = Column(Integer, ForeignKey("messages.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    emoji = Column(String(32), nullable=False)
    effect_id = Column(String(64), nullable=True)  # cosmetic reaction effect
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)

    __table_args__ = (UniqueConstraint("message_id", "user_id", "emoji", name="uq_reaction"),)


class PinnedMessage(Base):
    __tablename__ = "pinned_messages"

    id = Column(Integer, primary_key=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    message_id = Column(Integer, ForeignKey("messages.id", ondelete="CASCADE"), nullable=False, unique=True)
    pinned_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)


class ReadReceipt(Base):
    """Conversation-level cursor for unread counts."""

    __tablename__ = "read_receipts"

    id = Column(Integer, primary_key=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    last_read_message_id = Column(Integer, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=_now, nullable=False)

    __table_args__ = (UniqueConstraint("conversation_id", "user_id", name="uq_read"),)


class ChatDraft(Base):
    __tablename__ = "chat_drafts"

    id = Column(Integer, primary_key=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    content = Column(Text, default="")
    updated_at = Column(DateTime(timezone=True), default=_now, nullable=False)

    __table_args__ = (UniqueConstraint("conversation_id", "user_id", name="uq_draft"),)


# ----------------------------------------------------------------- cosmetics

RARITIES = ["common", "uncommon", "rare", "epic", "legendary", "mythic"]

# Category taxonomy (spec 18). New types are rows, never code.
COSMETIC_CATEGORIES = [
    "profile.avatar",
    "profile.frame",
    "profile.banner",
    "profile.nameplate",
    "profile.badge",
    "profile.background",
    "profile.effect",
    "chat.wallpaper",
    "chat.bubble",
    "chat.typing",
    "chat.reaction",
    "chat.send_effect",
    "expression.sticker_pack",
    "expression.sticker",
    "expression.emoji_theme",
    "expression.gif_collection",
    "event.seasonal",
    "event.limited",
]

# Loadout slots (spec 133): one cosmetic per slot in a loadout.
LOADOUT_SLOTS = [
    "AVATAR",
    "FRAME",
    "BACKGROUND",
    "BANNER",
    "NAMEPLATE",
    "STATUS_DECO",
    "BADGE",
    "PROFILE_EFFECT",
    "WALLPAPER",
    "BUBBLE",
    "SEND_EFFECT",
    "REACTION_EFFECT",
    "TYPING_EFFECT",
]

# Which categories can fill which loadout slot
SLOT_CATEGORY_MAP = {
    "AVATAR": ["profile.avatar"],
    "FRAME": ["profile.frame"],
    "BACKGROUND": ["profile.background"],
    "BANNER": ["profile.banner"],
    "NAMEPLATE": ["profile.nameplate"],
    "STATUS_DECO": ["profile.badge", "profile.effect"],
    "BADGE": ["profile.badge"],
    "PROFILE_EFFECT": ["profile.effect"],
    "WALLPAPER": ["chat.wallpaper"],
    "BUBBLE": ["chat.bubble"],
    "SEND_EFFECT": ["chat.send_effect"],
    "REACTION_EFFECT": ["chat.reaction"],
    "TYPING_EFFECT": ["chat.typing"],
}


class Cosmetic(Base):
    """Catalog item (spec 67-70, 187). Asset JSON is interpreted by the client;
    the server never decides visual truth beyond metadata."""

    __tablename__ = "cosmetics"

    id = Column(String(64), primary_key=True)  # e.g. "bubble_legendary_014"
    category = Column(String(32), nullable=False, index=True)
    name = Column(String(128), nullable=False)
    description = Column(Text, default="")  # lore / storytelling
    rarity = Column(String(16), default="common", nullable=False, index=True)
    version = Column(Integer, default=1, nullable=False)
    # asset: {gradient, emoji, animation, colors, ...} — client renders.
    asset = Column(JSON, default=dict, nullable=False)
    asset_hash = Column(String(64), default="")
    performance_class = Column(String(2), default="P0", nullable=False)  # P0..P3
    fallback_id = Column(String(64), nullable=True)  # static fallback for low-end
    theme_tags = Column(JSON, default=list, nullable=False)  # space, winter, ...
    # availability & acquisition
    availability = Column(String(16), default="permanent")  # permanent|seasonal|event|limited|retired
    acquisition = Column(String(16), default="free")  # free|purchase|event|achievement|reward|promo
    price_shards = Column(Integer, default=0, nullable=False)
    price_gems = Column(Integer, default=0, nullable=False)
    event_id = Column(String(64), nullable=True)
    release_date = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    max_supply = Column(Integer, nullable=True)
    obtainable = Column(Boolean, default=True, nullable=False)
    transferable = Column(Boolean, default=False, nullable=False)  # gifting eligibility
    # sets & evolution
    set_id = Column(String(64), nullable=True, index=True)
    evolves_from = Column(String(64), nullable=True)
    evolves_to = Column(String(64), nullable=True)
    # admin / shop
    enabled = Column(Boolean, default=True, nullable=False)
    featured = Column(Boolean, default=False, nullable=False)
    # v3 publishing lifecycle: draft → review → scheduled → live → retired
    # (retired is terminal-ish; re-release goes retired → draft).
    status = Column(String(16), default="live", nullable=False)
    publish_at = Column(DateTime(timezone=True), nullable=True)  # scheduled → live at this time
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)


class CosmeticSet(Base):
    __tablename__ = "cosmetic_sets"

    id = Column(String(64), primary_key=True)  # e.g. "set_galactic_eclipse"
    name = Column(String(128), nullable=False)
    description = Column(Text, default="")
    theme = Column(String(64), default="")
    # completion reward: {cosmetic_id?, shards?, gems?}
    completion_reward = Column(JSON, default=dict, nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)


class Entitlement(Base):
    """Why the user owns it (spec 23-24). Server-authoritative ownership."""

    __tablename__ = "entitlements"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    cosmetic_id = Column(String(64), ForeignKey("cosmetics.id"), nullable=False)
    source = Column(String(16), default="free", nullable=False)  # free|purchase|event|achievement|reward|gift|promo|admin|starter
    purchase_id = Column(Integer, ForeignKey("purchases.id"), nullable=True)
    event_id = Column(String(64), nullable=True)
    reward_id = Column(String(64), nullable=True)
    gift_id = Column(Integer, nullable=True)
    granted_at = Column(DateTime(timezone=True), default=_now, nullable=False)
    status = Column(String(16), default="active", nullable=False)  # active|revoked

    __table_args__ = (UniqueConstraint("user_id", "cosmetic_id", name="uq_entitlement"),)


class Loadout(Base):
    """Named loadout preset (spec 112, 133)."""

    __tablename__ = "loadouts"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(64), nullable=False)
    is_active = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)


class LoadoutItem(Base):
    __tablename__ = "loadout_items"

    id = Column(Integer, primary_key=True)
    loadout_id = Column(Integer, ForeignKey("loadouts.id", ondelete="CASCADE"), nullable=False)
    slot = Column(String(32), nullable=False)
    cosmetic_id = Column(String(64), ForeignKey("cosmetics.id"), nullable=True)

    __table_args__ = (UniqueConstraint("loadout_id", "slot", name="uq_loadout_slot"),)


class ChatTheme(Base):
    """Per-conversation cosmetic overrides (spec 134): personal vs shared scope."""

    __tablename__ = "chat_themes"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    scope = Column(String(16), default="personal", nullable=False)  # personal | shared
    wallpaper_id = Column(String(64), nullable=True)
    bubble_id = Column(String(64), nullable=True)
    send_effect_id = Column(String(64), nullable=True)
    reaction_effect_id = Column(String(64), nullable=True)
    typing_effect_id = Column(String(64), nullable=True)
    updated_at = Column(DateTime(timezone=True), default=_now, nullable=False)

    __table_args__ = (UniqueConstraint("user_id", "conversation_id", name="uq_chat_theme"),)


class Favorite(Base):
    __tablename__ = "favorites"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    cosmetic_id = Column(String(64), ForeignKey("cosmetics.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)

    __table_args__ = (UniqueConstraint("user_id", "cosmetic_id", name="uq_fav"),)


# ------------------------------------------------------------------- economy

CURRENCIES = ["shards", "gems", "event_tokens"]


class Wallet(Base):
    __tablename__ = "wallets"

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    currency = Column(String(16), primary_key=True)  # shards | gems | event_tokens
    balance = Column(Integer, default=0, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=_now, nullable=False)


class WalletTransaction(Base):
    """Append-only ledger (spec 73). Every currency change is a row."""

    __tablename__ = "wallet_transactions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    currency = Column(String(16), nullable=False)
    amount_delta = Column(Integer, nullable=False)
    balance_after = Column(Integer, nullable=False)
    reason = Column(String(64), nullable=False)
    source = Column(String(32), nullable=False)  # purchase|reward|daily|streak|achievement|event|gift|admin|refund|starter
    reference_id = Column(String(128), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)


Index("ix_ledger_user_created", WalletTransaction.user_id, WalletTransaction.created_at)


class Purchase(Base):
    __tablename__ = "purchases"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    item_type = Column(String(16), nullable=False)  # cosmetic | bundle | currency_pack
    item_id = Column(String(64), nullable=False)
    price_currency = Column(String(16), default="gems", nullable=False)
    price_amount = Column(Integer, nullable=False)
    status = Column(String(16), default="created", nullable=False)  # created|pending|verified|granted|failed|refunded|revoked
    idempotency_key = Column(String(64), unique=True, nullable=False)
    provider = Column(String(16), default="dev", nullable=False)  # dev | apple | google (honest: dev mode)
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)
    verified_at = Column(DateTime(timezone=True), nullable=True)
    granted_at = Column(DateTime(timezone=True), nullable=True)
    refunded_at = Column(DateTime(timezone=True), nullable=True)


class Bundle(Base):
    __tablename__ = "bundles"

    id = Column(String(64), primary_key=True)
    name = Column(String(128), nullable=False)
    description = Column(Text, default="")
    cosmetic_ids = Column(JSON, default=list, nullable=False)
    price_shards = Column(Integer, default=0, nullable=False)
    price_gems = Column(Integer, default=0, nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)


class CurrencyPack(Base):
    """Dev-mode gems pack. Real-money billing is an honest placeholder —
    grants go through the same verified purchase pipeline."""

    __tablename__ = "currency_packs"

    id = Column(String(64), primary_key=True)
    name = Column(String(128), nullable=False)
    gems = Column(Integer, nullable=False)
    price_label = Column(String(64), default="")  # display only
    enabled = Column(Boolean, default=True, nullable=False)


class GiftTransaction(Base):
    __tablename__ = "gift_transactions"

    id = Column(Integer, primary_key=True)
    sender_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    recipient_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    cosmetic_id = Column(String(64), ForeignKey("cosmetics.id"), nullable=False)
    status = Column(String(16), default="pending", nullable=False)  # pending|completed|cancelled
    message = Column(String(256), default="")
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)


# --------------------------------------------------------------- engagement

class DailyReward(Base):
    """30-day ladder definition (seeded)."""

    __tablename__ = "daily_rewards"

    day = Column(Integer, primary_key=True)  # 1..30
    shards = Column(Integer, default=0, nullable=False)
    gems = Column(Integer, default=0, nullable=False)
    cosmetic_id = Column(String(64), nullable=True)


class DailyClaim(Base):
    __tablename__ = "daily_claims"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    claim_date = Column(String(10), nullable=False)  # user's local YYYY-MM-DD
    day_number = Column(Integer, nullable=False)  # streak day on ladder
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)

    __table_args__ = (UniqueConstraint("user_id", "claim_date", name="uq_daily_claim"),)


class Streak(Base):
    """Friendship streak per ordered user pair, server-day based (spec 29, 233)."""

    __tablename__ = "streaks"

    id = Column(Integer, primary_key=True)
    user_a = Column(Integer, ForeignKey("users.id"), nullable=False)  # lower id
    user_b = Column(Integer, ForeignKey("users.id"), nullable=False)
    count = Column(Integer, default=0, nullable=False)
    last_active_day = Column(String(10), nullable=True)  # UTC YYYY-MM-DD
    longest = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)

    __table_args__ = (UniqueConstraint("user_a", "user_b", name="uq_streak"),)


class StreakDay(Base):
    """Per-day participation for honest two-sided streaks: a day only counts
    when both sides sent at least one message (spec 29)."""

    __tablename__ = "streak_days"

    id = Column(Integer, primary_key=True)
    user_a = Column(Integer, nullable=False)
    user_b = Column(Integer, nullable=False)
    day = Column(String(10), nullable=False)  # UTC YYYY-MM-DD
    a_sent = Column(Boolean, default=False, nullable=False)
    b_sent = Column(Boolean, default=False, nullable=False)

    __table_args__ = (UniqueConstraint("user_a", "user_b", "day", name="uq_streakday"),)


class FriendshipStat(Base):
    """First message, total count — drives friendship milestones (spec 30)."""

    __tablename__ = "friendship_stats"

    id = Column(Integer, primary_key=True)
    user_a = Column(Integer, nullable=False)
    user_b = Column(Integer, nullable=False)
    first_message_at = Column(DateTime(timezone=True), nullable=True)
    message_count = Column(Integer, default=0, nullable=False)
    milestones = Column(JSON, default=list, nullable=False)  # unlocked milestone keys

    __table_args__ = (UniqueConstraint("user_a", "user_b", name="uq_fstat"),)


class Achievement(Base):
    __tablename__ = "achievements"

    id = Column(String(64), primary_key=True)
    name = Column(String(128), nullable=False)
    description = Column(Text, default="")
    # rule: {"event": "message_sent"|"cosmetic_equipped"|"cosmetic_owned"|"streak_days"|"daily_claimed"|"event_completed", "count": N}
    rule = Column(JSON, default=dict, nullable=False)
    reward_shards = Column(Integer, default=0, nullable=False)
    reward_gems = Column(Integer, default=0, nullable=False)
    reward_cosmetic_id = Column(String(64), nullable=True)
    enabled = Column(Boolean, default=True, nullable=False)


class UserAchievement(Base):
    __tablename__ = "user_achievements"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    achievement_id = Column(String(64), ForeignKey("achievements.id"), nullable=False)
    progress = Column(Integer, default=0, nullable=False)
    unlocked_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (UniqueConstraint("user_id", "achievement_id", name="uq_ach"),)


class UserStat(Base):
    """Counters feeding achievements & XP (spec 129-130)."""

    __tablename__ = "user_stats"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    key = Column(String(64), nullable=False)
    value = Column(Integer, default=0, nullable=False)

    __table_args__ = (UniqueConstraint("user_id", "key", name="uq_stat"),)


class Event(Base):
    """Config-driven event (spec 32-33)."""

    __tablename__ = "events"

    id = Column(String(64), primary_key=True)
    name = Column(String(128), nullable=False)
    description = Column(Text, default="")
    theme = Column(String(64), default="")
    status = Column(String(16), default="draft", nullable=False)  # draft|scheduled|live|paused|ended|archived
    start_at = Column(DateTime(timezone=True), nullable=True)
    end_at = Column(DateTime(timezone=True), nullable=True)
    banner_asset = Column(JSON, default=dict, nullable=False)
    # challenges: [{id, name, rule{event,count}, reward{cosmetic_id,shards,gems}}]
    challenges = Column(JSON, default=list, nullable=False)
    shop_items = Column(JSON, default=list, nullable=False)  # [{cosmetic_id, price_gems?, price_shards?}]
    currency = Column(String(16), default="event_tokens", nullable=False)
    progression_track = Column(JSON, default=list, nullable=False)  # [{points, reward{...}}]
    feature_flags = Column(JSON, default=dict, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)


class EventProgress(Base):
    __tablename__ = "event_progress"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    event_id = Column(String(64), ForeignKey("events.id"), nullable=False)
    challenge_id = Column(String(64), nullable=False)
    progress = Column(Integer, default=0, nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    reward_claimed = Column(Boolean, default=False, nullable=False)

    __table_args__ = (UniqueConstraint("user_id", "event_id", "challenge_id", name="uq_evt"),)


class EventPoints(Base):
    __tablename__ = "event_points"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    event_id = Column(String(64), ForeignKey("events.id"), nullable=False)
    points = Column(Integer, default=0, nullable=False)
    tiers_claimed = Column(JSON, default=list, nullable=False)

    __table_args__ = (UniqueConstraint("user_id", "event_id", name="uq_evtpts"),)


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    type = Column(String(32), nullable=False)  # message|reaction|streak|reward|event|purchase|system|security
    title = Column(String(128), nullable=False)
    body = Column(Text, default="")
    data = Column(JSON, default=dict, nullable=False)
    read = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)


# ----------------------------------------------------------------- platform

class FeatureFlag(Base):
    __tablename__ = "feature_flags"

    key = Column(String(64), primary_key=True)
    description = Column(String(256), default="")
    enabled = Column(Boolean, default=False, nullable=False)
    rollout_percent = Column(Integer, default=100, nullable=False)  # 0..100


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True)
    actor_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    action = Column(String(64), nullable=False, index=True)  # login|purchase|reward_grant|admin_action|...
    target_type = Column(String(32), nullable=True)
    target_id = Column(String(128), nullable=True)
    details = Column(JSON, default=dict, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)


class Report(Base):
    __tablename__ = "reports"

    id = Column(Integer, primary_key=True)
    reporter_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    target_type = Column(String(16), nullable=False)  # user|message|cosmetic
    target_id = Column(String(64), nullable=False)
    reason = Column(Text, nullable=False)
    status = Column(String(16), default="open", nullable=False)
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)


class Block(Base):
    """A blocks B: no messages, no profile/presence visibility, no requests."""

    __tablename__ = "blocks"

    id = Column(Integer, primary_key=True)
    blocker_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    blocked_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)

    __table_args__ = (UniqueConstraint("blocker_id", "blocked_id", name="uq_block"),)


class UserSetting(Base):
    __tablename__ = "user_settings"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    key = Column(String(64), nullable=False)
    value = Column(JSON, nullable=False)

    __table_args__ = (UniqueConstraint("user_id", "key", name="uq_setting"),)


# ----------------------------------------------------------------- v3 auth

class SignupSession(Base):
    """In-progress v3 signup: start → verify (OTP) → username → complete.

    The shell user row carries a pending_<hex> username and password_hash "!"
    so it can never log in; identifier_verified flips at OTP verification.
    Sessions expire after 24h.
    """

    __tablename__ = "signup_sessions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token = Column(String(64), unique=True, nullable=False)  # bearer for the remaining steps
    channel = Column(String(16), nullable=False)  # phone | email
    address = Column(String(255), nullable=False)
    verified = Column(Boolean, default=False, nullable=False)
    username_reserved = Column(Boolean, default=False, nullable=False)
    completed = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (UniqueConstraint("user_id", name="uq_signup_session_user"),)


class UsernameTombstone(Base):
    """Released usernames on a 30-day hold: nobody can claim them until the
    hold expires (ADR-002)."""

    __tablename__ = "username_tombstones"

    id = Column(Integer, primary_key=True)
    normalized = Column(String(20), unique=True, nullable=False)  # lowercase NFKC username
    released_at = Column(DateTime(timezone=True), default=_now, nullable=False)


# -------------------------------------------------------- v3 message requests

class MessageRequest(Base):
    """First-contact request: a stranger's opener waits in a shadow
    conversation until the recipient accepts or rejects it."""

    __tablename__ = "message_requests"

    id = Column(Integer, primary_key=True)
    from_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    to_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    message_id = Column(Integer, ForeignKey("messages.id", ondelete="CASCADE"), nullable=False)
    status = Column(String(16), default="pending", nullable=False)  # pending|accepted|rejected
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)
    decided_at = Column(DateTime(timezone=True), nullable=True)


# ------------------------------------------------------------- v3 referrals

class ReferralCode(Base):
    __tablename__ = "referral_codes"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    code = Column(String(32), unique=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_now, nullable=False)

    __table_args__ = (UniqueConstraint("user_id", name="uq_referral_user"),)


class ReferralUse(Base):
    """One row per referee — the UNIQUE(referee_id) is the double-credit guard."""

    __tablename__ = "referral_uses"

    id = Column(Integer, primary_key=True)
    referrer_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    referee_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    code = Column(String(32), nullable=False)
    credited_at = Column(DateTime(timezone=True), default=_now, nullable=False)

    __table_args__ = (UniqueConstraint("referee_id", name="uq_referral_referee"),)
