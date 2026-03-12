import html
import json
import re
import time
import urllib.parse
from pathlib import Path

import requests
from fastapi import FastAPI, Request, HTTPException, Body, Header
from hypy_utils import ensure_dir
from hypy_utils.logging_utils import setup_logger
from starlette.responses import HTMLResponse, JSONResponse
from starlette.staticfiles import StaticFiles
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

import db
import utils
from utils import gen_sha, CONFIG

BOT_TOKEN = CONFIG["token"]
BOT_NAME = CONFIG["name"]

app = FastAPI()
logger = setup_logger()
bot = Application.builder().token(BOT_TOKEN).build()

data_dir = Path(__file__).parent / "data"
channels_dir = ensure_dir(data_dir / "channels")

validating = set()

# State tracking for tree hole conversations
# user_id -> {"action": "treehole"|"reply"|"leaf", ...}
states_file = data_dir / "user_states.json"


def load_states() -> dict[int, dict]:
    if states_file.exists():
        raw = json.loads(states_file.read_text(encoding='utf-8'))
        return {int(k): v for k, v in raw.items()}
    return {}


def set_state(user_id: int, state: dict | None):
    """Set or clear the state for a user, and persist to disk."""
    if state is None:
        user_states.pop(user_id, None)
    else:
        user_states[user_id] = state
    states_file.write_text(json.dumps({str(k): v for k, v in user_states.items()},
                                       ensure_ascii=False), encoding='utf-8')


user_states: dict[int, dict] = load_states()

# Rate limiting for tree hole messages: user_id -> last send timestamp
treehole_rate_limit: dict[int, float] = {}
TREEHOLE_COOLDOWN = 30  # seconds

# Animal emojis for anonymous tree hole identities
ANIMAL_EMOJIS = [
    "🐶", "🐱", "🐭", "🐹", "🐰", "🦊", "🐻", "🐼", "🐨", "🐯",
    "🦁", "🐮", "🐷", "🐸", "🐵", "🐔", "🐧", "🐦", "🦅", "🦆",
    "🦉", "🦇", "🐺", "🐗", "🐴", "🦄", "🐝", "🐛", "🦋", "🐌",
    "🐚", "🐞", "🐫", "🦒", "🐘", "🦏", "🦛", "🐪", "🦖", "🐳",
    "🐬", "🐠", "🐙", "🦐", "🦑", "🦥", "🦚", "🦜", "🦩", "🐿️",
    "🦔", "🦃", "🦢", "🦫", "🦦", "🦨", "🦝", "🐋", "🦈", "🦤",
    "🍇", "🍈", "🍉", "🍊", "🍋", "🍌", "🍍", "🥭", "🍎", "🍏", 
    "🍐", "🍑", "🍒", "🍓", "🫐", "🥝", "🍅", "🫒", "🥥",
]


def anon_name(user_id: int) -> str:
    """Generate a consistent anonymous name for a user based on their ID."""
    return ANIMAL_EMOJIS[user_id % len(ANIMAL_EMOJIS)]


def user_info(update: Update):
    return (f"{update.message.from_user.id} {update.message.from_user.username or ''} "
            f"{update.message.from_user.first_name or ''} {update.message.from_user.last_name or ''}")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"/start from {user_info(update)}")

    # Handle deep-link payloads (e.g. /start water_channelname)
    if context.args:
        payload = context.args[0]
        uid = update.message.from_user.id

        if payload.startswith("water_"):
            channel = payload[6:]
            return await handle_water(update, uid, channel)

        if payload.startswith("th_"):
            channel = payload[3:]
            return await handle_treehole(update, uid, channel)

        if payload.startswith("leaf_"):
            channel = payload[5:]
            return await handle_leaf(update, uid, channel)

    await update.message.reply_text("🌳🌳🌳")


def channel_html(channel: str):
    ouf = (channels_dir / f"{channel}.html")
    if ouf.exists():
        return ouf.read_text('utf-8')
    t = requests.get(f"https://t.me/{channel}").text
    ouf.write_text(t, encoding='utf-8')
    return t


