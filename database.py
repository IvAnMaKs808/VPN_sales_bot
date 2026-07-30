"""Слой базы данных (SQLite через aiosqlite).

Все временные метки хранятся как epoch-секунды (int).
Баланс и суммы — в рублях (int).
"""
import time
import aiosqlite

from config import DB_PATH

_db: aiosqlite.Connection | None = None


def now() -> int:
    return int(time.time())


async def init_db() -> None:
    global _db
    _db = await aiosqlite.connect(DB_PATH)
    _db.row_factory = aiosqlite.Row
    await _db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            telegram_id  INTEGER PRIMARY KEY,
            username     TEXT,
            first_name   TEXT,
            referrer_id  INTEGER,
            balance      INTEGER NOT NULL DEFAULT 0,
            trial_used   INTEGER NOT NULL DEFAULT 0,
            first_paid   INTEGER NOT NULL DEFAULT 0,
            banned       INTEGER NOT NULL DEFAULT 0,
            created_at   INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS subscriptions (
            user_id         INTEGER PRIMARY KEY,
            xui_uuid        TEXT,
            xui_email       TEXT,
            sub_id          TEXT,
            expires_at      INTEGER NOT NULL DEFAULT 0,
            notified_expire INTEGER NOT NULL DEFAULT 0,
            created_at      INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS payments (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            provider    TEXT NOT NULL,
            amount      INTEGER NOT NULL,
            plan_code   TEXT,
            status      TEXT NOT NULL DEFAULT 'pending',
            external_id TEXT,
            promo_code  TEXT,
            created_at  INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS promo_codes (
            code             TEXT PRIMARY KEY,
            discount_percent INTEGER NOT NULL DEFAULT 0,
            discount_fixed   INTEGER NOT NULL DEFAULT 0,
            bonus_days       INTEGER NOT NULL DEFAULT 0,
            max_uses         INTEGER NOT NULL DEFAULT 0,
            used_count       INTEGER NOT NULL DEFAULT 0,
            active           INTEGER NOT NULL DEFAULT 1,
            created_at       INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS promo_uses (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            code       TEXT NOT NULL,
            user_id    INTEGER NOT NULL,
            created_at INTEGER NOT NULL,
            UNIQUE(code, user_id)
        );

        CREATE TABLE IF NOT EXISTS referral_earnings (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id INTEGER NOT NULL,
            referred_id INTEGER NOT NULL,
            payment_id  INTEGER,
            amount      INTEGER NOT NULL,
            created_at  INTEGER NOT NULL
        );
        """
    )
    await _db.commit()


# ----------------------------- users -----------------------------
async def get_user(tg_id: int):
    async with _db.execute("SELECT * FROM users WHERE telegram_id=?", (tg_id,)) as c:
        return await c.fetchone()


async def ensure_user(tg_id: int, username: str, first_name: str, referrer_id: int | None):
    """Создаёт пользователя, если его нет. Реферер фиксируется только при создании."""
    user = await get_user(tg_id)
    if user:
        # обновим username/имя на случай изменений
        await _db.execute(
            "UPDATE users SET username=?, first_name=? WHERE telegram_id=?",
            (username, first_name, tg_id),
        )
        await _db.commit()
        return user, False
    # нельзя быть рефералом самого себя
    if referrer_id == tg_id:
        referrer_id = None
    if referrer_id and not await get_user(referrer_id):
        referrer_id = None
    await _db.execute(
        "INSERT INTO users (telegram_id, username, first_name, referrer_id, created_at) "
        "VALUES (?,?,?,?,?)",
        (tg_id, username, first_name, referrer_id, now()),
    )
    await _db.commit()
    return await get_user(tg_id), True


async def set_banned(tg_id: int, banned: bool):
    await _db.execute("UPDATE users SET banned=? WHERE telegram_id=?", (1 if banned else 0, tg_id))
    await _db.commit()


async def add_balance(tg_id: int, amount: int):
    await _db.execute("UPDATE users SET balance=balance+? WHERE telegram_id=?", (amount, tg_id))
    await _db.commit()


async def deduct_balance(tg_id: int, amount: int) -> bool:
    user = await get_user(tg_id)
    if not user or user["balance"] < amount:
        return False
    await _db.execute("UPDATE users SET balance=balance-? WHERE telegram_id=?", (amount, tg_id))
    await _db.commit()
    return True


async def mark_trial_used(tg_id: int):
    await _db.execute("UPDATE users SET trial_used=1 WHERE telegram_id=?", (tg_id,))
    await _db.commit()


async def mark_first_paid(tg_id: int) -> bool:
    """Возвращает True, если это была ПЕРВАЯ оплата (флаг только что установлен)."""
    user = await get_user(tg_id)
    if not user or user["first_paid"]:
        return False
    await _db.execute("UPDATE users SET first_paid=1 WHERE telegram_id=?", (tg_id,))
    await _db.commit()
    return True


async def count_referrals(tg_id: int) -> int:
    async with _db.execute("SELECT COUNT(*) AS c FROM users WHERE referrer_id=?", (tg_id,)) as c:
        row = await c.fetchone()
        return row["c"]


async def all_user_ids() -> list[int]:
    async with _db.execute("SELECT telegram_id FROM users WHERE banned=0") as c:
        return [r["telegram_id"] for r in await c.fetchall()]


# ------------------------- subscriptions -------------------------
async def get_subscription(user_id: int):
    async with _db.execute("SELECT * FROM subscriptions WHERE user_id=?", (user_id,)) as c:
        return await c.fetchone()


async def save_subscription(user_id: int, uuid: str, email: str, sub_id: str, expires_at: int):
    await _db.execute(
        "INSERT INTO subscriptions (user_id, xui_uuid, xui_email, sub_id, expires_at, notified_expire, created_at) "
        "VALUES (?,?,?,?,?,0,?) "
        "ON CONFLICT(user_id) DO UPDATE SET xui_uuid=excluded.xui_uuid, "
        "xui_email=excluded.xui_email, sub_id=excluded.sub_id, "
        "expires_at=excluded.expires_at, notified_expire=0",
        (user_id, uuid, email, sub_id, expires_at, now()),
    )
    await _db.commit()


async def set_expiry(user_id: int, expires_at: int):
    # сброс флага уведомления — при продлении снова напомним ближе к концу
    await _db.execute(
        "UPDATE subscriptions SET expires_at=?, notified_expire=0 WHERE user_id=?",
        (expires_at, user_id),
    )
    await _db.commit()


async def subs_needing_expiry_notice(window_end: int):
    """Активные подписки, истекающие до window_end, которым ещё не отправляли напоминание."""
    async with _db.execute(
        "SELECT * FROM subscriptions WHERE notified_expire=0 "
        "AND expires_at > ? AND expires_at <= ?", (now(), window_end)
    ) as c:
        return await c.fetchall()


async def mark_expiry_notified(user_id: int):
    await _db.execute("UPDATE subscriptions SET notified_expire=1 WHERE user_id=?", (user_id,))
    await _db.commit()


async def active_subscriptions_count() -> int:
    async with _db.execute(
        "SELECT COUNT(*) AS c FROM subscriptions WHERE expires_at > ?", (now(),)
    ) as c:
        return (await c.fetchone())["c"]


async def subscriptions_expiring_between(start: int, end: int):
    """Подписки, срок которых истекает в интервале (start, end]."""
    async with _db.execute(
        "SELECT * FROM subscriptions WHERE expires_at > ? AND expires_at <= ?", (start, end)
    ) as c:
        return await c.fetchall()


# --------------------------- payments ---------------------------
async def add_payment(user_id: int, provider: str, amount: int, plan_code: str,
                      external_id: str, promo_code: str | None) -> int:
    cur = await _db.execute(
        "INSERT INTO payments (user_id, provider, amount, plan_code, status, external_id, promo_code, created_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (user_id, provider, amount, plan_code, "pending", external_id, promo_code, now()),
    )
    await _db.commit()
    return cur.lastrowid


async def set_payment_status(payment_id: int, status: str):
    await _db.execute("UPDATE payments SET status=? WHERE id=?", (status, payment_id))
    await _db.commit()


async def get_payment(payment_id: int):
    async with _db.execute("SELECT * FROM payments WHERE id=?", (payment_id,)) as c:
        return await c.fetchone()


async def pending_payments(since: int):
    """Незавершённые внешние платежи, созданные не раньше since (для фонового поллинга)."""
    async with _db.execute(
        "SELECT * FROM payments WHERE status='pending' "
        "AND provider IN ('yookassa','crypto') AND created_at >= ?", (since,)
    ) as c:
        return await c.fetchall()


async def total_revenue() -> int:
    """Реальная выручка — только внешние платежи (без оплат с внутреннего баланса)."""
    async with _db.execute(
        "SELECT COALESCE(SUM(amount),0) AS s FROM payments "
        "WHERE status='succeeded' AND provider IN ('yookassa','crypto')"
    ) as c:
        return (await c.fetchone())["s"]


async def users_count() -> int:
    async with _db.execute("SELECT COUNT(*) AS c FROM users") as c:
        return (await c.fetchone())["c"]


# --------------------------- promo ---------------------------
async def get_promo(code: str):
    async with _db.execute("SELECT * FROM promo_codes WHERE code=?", (code,)) as c:
        return await c.fetchone()


async def create_promo(code: str, percent: int, fixed: int, bonus_days: int, max_uses: int):
    await _db.execute(
        "INSERT OR REPLACE INTO promo_codes "
        "(code, discount_percent, discount_fixed, bonus_days, max_uses, used_count, active, created_at) "
        "VALUES (?,?,?,?,?,0,1,?)",
        (code, percent, fixed, bonus_days, max_uses, now()),
    )
    await _db.commit()


async def promo_used_by(code: str, user_id: int) -> bool:
    async with _db.execute(
        "SELECT 1 FROM promo_uses WHERE code=? AND user_id=?", (code, user_id)
    ) as c:
        return await c.fetchone() is not None


async def register_promo_use(code: str, user_id: int):
    await _db.execute(
        "INSERT OR IGNORE INTO promo_uses (code, user_id, created_at) VALUES (?,?,?)",
        (code, user_id, now()),
    )
    await _db.execute("UPDATE promo_codes SET used_count=used_count+1 WHERE code=?", (code,))
    await _db.commit()


# ------------------------ referral earnings ------------------------
async def add_referral_earning(referrer_id: int, referred_id: int, payment_id: int, amount: int):
    await _db.execute(
        "INSERT INTO referral_earnings (referrer_id, referred_id, payment_id, amount, created_at) "
        "VALUES (?,?,?,?,?)",
        (referrer_id, referred_id, payment_id, amount, now()),
    )
    await _db.commit()
