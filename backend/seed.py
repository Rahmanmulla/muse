"""STIP backend — seed data: catalog, sets, daily ladder, achievements, events.

Every cosmetic is a row: the client renders from `asset` metadata.
Starter kit items are granted free at signup (spec 103).
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import Session

import models as m
from core import utcnow

STARTER_KIT = [
    "avatar_starter", "frame_starter", "wp_starter", "bubble_starter",
    "banner_starter", "stickers_starter",
    # v3: 2D avatar identity starters (common, free)
    "avatar_2d_sage", "avatar_2d_comet", "avatar_2d_ink", "avatar_2d_bloom",
]

SETS = [
    {
        "id": "set_galactic_eclipse",
        "name": "Galactic Eclipse",
        "description": "When the sun and moon share one sky. Collect all seven to unlock the Eclipse Aura.",
        "theme": "space",
        "completion_reward": {"cosmetic_id": "effect_eclipse_aura", "shards": 250},
    },
    {
        "id": "set_winter_solstice",
        "name": "Winter Solstice",
        "description": "The longest night, rendered beautifully.",
        "theme": "winter",
        "completion_reward": {"cosmetic_id": "frame_solstice_crown", "shards": 150},
    },
]

# (id, category, name, rarity, perf, theme_tags, acquisition, price_shards, price_gems,
#  set_id, availability, emoji, gradient, animation, lore)
C = [
    # ---- starter kit (free) ----
    ("avatar_starter", "profile.avatar", "Starter Orb", "common", "P0", ["minimal"], "free", 0, 0, None, "permanent",
     "🫧", ["#6b7cff", "#9d6bff"], "float", "Where every STIP journey begins."),
    ("frame_starter", "profile.frame", "Starter Ring", "common", "P0", ["minimal"], "free", 0, 0, None, "permanent",
     "⭕", ["#8a93a6", "#5b6272"], "none", "Simple. Clean. Yours."),
    ("wp_starter", "chat.wallpaper", "Mist", "common", "P0", ["minimal"], "free", 0, 0, None, "permanent",
     "🌫️", ["#1a1d29", "#232838"], "none", "A calm backdrop for real conversation."),
    ("bubble_starter", "chat.bubble", "Classic", "common", "P0", ["minimal"], "free", 0, 0, None, "permanent",
     "💬", ["#2f6bff", "#2f6bff"], "none", "The original. It just works."),
    ("banner_starter", "profile.banner", "Dusk Line", "common", "P0", ["minimal"], "free", 0, 0, None, "permanent",
     "🌆", ["#2b2f4a", "#4a2b5a"], "none", "A quiet gradient to sign your profile."),
    ("stickers_starter", "expression.sticker_pack", "Daily Moods", "common", "P0", ["minimal"], "free", 0, 0, None, "permanent",
     "😊", ["#ffd166", "#ff8c42"], "none", "Twelve moods for twelve kinds of days."),
    # ---- v3: 2D avatar identity starters (common, free) ----
    ("avatar_2d_sage", "profile.avatar", "Sage Circle", "common", "P0", ["minimal", "2d"], "free", 0, 0, None, "permanent",
     "🧙", ["#7fd4a8", "#3f8f6f"], "blink", "A calm little sage, drawn in two dimensions."),
    ("avatar_2d_comet", "profile.avatar", "Comet Cub", "common", "P0", ["minimal", "2d"], "free", 0, 0, None, "permanent",
     "🐻", ["#ffd166", "#ff8c42"], "float", "A round cub with a starry tail."),
    ("avatar_2d_ink", "profile.avatar", "Ink Sprite", "common", "P0", ["minimal", "2d"], "free", 0, 0, None, "permanent",
     "🦑", ["#6b7cff", "#2f3a6b"], "swim", "Doodled in the margins of your chats."),
    ("avatar_2d_bloom", "profile.avatar", "Bloom Bot", "common", "P0", ["minimal", "2d"], "free", 0, 0, None, "permanent",
     "🌸", ["#ff9ecb", "#c86bff"], "sway", "A friendly bot that only speaks in petals."),
    # ---- avatars ----
    ("avatar_2d_fable", "profile.avatar", "Fable Fox", "uncommon", "P1", ["fantasy", "anime"], "free", 0, 0, None, "permanent",
     "🦊", ["#ff9a56", "#ff5e78"], "blink", "A clever little spirit, drawn by hand."),
    ("avatar_neon_fox", "profile.avatar", "Neon Fox", "rare", "P2", ["cyber", "anime"], "purchase", 400, 0, None, "permanent",
     "🦊", ["#00e5ff", "#7b2ff7"], "pulse", "It leaves light trails wherever it goes."),
    ("avatar_cyber_warrior", "profile.avatar", "Cyber Ronin", "epic", "P2", ["cyber", "anime"], "purchase", 0, 120, None, "permanent",
     "🤖", ["#0f2027", "#00e5ff"], "scan", "A blade of light in a city of glass."),
    ("avatar_celestial_dragon", "profile.avatar", "Celestial Dragon", "legendary", "P3", ["fantasy", "space"], "purchase", 0, 400, None, "limited",
     "🐉", ["#7b2ff7", "#f107a3"], "soar", "It remembers every star it has ever burned."),
    ("avatar_void_sovereign", "profile.avatar", "Void Sovereign", "mythic", "P3", ["space", "horror"], "event", 0, 0, None, "event",
     "🕳️", ["#000000", "#4a00e0"], "void", "It does not look back at you. It looks through."),
    ("avatar_solar", "profile.avatar", "Solar Warden", "epic", "P2", ["space", "fantasy"], "purchase", 0, 150, "set_galactic_eclipse", "permanent",
     "☀️", ["#ffb800", "#ff5e00"], "radiate", "Chapter I — Arrival. The light comes first."),
    ("avatar_snow_scout", "profile.avatar", "Snow Scout", "uncommon", "P1", ["winter"], "free", 0, 0, "set_winter_solstice", "seasonal",
     "🐧", ["#a8d8ff", "#ffffff"], "shiver", "First tracks in fresh snow."),
    # ---- frames ----
    ("frame_neon", "profile.frame", "Neon Circuit", "uncommon", "P1", ["cyber"], "purchase", 150, 0, None, "permanent",
     "⚡", ["#00e5ff", "#ff00aa"], "pulse", "Hums softly when you open your profile."),
    ("frame_aurora", "profile.frame", "Aurora Veil", "rare", "P2", ["space", "winter"], "purchase", 350, 0, None, "permanent",
     "🌌", ["#43e97b", "#38f9d7"], "flow", "The sky, folded around your face."),
    ("frame_eclipse", "profile.frame", "Eclipse Frame", "legendary", "P3", ["space"], "purchase", 0, 300, "set_galactic_eclipse", "limited",
     "🌑", ["#141414", "#f7b733"], "corona", "Chapter II — Discovery. The shadow learns your name."),
    ("frame_solstice_crown", "profile.frame", "Solstice Crown", "legendary", "P2", ["winter"], "event", 0, 0, "set_winter_solstice", "event",
     "👑", ["#b8e6ff", "#ffffff"], "sparkle", "Worn only on the longest night."),
    # ---- backgrounds / banners / nameplates ----
    ("bg_aurora", "profile.background", "Aurora Field", "rare", "P2", ["space", "winter"], "purchase", 300, 0, None, "permanent",
     "🌠", ["#0f2027", "#43e97b"], "drift", "Slow light, forever moving."),
    ("bg_nebula", "profile.background", "Nebula Deep", "epic", "P3", ["space"], "purchase", 0, 140, None, "permanent",
     "🌌", ["#2b1055", "#7597de"], "swirl", "A stellar nursery behind your name."),
    ("banner_solar", "profile.banner", "Solar Flare", "uncommon", "P1", ["space"], "purchase", 120, 0, None, "permanent",
     "☀️", ["#ff9a00", "#ff2d00"], "flare", "Warmth, weaponized into style."),
    ("banner_eclipse", "profile.banner", "Black Hole Banner", "legendary", "P3", ["space"], "purchase", 0, 280, "set_galactic_eclipse", "limited",
     "🕳️", ["#000000", "#7b2ff7"], "accrete", "Chapter III — Expansion. Everything falls inward."),
    ("nameplate_neon", "profile.nameplate", "Neon Script", "rare", "P1", ["cyber"], "purchase", 250, 0, None, "permanent",
     "✨", ["#00e5ff", "#ff00aa"], "glow", "Your name, in light."),
    ("nameplate_mythic", "profile.nameplate", "Mythic Sigil", "mythic", "P3", ["fantasy"], "event", 0, 0, None, "event",
     "🔱", ["#ffd700", "#ff5e00"], "sigil", "Fewer than a hundred will ever carry it."),
    ("badge_first_flame", "profile.badge", "First Flame", "common", "P0", ["minimal"], "achievement", 0, 0, None, "permanent",
     "🔥", ["#ff6b35", "#f7931e"], "none", "For the first conversation that mattered."),
    # ---- profile effects ----
    ("effect_fire_aura", "profile.effect", "Ember Aura", "epic", "P2", ["fantasy"], "purchase", 0, 160, None, "permanent",
     "🔥", ["#ff5e00", "#ffb800"], "flicker", "Warmth you can see."),
    ("effect_snowfall", "profile.effect", "Gentle Snowfall", "rare", "P1", ["winter"], "purchase", 300, 0, "set_winter_solstice", "seasonal",
     "❄️", ["#a8d8ff", "#ffffff"], "fall", "Chapter II — Hush. Snow that never melts."),
    ("effect_hologram", "profile.effect", "Hologram Scan", "legendary", "P3", ["cyber", "space"], "purchase", 0, 350, None, "limited",
     "👾", ["#00e5ff", "#7b2ff7"], "scan", "You, rendered in light."),
    ("effect_eclipse_aura", "profile.effect", "Eclipse Aura", "legendary", "P3", ["space"], "event", 0, 0, "set_galactic_eclipse", "event",
     "🌑", ["#141414", "#f7b733"], "corona", "Chapter V — Ascension. Earned by completing the Galactic Eclipse set."),
    # ---- wallpapers ----
    ("wp_aurora", "chat.wallpaper", "Aurora Night", "rare", "P2", ["space", "winter"], "purchase", 280, 0, None, "permanent",
     "🌌", ["#0f2027", "#43e97b"], "drift", "The sky keeps you company."),
    ("wp_snowfall", "chat.wallpaper", "Snowfall", "uncommon", "P1", ["winter"], "purchase", 120, 0, "set_winter_solstice", "seasonal",
     "❄️", ["#1a2a4a", "#a8d8ff"], "fall", "Quiet conversations, white noise."),
    ("wp_cyberpunk", "chat.wallpaper", "Neon District", "epic", "P2", ["cyber"], "purchase", 0, 130, None, "permanent",
     "🌃", ["#ff00aa", "#00e5ff"], "rain", "Rain on neon. Always night, never tired."),
    ("wp_nebula", "chat.wallpaper", "Nebula Drift", "legendary", "P3", ["space"], "purchase", 0, 320, "set_galactic_eclipse", "limited",
     "🌠", ["#2b1055", "#f107a3"], "swirl", "Chapter IV — Eclipse. Where messages go to dream."),
    ("wp_mythic_void", "chat.wallpaper", "Mythic Void", "mythic", "P3", ["space", "horror"], "event", 0, 0, None, "event",
     "🕳️", ["#000000", "#1a0033"], "void", "For conversations that change you."),
    ("wp_winter_2026", "chat.wallpaper", "Winter 2026", "rare", "P1", ["winter"], "event", 0, 0, None, "event",
     "⛄", ["#b8e6ff", "#ffffff"], "fall", "A season, kept forever."),
    # ---- bubbles ----
    ("bubble_glass", "chat.bubble", "Glass", "uncommon", "P1", ["minimal", "luxury"], "purchase", 100, 0, None, "permanent",
     "🫧", ["#ffffff33", "#ffffff11"], "shine", "See-through, but never empty."),
    ("bubble_fire", "chat.bubble", "Ember", "rare", "P2", ["fantasy"], "purchase", 260, 0, None, "permanent",
     "🔥", ["#ff5e00", "#ffb800"], "flicker", "Every word, warm to the touch."),
    ("bubble_electric", "chat.bubble", "Arc", "epic", "P2", ["cyber"], "purchase", 0, 110, None, "permanent",
     "⚡", ["#00e5ff", "#7b2ff7"], "arc", "Messages that crackle."),
    ("bubble_cosmic", "chat.bubble", "Cosmic", "legendary", "P3", ["space"], "purchase", 0, 300, None, "limited",
     "🌌", ["#7b2ff7", "#f107a3"], "swirl", "Your words, orbiting something beautiful."),
    ("bubble_liquid", "chat.bubble", "Liquid Myth", "mythic", "P3", ["ocean", "luxury"], "event", 0, 0, None, "event",
     "💧", ["#00e5ff", "#0066ff"], "flow", "It moves like it remembers being rain."),
    ("bubble_gravity", "chat.bubble", "Gravity", "epic", "P2", ["space"], "purchase", 0, 170, "set_galactic_eclipse", "limited",
     "🪐", ["#2b1055", "#7597de"], "orbit", "Chapter IV — Eclipse. Words with their own pull."),
    ("bubble_frost", "chat.bubble", "Frost", "rare", "P1", ["winter"], "purchase", 240, 0, "set_winter_solstice", "seasonal",
     "🧊", ["#a8d8ff", "#ffffff"], "shimmer", "Crisp as the first cold morning."),
    # ---- typing / reaction / send effects ----
    ("typing_cyber", "chat.typing", "Cyber Dots", "rare", "P1", ["cyber"], "purchase", 150, 0, None, "permanent",
     "⌨️", ["#00e5ff", "#00e5ff"], "blink", "They're typing. In neon."),
    ("typing_stars", "chat.typing", "Starfall Typing", "epic", "P2", ["space"], "purchase", 0, 90, "set_galactic_eclipse", "limited",
     "✨", ["#ffd700", "#7b2ff7"], "fall", "Chapter III — Expansion. Every keystroke, a meteor."),
    ("reaction_lightning", "chat.reaction", "Lightning React", "rare", "P2", ["cyber"], "purchase", 200, 0, None, "permanent",
     "⚡", ["#ffd700", "#00e5ff"], "strike", "Reactions that arrive before you do."),
    ("reaction_hearts", "chat.reaction", "Heartburst", "epic", "P2", ["fantasy"], "purchase", 0, 100, None, "permanent",
     "💖", ["#ff5e78", "#ff9a56"], "burst", "For when one heart isn't enough."),
    ("reaction_stellar", "chat.reaction", "Stellar React", "legendary", "P3", ["space"], "event", 0, 0, "set_galactic_eclipse", "event",
     "🌟", ["#ffd700", "#f107a3"], "nova", "Chapter V — Ascension. A small supernova of approval."),
    ("send_fire", "chat.send_effect", "Fire Burst", "rare", "P2", ["fantasy"], "purchase", 220, 0, None, "permanent",
     "🔥", ["#ff5e00", "#ffb800"], "burst", "Your message, launched."),
    ("send_lightning", "chat.send_effect", "Lightning Strike", "epic", "P2", ["cyber"], "purchase", 0, 120, None, "permanent",
     "⚡", ["#00e5ff", "#ffd700"], "strike", "Faster than the network. Almost."),
    ("send_cosmic", "chat.send_effect", "Cosmic Trail", "legendary", "P3", ["space"], "purchase", 0, 280, None, "limited",
     "☄️", ["#7b2ff7", "#00e5ff"], "trail", "It leaves stardust on the way out."),
    # ---- stickers / emoji ----
    ("stickers_neon_cats", "expression.sticker_pack", "Neon Cats", "uncommon", "P1", ["cyber", "anime"], "purchase", 90, 0, None, "permanent",
     "🐱", ["#ff00aa", "#00e5ff"], "bounce", "Twenty-four cats. Zero chill."),
    ("stickers_dragon_lords", "expression.sticker_pack", "Dragon Lords", "legendary", "P2", ["fantasy"], "purchase", 0, 220, None, "limited",
     "🐲", ["#7b2ff7", "#f107a3"], "soar", "Ancient. Dramatic. Slightly judgy."),
    ("emoji_galaxy", "expression.emoji_theme", "Galaxy Emoji", "rare", "P1", ["space"], "purchase", 180, 0, "set_galactic_eclipse", "limited",
     "🌌", ["#7b2ff7", "#38f9d7"], "twinkle", "Chapter II — Discovery. Even 😊 looks cosmic."),
]

DAILY_LADDER = [
    # day: (shards, gems, cosmetic_id)
    (1, 50, 0, None), (2, 100, 0, None), (3, 0, 0, "avatar_2d_fable"),
    (4, 120, 0, None), (5, 0, 10, None), (6, 150, 0, None),
    (7, 0, 0, "frame_neon"), (8, 180, 0, None), (9, 200, 0, None),
    (10, 0, 15, None), (11, 220, 0, None), (12, 250, 0, None),
    (13, 0, 0, "stickers_neon_cats"), (14, 0, 0, "avatar_neon_fox"),
    (15, 300, 0, None), (16, 0, 20, None), (17, 320, 0, None),
    (18, 350, 0, None), (19, 0, 0, "wp_aurora"), (20, 400, 0, None),
    (21, 0, 25, None), (22, 450, 0, None), (23, 500, 0, None),
    (24, 0, 0, "bubble_fire"), (25, 550, 0, None), (26, 600, 0, None),
    (27, 0, 40, None), (28, 0, 0, "effect_snowfall"),
    (29, 800, 0, None), (30, 0, 0, "avatar_celestial_dragon"),
]

ACHIEVEMENTS = [
    ("first_connection", "First Connection", "Started your first conversation.", {"event": "friend_added", "count": 1}, 50, 0, None),
    ("first_message", "First Words", "Sent your first message.", {"event": "message_sent", "count": 1}, 25, 0, None),
    ("chatter_100", "Conversationalist", "Sent 100 messages.", {"event": "message_sent", "count": 100}, 150, 10, None),
    ("first_cosmetic", "New Look", "Equipped your first cosmetic.", {"event": "cosmetic_equipped", "count": 1}, 50, 0, None),
    ("collector_10", "Collector", "Own 10 cosmetics.", {"event": "cosmetic_owned", "count": 10}, 100, 5, None),
    ("first_rare", "Rare Find", "Own a rare (or better) cosmetic.", {"event": "cosmetic_owned", "count": 1}, 75, 0, None),
    ("legendary_unlocked", "Legendary", "Own a legendary cosmetic.", {"event": "cosmetic_owned", "count": 1}, 0, 25, None),
    ("streak_7", "Week Strong", "Kept a 7-day friend streak.", {"event": "streak_days", "count": 7}, 100, 0, "badge_first_flame"),
    ("streak_30", "Month of Us", "Kept a 30-day friend streak.", {"event": "streak_days", "count": 30}, 250, 15, None),
    ("streak_100", "Century Bond", "Kept a 100-day friend streak.", {"event": "streak_days", "count": 100}, 500, 50, None),
    ("daily_7", "Rising Regular", "Claimed daily rewards 7 days in a row.", {"event": "daily_claimed", "count": 7}, 120, 5, None),
    ("event_participant", "Showed Up", "Completed an event challenge.", {"event": "event_challenge_completed", "count": 1}, 80, 0, None),
    ("set_completed", "Set Complete", "Completed a cosmetic set.", {"event": "set_completed", "count": 1}, 200, 10, None),
    ("gift_giver", "Generous", "Gifted a cosmetic to a friend.", {"event": "gift_sent", "count": 1}, 60, 0, None),
    ("shopper", "Collector's Eye", "Made your first purchase.", {"event": "purchase_made", "count": 1}, 40, 0, None),
    ("loadout_stylist", "Stylist", "Created 3 loadouts.", {"event": "loadout_created", "count": 3}, 80, 0, None),
]

EVENTS = [
    {
        "id": "cosmic_season",
        "name": "Cosmic Season",
        "description": "Thirty days among the stars. Chat, collect, and earn event rewards.",
        "theme": "space",
        "status": "live",
        "start_at": dt.datetime(2026, 9, 1),
        "end_at": dt.datetime(2026, 10, 31, 23, 59, 59),
        "banner_asset": {"emoji": "🌌", "gradient": ["#2b1055", "#f107a3"]},
        "challenges": [
            {"id": "cs_chat_10", "name": "First Contact", "rule": {"event": "message_sent", "count": 10},
             "reward": {"shards": 100}},
            {"id": "cs_streak_3", "name": "Spark", "rule": {"event": "streak_days", "count": 3},
             "reward": {"cosmetic_id": "wp_winter_2026"}},
            {"id": "cs_collect_5", "name": "Stargazer", "rule": {"event": "cosmetic_owned", "count": 5},
             "reward": {"gems": 30}},
        ],
        "shop_items": [
            {"cosmetic_id": "bubble_cosmic", "price_gems": 300},
            {"cosmetic_id": "wp_nebula", "price_gems": 320},
        ],
        "currency": "event_tokens",
        "progression_track": [
            {"points": 100, "reward": {"shards": 100}},
            {"points": 500, "reward": {"cosmetic_id": "typing_stars"}},
        ],
        "feature_flags": {},
    },
]

FEATURE_FLAGS = [
    ("live_profile_v2", "Animated live profiles", True, 100),
    ("mythic_effects", "Mythic-tier visual effects", True, 100),
    ("animated_wallpapers", "Animated chat wallpapers", True, 100),
    ("friend_streak_v3", "New streak engine", True, 100),
    ("new_cosmetic_shop", "Redesigned shop experience", True, 50),
    ("shared_chat_themes", "Shared per-chat themes", True, 100),
]


def cosmetic_row(t) -> dict:
    (cid, category, name, rarity, perf, tags, acq, ps, pg, set_id, avail,
     emoji, gradient, animation, lore) = t
    return dict(
        id=cid, category=category, name=name, description=lore, rarity=rarity,
        version=1,
        asset={"emoji": emoji, "gradient": gradient, "animation": animation},
        asset_hash=f"sha256:{cid}:v1",
        performance_class=perf, fallback_id=None, theme_tags=tags,
        availability=avail, acquisition=acq, price_shards=ps, price_gems=pg,
        event_id=None, obtainable=avail != "retired", transferable=(acq == "purchase"),
        set_id=set_id,
        featured=cid in {"avatar_neon_fox", "bubble_electric", "send_lightning",
                         "wp_cyberpunk", "stickers_neon_cats", "reaction_lightning"},
    )


def grant_starter_kit(db: Session, user: m.User):
    """Grant the starter kit (idempotent): entitlements, default loadout,
    empty wallets. Called at signup; also backfills users missing new kit items."""
    for cid in STARTER_KIT:
        if db.get(m.Cosmetic, cid) is None:
            continue
        if db.query(m.Entitlement).filter_by(user_id=user.id, cosmetic_id=cid).first() is None:
            db.add(m.Entitlement(user_id=user.id, cosmetic_id=cid, source="starter"))
    if db.query(m.Loadout).filter_by(user_id=user.id).first() is None:
        loadout = m.Loadout(user_id=user.id, name="Default", is_active=True)
        db.add(loadout)
        db.flush()
        slot_map = {
            "avatar_starter": "AVATAR", "frame_starter": "FRAME", "wp_starter": "WALLPAPER",
            "bubble_starter": "BUBBLE", "banner_starter": "BANNER",
        }
        for cid, slot in slot_map.items():
            db.add(m.LoadoutItem(loadout_id=loadout.id, slot=slot, cosmetic_id=cid))
    for currency in m.CURRENCIES:
        if db.query(m.Wallet).filter_by(user_id=user.id, currency=currency).first() is None:
            db.add(m.Wallet(user_id=user.id, currency=currency, balance=0))
    db.flush()


def ensure_catalog_additions(db: Session):
    """Idempotent: add any catalog rows from C that don't exist yet (v3 avatar
    starters on old databases) and grant missing starter-kit items to
    existing users."""
    added = False
    for t in C:
        if db.get(m.Cosmetic, t[0]) is None:
            db.add(m.Cosmetic(**cosmetic_row(t)))
            added = True
    if added:
        db.flush()
    # backfill starter kit for existing users (skips anything already owned)
    for (uid,) in db.query(m.User.id).all():
        user = db.get(m.User, uid)
        if user and not user.username.startswith("pending_"):
            grant_starter_kit(db, user)
    db.commit()


def seed(db: Session):
    if not db.query(m.Cosmetic).first():
        for s in SETS:
            db.add(m.CosmeticSet(**s))
        for t in C:
            db.add(m.Cosmetic(**cosmetic_row(t)))
    if not db.query(m.DailyReward).first():
        for day, shards, gems, cid in DAILY_LADDER:
            db.add(m.DailyReward(day=day, shards=shards, gems=gems, cosmetic_id=cid))
    for aid, name, desc, rule, rs, rg, rc in ACHIEVEMENTS:
        if db.get(m.Achievement, aid) is None:
            db.add(m.Achievement(id=aid, name=name, description=desc, rule=rule,
                                 reward_shards=rs, reward_gems=rg, reward_cosmetic_id=rc))
    for ev in EVENTS:
        if db.get(m.Event, ev["id"]) is None:
            db.add(m.Event(**ev))
    for key, desc, enabled, pct in FEATURE_FLAGS:
        if db.get(m.FeatureFlag, key) is None:
            db.add(m.FeatureFlag(key=key, description=desc, enabled=enabled, rollout_percent=pct))
    for bid, name, desc, cids, ps, pg in [
        ("bundle_cyber_genesis", "Cyber Genesis Bundle",
         "The complete cyber look: avatar, frame, wallpaper, bubble, send effect, stickers.",
         ["avatar_cyber_warrior", "frame_neon", "wp_cyberpunk", "bubble_electric",
          "send_lightning", "stickers_neon_cats"], 0, 450),
        ("bundle_starter_plus", "Starter Plus",
         "Polish the basics: glass bubble, neon frame, cyber typing.",
         ["bubble_glass", "frame_neon", "typing_cyber"], 500, 0),
    ]:
        if db.get(m.Bundle, bid) is None:
            db.add(m.Bundle(id=bid, name=name, description=desc, cosmetic_ids=cids,
                            price_shards=ps, price_gems=pg))
    for pid, name, gems, label in [
        ("pack_gems_small", "Handful of Gems", 100, "$0.99"),
        ("pack_gems_medium", "Pouch of Gems", 550, "$4.99"),
        ("pack_gems_large", "Vault of Gems", 1200, "$9.99"),
    ]:
        if db.get(m.CurrencyPack, pid) is None:
            db.add(m.CurrencyPack(id=pid, name=name, gems=gems, price_label=label))
    # mark event cosmetics
    for cid in ("avatar_void_sovereign", "nameplate_mythic", "bubble_liquid",
                "wp_mythic_void", "wp_winter_2026", "effect_eclipse_aura"):
        c = db.get(m.Cosmetic, cid)
        if c:
            c.event_id = "cosmic_season"
            c.acquisition = "event"
    db.commit()
    ensure_catalog_additions(db)