def channel_buttons(channel: str) -> InlineKeyboardMarkup:
    """Build the inline keyboard buttons for a channel post. All buttons use URL
    deep-links so the keyboard is preserved when the message is forwarded."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌿 成为树叶", url=f"https://t.me/{BOT_NAME}?start=leaf_{channel}")],
        [InlineKeyboardButton("💧 浇水", url=f"https://t.me/{BOT_NAME}?start=water_{channel}"),
         InlineKeyboardButton("🕳️ 树洞", url=f"https://t.me/{BOT_NAME}?start=th_{channel}")],
    ])


def shareable_message(channel: str, title: str, description: str) -> str:
    """Build the shareable HTML message for a channel post."""
    url_enc = urllib.parse.quote_plus(f"https://tree.aza.moe/c/{channel}")
    return f"""
又到了植树节！想和大家一起再种一颗 <a href="https://tree.aza.moe">tgcn 频道树🌳</a>！（这次有更多功能可以玩哦~）

这里是 {title}，{description}

（如果你也有公开频道，想成为这个频道的树叶的话，就点击下面的「成为树叶」吧！ &gt; &lt;） <a href="https://t.me/iv?url={url_enc}&rhash=d96b84e483dc30">\u200e</a>
""".strip()


async def init(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /init — create the root channel of the tree (password-protected)."""
    if update.message.chat.type != "private":
        return

    logger.info(f"/init from {user_info(update)}")

    args, uid = context.args, update.message.from_user.id
    if len(args) != 2:
        return await update.message.reply_text("用法是 /init <密码> <根频道名> 哦~")

    password, channel = args
    channel = channel.strip("<>{} @")

    if password != CONFIG.get("init-password", ""):
        return await update.message.reply_text("密码不对哦~")

    info = utils.extract_meta_tags(channel_html(channel))
    title = info.title or channel

    logger.info(f"> 🌳 Initializing root channel {channel}.")
    db.register(channel, title, owner_id=uid)

    await update.message.reply_text(f"🌳 根频道 @{channel} 创建成功！把下面这条转发到频道里吧~")
    return await update.message.reply_html(
        shareable_message(channel, title, "是频道树的树根 🌳"),
        reply_markup=channel_buttons(channel))


async def plant(update: Update):
    """Handle /leaf — deprecated, redirect to button flow."""
    if update.message.chat.type != "private":
        return
    await update.message.reply_text("/leaf 指令已经不再使用了哦~ 请点击频道消息上的「🌿 成为树叶」按钮吧！")


async def handle_leaf(update: Update, user_id: int, parent: str):
    """Handle the 成为树叶 action via deep-link — ask for the user's channel name."""
    logger.info(f"🌿 Leaf request from {user_id} for parent {parent}")

    if not db.channel_info(parent):
        return await update.message.reply_text("上级频道还不在树上... 是不是打错了 qwq")

    set_state(user_id, {"action": "leaf", "parent": parent})
    await update.message.reply_html(f"🌿 <b>成为树叶</b>\n\n你想让哪个频道成为 @{parent} 的树叶呢？（请发送你的频道的 @用户名）")


async def handle_water(update: Update, user_id: int, channel: str):
    """Handle the 浇水 (water/upvote) action via deep-link."""
    logger.info(f"💧 Water from {user_id} for {channel}")

    info = db.channel_info(channel)
    if not info:
        return await update.message.reply_text("这个频道不在树上哦~")

    # Block self-watering
    owner_id = db.get_channel_owner(channel)
    if owner_id == user_id:
        return await update.message.reply_text("不能给自己的频道浇水哦~ 🥺")

    if db.add_vote(user_id, channel):
        votes = db.get_votes(channel)
        await update.message.reply_text(f"💧 浇水成功！这个树枝已经被浇了 {votes} 次水~")
    else:
        votes = db.get_votes(channel)
        await update.message.reply_text(f"你已经浇过水了哦~ 这个树枝已经被浇了 {votes} 次水~")


