// STIP API shapes (see ~/workspace/stip/API.md)

export interface AuthResult {
  access_token: string;
  refresh_token?: string;
  user_id: number;
  username: string;
  device_id?: number;
  token_type?: string;
  expires_in?: number;
}

export interface Profile {
  id: number;
  username: string;
  display_name: string;
  level: number;
  xp: number;
  is_admin: boolean;
  online?: boolean;
  last_seen?: string | null;
  wallets?: Record<string, number>;
  email?: string | null;
  phone?: string | null;
  avatar?: EquippedCosmetic | null;
  frame?: EquippedCosmetic | null;
  banner?: EquippedCosmetic | null;
  nameplate?: EquippedCosmetic | null;
  profile_effect?: EquippedCosmetic | null;
  created_at: string;
}

export interface EquippedCosmetic {
  id: string;
  name: string;
  rarity: string;
  category: string;
  asset: CosmeticAsset;
  performance_class?: string;
}

export interface Conversation {
  id: number;
  is_group: boolean;
  title?: string | null;
  members: Profile[];
  last_message?: Message | null;
  unread_count: number;
  updated_at: string;
  request?: { status: string; id: number } | null;
}

export interface ReplyPreview {
  id: number;
  sender_username: string;
  body: string | null;
  kind: string;
}

export interface Reaction {
  emoji: string;
  count: number;
  users: number[];
  effect_id?: string | null;
}

export interface Message {
  id: number;
  conversation_id: number;
  sender_id: number;
  sender_username: string;
  kind: string;
  body: string | null;
  media_url?: string | null;
  media_mime?: string | null;
  sticker_pack_id?: string | null;
  sticker_id?: string | null;
  reply_to?: ReplyPreview | null;
  forwarded: boolean;
  reactions: Reaction[];
  cosmetic_id?: string | null;
  send_effect_id?: string | null;
  client_msg_id?: string | null;
  server_sequence?: number;
  edited_at?: string | null;
  deleted: boolean;
  delivery: Record<string, string>;
  created_at: string;
  leveled_up?: boolean;
}

export interface CosmeticAsset {
  emoji?: string;
  gradient?: string[];
  animation?: string;
}

export interface Cosmetic {
  id: string;
  category: string;
  name: string;
  description: string;
  rarity: 'common' | 'uncommon' | 'rare' | 'epic' | 'legendary' | 'mythic';
  version: number;
  asset: CosmeticAsset;
  performance_class: string;
  theme_tags: string[];
  availability: string;
  acquisition: string;
  price_shards: number;
  price_gems: number;
  event_id?: string | null;
  set_id?: string | null;
  obtainable: boolean;
  transferable: boolean;
  featured: boolean;
  owned: boolean;
  status?: string;
  source?: string;
  granted_at?: string;
  favorite?: boolean;
  expires_at?: string | null;
}

export interface LoadoutItem {
  id: string;
  name: string;
  rarity: string;
  category: string;
  asset: CosmeticAsset;
}

export interface Loadout {
  id: number;
  name: string;
  is_active: boolean;
  items: Record<string, LoadoutItem | null>;
  created_at: string;
}

export interface CosmeticSet {
  id: string;
  name: string;
  description: string;
  theme: string;
  total: number;
  owned: number;
  complete: boolean;
  completion_reward?: unknown;
  items: Cosmetic[];
}

export interface CollectionBook {
  total: number;
  owned_count: number;
  items: (Cosmetic & { favorite: boolean })[];
  sets: CosmeticSet[];
  favorites: Cosmetic[];
}

export interface ChatTheme {
  wallpaper_id?: LoadoutItem | null;
  bubble_id?: LoadoutItem | null;
  send_effect_id?: LoadoutItem | null;
  reaction_effect_id?: LoadoutItem | null;
  typing_effect_id?: LoadoutItem | null;
  scope?: string;
}

export interface ShopItem extends Cosmetic {
  price_shards: number;
  price_gems: number;
}

export interface Bundle {
  id: string;
  name: string;
  description: string;
  cosmetic_ids: string[];
  price_shards: number;
  price_gems: number;
}

export interface CurrencyPack {
  id: string;
  name: string;
  gems: number;
  price_label: string;
}

export interface Shop {
  featured: ShopItem[];
  new: ShopItem[];
  by_rarity: Record<string, ShopItem[]>;
  bundles: Bundle[];
  currency_packs: CurrencyPack[];
  free: ShopItem[];
}

export interface PurchaseResult {
  ok: boolean;
  purchase_id: number;
  status: string;
  balances: Record<string, number>;
  duplicate?: boolean;
}

export interface GiftTx {
  id: number;
  sender_id: number;
  recipient_id: number;
  cosmetic_id: string;
  status: string;
  message?: string;
  created_at: string;
}

export interface DailyLadderDay {
  day: number;
  shards: number;
  gems: number;
  cosmetic_id?: string | null;
}

export interface DailyStatus {
  today: string;
  claimed: boolean;
  next_day: number;
  ladder: DailyLadderDay[];
}

export interface DailyClaim {
  ok: boolean;
  day_number: number;
  granted: { shards: number; gems: number; cosmetic_id?: string | null };
  balances: Record<string, number>;
  leveled_up: boolean;
}

export interface Streak {
  with_user?: { id: number; username: string; display_name: string } | null;
  count: number;
  longest: number;
  last_active_day?: string | null;
  message_count: number;
  milestones: string[];
}