async def handle_treehole(update: Update, user_id: int, channel: str):
    """Handle the 树洞 action via deep-link."""
    logger.info(f"🕳️ Tree hole from {user_id} for {channel}")

    # Check if channel has an owner
    owner_id = db.get_channel_owner(channel)
    if not owner_id:
        return await update.message.reply_text("这个频道还没有设置主人哦~")

    # Block sending to oneself
    if owner_id == user_id:
        return await update.message.reply_text("不能给自己发树洞消息哦~ 🥺")

    # Check if owner walked away
    if db.is_treehole_opted_out(owner_id):
        return await update.message.reply_text("树洞对面没有人的样子，过一会再试试吧！（对方关闭了树洞）")

    # Check rate limit
    last_time = treehole_rate_limit.get(user_id, 0)
    if time.time() - last_time < TREEHOLE_COOLDOWN:
        remaining = int(TREEHOLE_COOLDOWN - (time.time() - last_time))
        return await update.message.reply_text(f"发送太频繁了，请 {remaining} 秒后再试~")

    set_state(user_id, {"action": "treehole", "channel": channel})
    return await update.message.reply_html(f"🕳️ <b>树洞模式</b>\n\n想对频道 @{channel} 的主人说什么呢？"
                                           f"（发送文字消息即可，消息将会匿名发送）")


async def reply_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the channel owner clicking reply to a tree hole message."""
    query = update.callback_query
    data = query.data

    parts = data.split(":", 2)

    # New format: reply:{msg_id}
    if len(parts) == 2:
        msg = db.get_treehole_msg(int(parts[1]))
        if not msg:
            return await query.answer("这条消息已经过期了哦~", show_alert=False)
        sender_id, channel = msg.sender_id, msg.channel_id
    # Old format (backward compat): reply:{sender_id}:{channel}
    elif len(parts) == 3:
        sender_id, channel = int(parts[1]), parts[2]
    else:
        return

    owner_id = query.from_user.id

    # Verify the person clicking is the channel owner
    actual_owner = db.get_channel_owner(channel)
    if actual_owner != owner_id:
        return await query.answer("只有频道主人才能回复哦~", show_alert=False)

    set_state(owner_id, {"action": "reply", "sender_id": sender_id, "channel": channel})
    await query.answer()
    return await context.bot.send_message(
        chat_id=owner_id,
        text="💬 回复模式\n\n请输入你想回复的内容（发送文字消息即可）"
    )


async def block_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the channel owner clicking block on a tree hole message sender."""
    query = update.callback_query
    data = query.data

    parts = data.split(":", 2)

    # New format: block:{msg_id}
    if len(parts) == 2:
        msg = db.get_treehole_msg(int(parts[1]))
        if not msg:
            return await query.answer("这条消息已经过期了哦~", show_alert=False)
        sender_id, channel = msg.sender_id, msg.channel_id
    # Old format (backward compat): block:{sender_id}:{channel}
    elif len(parts) == 3:
        sender_id, channel = int(parts[1]), parts[2]
    else:
        return

    owner_id = query.from_user.id

    # Verify the person clicking is the channel owner
    actual_owner = db.get_channel_owner(channel)
    if actual_owner != owner_id:
        return await query.answer("只有频道主人才能屏蔽哦~", show_alert=False)

    if db.block_user(sender_id, channel):
        return await query.answer("✅ 已屏蔽该发送者", show_alert=True)
    else:
        return await query.answer("该发送者已经被屏蔽了", show_alert=False)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages for tree hole composing and owner replies."""
    if update.message.chat.type != "private":
        return

    user_id = update.message.from_user.id
    state = user_states.get(user_id)

    if not state:
        return await update.message.reply_text("🌳 不太明白你在说什么哦~ 请点击频道消息上的按钮来互动吧！\n"
                                               "（如果哪里不对的话，应该是 bot 重启了，重新点击按钮就好 ;-;）")

    if state["action"] == "leaf":
        if not update.message.text:
            return await update.message.reply_text("请发送频道的 @用户名哦~")

        parent = state["parent"]
        channel = update.message.text.strip().strip("<>{} @")
        uid = user_id

        # Validate channel name (keep state so user can retry)
        if not re.match(r"^[0-9a-zA-Z_]+$", channel):
            return await update.message.reply_text("没有找到这个频道... 只有公开的频道可以参与，"
                                                   "以及需要输入频道的 @用户名，不是显示名哦~")

        if db.channel_info(channel):
            return await update.message.reply_text(f"这个频道已经在树上了哦~ https://tree.aza.moe/c/{channel}")

        sha = gen_sha(channel, uid, parent)

        # Check channel
        text = channel_html(channel)
        if 'noindex, nofollow' in text:
            return await update.message.reply_text("没有找到这个频道... 只有公开的频道可以参与，"
                                                   "以及需要输入频道的 @用户名，不是显示名哦~")

        # Success paths — clear state
        set_state(user_id, None)

        info = utils.extract_meta_tags(text)
        if sha in text:
            title = info.title or channel
            logger.info(f"> 🌿 Registering channel {channel} with parent {parent}.")
            height = db.register(channel, title, parent, owner_id=uid)
            await update.message.reply_text(f"频道 {channel} 上树成功！把下面这条转发到频道里吧~")
            return await update.message.reply_html(
                shareable_message(channel, title, f"是 @{parent} 的树枝 🌿 在频道树的第 {height + 1} 层~"),
                reply_markup=channel_buttons(channel))

        verify_btn = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ 添加好了", callback_data=f"verify:{channel}:{parent}")],
        ])
        await update.message.reply_text(f"""
好耶！

不过上树之前，为了防止被滥用，需要先验证一下你是 {channel} 的管理员...

请编辑频道简介加入验证码 <code>{sha}</code> 再点击下面的「添加好了」吧~（加在哪里都可以的 &gt; &lt; 验证完就可以删掉）
""".strip(), reply_markup=verify_btn, parse_mode="HTML")
        validating.add(sha)

    elif state["action"] == "treehole":
        channel = state["channel"]
        set_state(user_id, None)

        # Update rate limit
        treehole_rate_limit[user_id] = time.time()

        # Shadowban: if blocked, pretend the message was sent
        if db.is_blocked(user_id, channel):
            logger.info(f"🕳️ Shadowbanned message from {user_id} for {channel}")
            return await update.message.reply_text("✅ 消息已匿名发送~")

        # Get channel owner
        owner_id = db.get_channel_owner(channel)
        if not owner_id:
            return await update.message.reply_text("这个频道还没有设置主人哦~")

        # If owner opted out, silently drop (shadowban style)
        if db.is_treehole_opted_out(owner_id):
            logger.info(f"🕳️ Owner {owner_id} opted out, dropping message from {user_id} for {channel}")
            return await update.message.reply_text("✅ 消息已匿名发送~")

        # Send first-time notice to owner if not yet notified
        if not db.is_treehole_notified(owner_id):
            db.set_treehole_notified(owner_id)
            try:
                await context.bot.send_message(
                    chat_id=owner_id,
                    text="<b>树洞对面传来消息了！</b>（其实是匿名消息功能啦）\n\n如果不想要听到树洞消息的话可以说 /walkaway",
                    parse_mode="HTML"
                )
            except Exception:
                pass

        # Send to owner anonymously
        msg_id = db.create_treehole_msg(user_id, channel)
        reply_btn = InlineKeyboardMarkup([
            [InlineKeyboardButton("💬 回复", callback_data=f"reply:{msg_id}")],
            [InlineKeyboardButton("🚫 屏蔽发送者", callback_data=f"block:{msg_id}")],
        ])

        try:
            name = anon_name(user_id)
            if update.message.sticker:
                await context.bot.send_message(
                    chat_id=owner_id,
                    text=f"🕳️ <b>树洞消息</b>\n\n匿名{name}对你的频道 @{channel} 发了一张贴纸：",
                    parse_mode="HTML"
                )
                await context.bot.send_sticker(
                    chat_id=owner_id,
                    sticker=update.message.sticker.file_id,
                    reply_markup=reply_btn
                )
                await update.message.reply_text("✅ 贴纸已匿名发送~")
            else:
                escaped_text = html.escape(update.message.text or "")
                await context.bot.send_message(
                    chat_id=owner_id,
                    text=f"🕳️ <b>树洞消息</b>\n\n匿名{name}对你的频道 @{channel} 说：\n\n{escaped_text}",
                    reply_markup=reply_btn,
                    parse_mode="HTML"
                )
                await update.message.reply_text("✅ 消息已匿名发送~")
        except Exception:
            await update.message.reply_text("发送失败了... 频道主人可能还没有启用 bot")

    elif state["action"] == "reply":
        sender_id = state["sender_id"]
        channel = state["channel"]
        set_state(user_id, None)

        try:
            reply_back_btn = InlineKeyboardMarkup([
                [InlineKeyboardButton("💬 回复", url=f"https://t.me/{BOT_NAME}?start=th_{channel}")],
            ])
            if update.message.sticker:
                await context.bot.send_message(
                    chat_id=sender_id,
                    text=f"💬 <b>频道 @{channel} 的主人回复了你的树洞消息：</b>",
                    parse_mode="HTML"
                )
                await context.bot.send_sticker(
                    chat_id=sender_id,
                    sticker=update.message.sticker.file_id,
                    reply_markup=reply_back_btn
                )
                await update.message.reply_text("✅ 回复已发送~")
            else:
                escaped_text = html.escape(update.message.text or "")
                await context.bot.send_message(
                    chat_id=sender_id,
                    text=f"💬 <b>频道 @{channel} 的主人回复了你的树洞消息：</b>\n\n{escaped_text}",
                    reply_markup=reply_back_btn,
                    parse_mode="HTML"
                )
                await update.message.reply_text("✅ 回复已发送~")
        except Exception:
            await update.message.reply_text("回复发送失败了...")


async def walkaway(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /walkaway — owner opts out of tree hole messages."""
    if update.message.chat.type != "private":
        return

    uid = update.message.from_user.id
    logger.info(f"/walkaway from {user_info(update)}")

    db.set_treehole_optout(uid, True)
    await update.message.reply_text("你离开了树洞！如果想重新开始收到树洞消息的话请说 /walkback")