export interface StreakDetail {
  count: number;
  longest: number;
  last_active_day?: string | null;
  message_count: number;
  first_message_at?: string | null;
  milestones: string[];
}

export interface Notification {
  id: number;
  type: string;
  title: string;
  body: string;
  data: Record<string, unknown>;
  read: boolean;
  created_at: string;
}

export interface EventChallenge {
  id: string;
  name: string;
  rule: Record<string, unknown>;
  reward: Record<string, unknown>;
  progress: number;
  target: number;
  completed: boolean;
}

export interface GameEvent {
  id: string;
  name: string;
  description: string;
  theme: string;
  status: string;
  is_live: boolean;
  start_at?: string | null;
  end_at?: string | null;
  banner_asset: CosmeticAsset;
  challenges: EventChallenge[];
  shop_items: { cosmetic_id: string; name: string; rarity: string; asset: CosmeticAsset; price_shards: number; price_gems: number }[];
  points: number;
  tiers_claimed: unknown[];
  progression_track: unknown[];
}

export interface Achievement {
  id: string;
  name: string;
  description: string;
  target: number;
  progress: number;
  unlocked: boolean;
  unlocked_at?: string | null;
  reward: { shards: number; gems: number; cosmetic_id?: string | null };
}

export interface ProgressSnapshot {
  level: number;
  xp: number;
  xp_for_next: number;
  collection: { owned: number; total: number; percent: number };
  legendary_count: number;
  titles: string[];
  stats: Record<string, number>;
}

export interface WalletTx {
  id: number;
  currency: string;
  amount_delta: number;
  balance_after: number;
  reason: string;
  source: string;
  reference_id?: string | null;
  created_at: string;
}

export interface Device {
  id: number;
  device_name?: string | null;
  platform?: string | null;
  trusted?: boolean;
  verified_at?: string | null;
  created_at: string;
  revoked: boolean;
}

// v3: message requests (explicit gate for first contact)
export interface MsgRequest {
  id: number;
  from_user_id: number;
  to_user_id: number;
  conversation_id: number;
  status: string;
  from_user?: { id: number; username: string; display_name: string } | null;
  message_preview?: string | null;
  created_at: string;
  decided_at?: string | null;
}

// v3: SSRF-guarded link previews (server-fetched only)
export interface LinkPreview {
  url: string;
  title?: string | null;
  description?: string | null;
  image?: string | null;
  site_name?: string | null;
  cached?: boolean;
}

// v3: referrals
export interface ReferralInfo {
  code: string;
  credited_last_30d: number;
  total_credited: number;
  reward_shards: number;
  credit_limit_30d: number;
}

// WebSocket frames: { type: string, ... }
export interface WSFrame {
  type: string;
  [key: string]: unknown;
}

export const RARITY_ORDER = ['common', 'uncommon', 'rare', 'epic', 'legendary', 'mythic'] as const;

export const RARITY_COLORS: Record<string, string> = {
  common: '#9aa0a6',
  uncommon: '#66bb6a',
  rare: '#42a5f5',
  epic: '#ab47bc',
  legendary: '#ffa726',
  mythic: 'linear-gradient(135deg,#f857a6,#ff8a5c,#ffd76a,#7bf59b,#5cb8ff,#c58bff)',
};

// Real backend slot list (models.py LOADOUT_SLOTS) + slot->category mapping
// (models.py SLOT_CATEGORY_MAP). API.md's shorter list is outdated.
export const LOADOUT_SLOTS = [
  'AVATAR', 'FRAME', 'BACKGROUND', 'BANNER', 'NAMEPLATE', 'STATUS_DECO',
  'BADGE', 'PROFILE_EFFECT', 'WALLPAPER', 'BUBBLE',
  'SEND_EFFECT', 'REACTION_EFFECT', 'TYPING_EFFECT',
] as const;

export const SLOT_LABELS: Record<string, string> = {
  AVATAR: 'Avatar',
  FRAME: 'Frame',
  BACKGROUND: 'Background',
  BANNER: 'Banner',
  NAMEPLATE: 'Nameplate',
  STATUS_DECO: 'Status deco',
  BADGE: 'Badge',
  PROFILE_EFFECT: 'Profile effect',
  WALLPAPER: 'Wallpaper',
  BUBBLE: 'Chat bubble',
  SEND_EFFECT: 'Send effect',
  REACTION_EFFECT: 'Reaction effect',
  TYPING_EFFECT: 'Typing effect',
};

export const SLOT_CATEGORY_MAP: Record<string, string[]> = {
  AVATAR: ['profile.avatar'],
  FRAME: ['profile.frame'],
  BACKGROUND: ['profile.background'],
  BANNER: ['profile.banner'],
  NAMEPLATE: ['profile.nameplate'],
  STATUS_DECO: ['profile.badge', 'profile.effect'],
  BADGE: ['profile.badge'],
  PROFILE_EFFECT: ['profile.effect'],
  WALLPAPER: ['chat.wallpaper'],
  BUBBLE: ['chat.bubble'],
  SEND_EFFECT: ['chat.send_effect'],
  REACTION_EFFECT: ['chat.reaction'],
  TYPING_EFFECT: ['chat.typing'],
};

export function prettyCategory(cat: string): string {
  return cat.replace(/\./g, ' ').replace(/_/g, ' ');
}