async def walkback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /walkback — owner opts back in to tree hole messages."""
    if update.message.chat.type != "private":
        return

    uid = update.message.from_user.id
    logger.info(f"/walkback from {user_info(update)}")

    db.set_treehole_optout(uid, False)
    await update.message.reply_text("欢迎回到树洞！你现在可以重新收到树洞消息了~")


async def verify_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the 添加好了 button — re-check verification code."""
    query = update.callback_query
    data = query.data

    # Format: verify:{channel}:{parent}
    parts = data.split(":", 2)
    if len(parts) != 3:
        return

    _, channel, parent = parts
    uid = query.from_user.id
    sha = gen_sha(channel, uid, parent)

    # Delete cached HTML to force re-fetch
    cached = channels_dir / f"{channel}.html"
    if cached.exists():
        cached.unlink()

    text = channel_html(channel)
    if sha in text:
        # Check if already registered (e.g. double-click)
        if db.channel_info(channel):
            return await query.answer("这个频道已经在树上了哦~", show_alert=False)

        info = utils.extract_meta_tags(text)
        title = info.title or channel
        logger.info(f"> 🌿 Registering channel {channel} with parent {parent}.")
        height = db.register(channel, title, parent, owner_id=uid)
        await query.answer("✅ 验证成功！", show_alert=False)
        await query.message.reply_text(f"频道 {channel} 上树成功！把下面这条转发到频道里吧~（以及不要忘记把验证码删掉哦）")
        await query.message.reply_html(
            shareable_message(channel, title, f"是 @{parent} 的树枝 🌿 在频道树的第 {height + 1} 层~"),
            reply_markup=channel_buttons(channel))
    else:
        await query.answer("看了一下好像频道信息还没有更新的样子... 确定加上了吗？再试试吧", show_alert=True)


# Add handlers
bot.add_handler(CommandHandler("start", start))
bot.add_handler(CommandHandler("init", init))
bot.add_handler(CommandHandler("leaf", plant))
bot.add_handler(CommandHandler("walkaway", walkaway))
bot.add_handler(CommandHandler("walkback", walkback))
bot.add_handler(CallbackQueryHandler(verify_callback, pattern=r"^verify:"))
bot.add_handler(CallbackQueryHandler(reply_callback, pattern=r"^reply:"))
bot.add_handler(CallbackQueryHandler(block_callback, pattern=r"^block:"))
bot.add_handler(MessageHandler((filters.TEXT | filters.Sticker.ALL) & ~filters.COMMAND, handle_message))


@app.on_event("startup")
async def startup_event():
    """Starts the bot."""
    logger.info("Starting bot...")
    await bot.initialize()
    await bot.start()
    await bot.updater.start_polling()


@app.on_event("shutdown")
async def shutdown_event():
    """Stops the bot on shutdown."""
    logger.info("Stopping bot...")
    await bot.updater.stop()
    await bot.stop()
    await bot.shutdown()


layout_html = (Path(__file__).parent.parent / "public" / "layout.html").read_text('utf-8')
fmt_html = lambda x: layout_html.replace("{{CONTENT}}", x).replace("\n", "")


def tree_to_dict(channel: str) -> dict | None:
    """Recursively build a dict representation of the tree for the API."""
    info = db.channel_info(channel)
    if not info:
        return None
    return {
        "username": channel,
        "name": info.name,
        "water": db.get_votes(channel),
        "children": [tree_to_dict(c.username) for c in info.children],
    }


@app.get("/api/tree")
def api_tree():
    return tree_to_dict("azaneko")


@app.get("/api/admin/channels")
def api_admin_channels(x_admin_password: str = Header(None)):
    if x_admin_password not in CONFIG.get("admin-passwords", [CONFIG.get("init-password")]):
        raise HTTPException(status_code=403, detail="Invalid admin password")

    channels = db.get_all_channels()
    return [{"username": c.username, "name": c.name, "parent": c.parent_id, "hidden": c.hidden} for c in channels]


@app.post("/api/admin/channels/{username}/hide")
def api_hide_channel(username: str, hidden: bool = Body(..., embed=True), x_admin_password: str = Header(None)):
    if x_admin_password not in CONFIG.get("admin-passwords", [CONFIG.get("init-password")]):
        raise HTTPException(status_code=403, detail="Invalid admin password")

    if db.set_hidden(username, hidden):
        return {"success": True}
    else:
        raise HTTPException(status_code=404, detail="Channel not found")


@app.delete("/api/admin/channels/{username}")
def api_delete_channel(username: str, x_admin_password: str = Header(None)):
    if x_admin_password not in CONFIG.get("admin-passwords", [CONFIG.get("init-password")]):
        raise HTTPException(status_code=403, detail="Invalid admin password")

    if db.remove_channel(username):
        return {"success": True}
    else:
        raise HTTPException(status_code=404, detail="Channel not found")


@app.get("/c/{channel}", response_class=HTMLResponse)
def channel_info(channel: str):
    info = db.channel_info(channel)

    if not info:
        return fmt_html(f"""
            <h1>TGCN 频道树！</h1>
            <p>频道 @{channel} 不在树上哦~</p>
        """)

    leaf_txt = '树枝' if info.children else '树叶'
    votes = db.get_votes(channel)
    water_html = f'<p>💧 这个频道已经被浇了 {votes} 次水~</p>' if votes else ''

    return fmt_html(f"""
        <h1>TGCN 频道树！</h1>
        <p>这里是频道 <a href="https://t.me/{channel}">@{channel}</a> - {info.name}，{
            f'在频道树的第 {info.height + 1} 层，是 <a href="https://t.me/{info.parent}">@{info.parent}</a> (<a href="/c/{info.parent}">🔗</a>) 的{leaf_txt}哦~'
            if info.parent else "是树根哦~"
        }</p>
        {water_html}
        {f"""<p>下面这些是这个频道的树枝：</p>
        <ul>
            {"".join(f'<li><a href="https://t.me/{child.username}">@{child.username}</a> (<a href="/c/{child.username}">🔗</a>) - {child.name}</li>' for child in info.children)}
        </ul>""" if info.children else "这个频道是树叶哦~"}
        <p class="note">（如果你也有公开频道，想成为这个频道的树叶的话，就点击频道消息上的「🌿 成为树叶」按钮吧! &gt; &lt;）</p>
    """)


app.mount("/", StaticFiles(directory="public", html=True))


if __name__ == '__main__':
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=9498)
