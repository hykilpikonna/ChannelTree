import re
import time
import tomllib
import urllib.parse
from pathlib import Path

import requests
from fastapi import FastAPI
from hypy_utils import ensure_dir
from hypy_utils.logging_utils import setup_logger
from starlette.responses import HTMLResponse
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
# user_id -> {"action": "treehole"|"reply", "channel": str, "sender_id": int (for reply)}
user_states: dict[int, dict] = {}

# Rate limiting for tree hole messages: user_id -> last send timestamp
treehole_rate_limit: dict[int, float] = {}
TREEHOLE_COOLDOWN = 30  # seconds


def user_info(update: Update):
    return (f"{update.message.from_user.id} {update.message.from_user.username or ''} "
            f"{update.message.from_user.first_name or ''} {update.message.from_user.last_name or ''}")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"/start from {user_info(update)}")
    await update.message.reply_text("🌳🌳🌳")


def channel_html(channel: str):
    ouf = (channels_dir / f"{channel}.html")
    if ouf.exists():
        return ouf.read_text()
    t = requests.get(f"https://t.me/{channel}").text
    ouf.write_text(t)
    return t


async def plant(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private":
        return

    logger.info(f"/leaf from {user_info(update)}: {update.message.text}")

    args, uid = context.args, update.message.from_user.id
    if len(args) != 2:
        logger.info(f"> Invalid args.")
        return await update.message.reply_text("用法是 /leaf <上级频道名> <你的频道名> 哦~")

    parent, channel = args
    parent, channel = parent.strip("<>{} @"), channel.strip("<>{} @")
    sha = gen_sha(channel, uid, parent)

    # Check if channel only contains 0-9, a-z, A-Z and _
    if not re.match(r"^[0-9a-zA-Z_]+$", channel):
        logger.info(f"> Invalid channel name.")
        return await update.message.reply_text("没有找到这个频道... 只有公开的频道可以参与，以及需要输入频道的 @用户名，不是显示名哦~")

    if not db.channel_info(parent):
        logger.info(f"> Parent channel not found.")
        return await update.message.reply_text("上级频道还不在树上... 是不是打错了 qwq")

    # 检查在不在树上
    if db.channel_info(channel):
        logger.info(f"> Channel already exists.")
        return await update.message.reply_text(f"这个频道已经在树上了哦~ https://tree.aza.moe/c/{channel}")

    # 检查验证码
    text = channel_html(channel)
    if 'noindex, nofollow' in text:
        logger.info(f"> Channel noindex, nofollow.")
        return await update.message.reply_text("没有找到这个频道... 只有公开的频道可以参与，以及需要输入频道的 @用户名，不是显示名哦~")

    info = utils.extract_meta_tags(text)
    if sha in text:
        logger.info(f"> 🌿 Registering channel {channel} with parent {parent}.")
        height = db.register(channel, info.title, parent, owner_id=uid)
        await update.message.reply_text(f"""频道 {channel} 上树成功！把下面这条转发到频道里吧~""".strip())
        url_enc = urllib.parse.quote_plus(f"https://tree.aza.moe/c/{channel}")
        leaf_text = urllib.parse.quote(f"/leaf {channel} ")
        leaf_btn = InlineKeyboardMarkup([
            [InlineKeyboardButton("🌿 成为树叶", url=f"https://t.me/{BOT_NAME}?text={leaf_text}")],
            [InlineKeyboardButton("💧 浇水", callback_data=f"water:{channel}")],
            [InlineKeyboardButton("🕳️ 树洞", callback_data=f"th:{channel}")],
        ])
        return await update.message.reply_html(f"""
今天是植树节，想试试和大家一起种一颗 tgcn 频道树 🌳 qwq

这里是 {info.title}，是 @{parent} 的树枝 🌿 在频道树的第 {height + 1} 层哦~

（如果你也有公开频道，想成为这个频道的树叶的话，就点击下面的「成为树叶」吧！ &gt; &lt;） <a href="https://t.me/iv?url={url_enc}&rhash=d96b84e483dc30">\u200e</a>
""".strip(), reply_markup=leaf_btn)

    if sha not in validating:
        logger.info(f"> Channel not validated, asking for validation.")
        await update.message.reply_text(f"""
好耶！

不过上树之前，为了防止被滥用，需要先验证一下你是 {channel} 的管理员...

请编辑频道简介加入验证码 {sha} 再重新执行这条指令吧~（加在哪里都可以的 > < 验证完就可以删掉）
""".strip())
        validating.add(sha)
    else:
        logger.info(f"> Channel not validated, asking again for validation.")
        await update.message.reply_text("（看了一下好像频道信息还没有更新的样子... 确定加上了吗？再试试吧）")


async def water_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the 浇水 (water/upvote) button press."""
    query = update.callback_query
    data = query.data

    if not data.startswith("water:"):
        return

    channel = data[len("water:"):]
    user_id = query.from_user.id

    logger.info(f"💧 Water from {user_id} {query.from_user.username or ''} for {channel}")

    # Check if the channel exists
    info = db.channel_info(channel)
    if not info:
        return await query.answer("这个频道不在树上哦~", show_alert=False)

    # Try to add the vote
    if db.add_vote(user_id, channel):
        votes = db.get_votes(channel)
        await query.answer(f"💧 浇水成功！这个树枝已经被浇了 {votes} 次水~", show_alert=False)
    else:
        votes = db.get_votes(channel)
        await query.answer(f"你已经浇过水了哦~ 这个树枝已经被浇了 {votes} 次水~", show_alert=False)


async def treehole_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the 树洞 button press — initiate anonymous messaging."""
    query = update.callback_query
    data = query.data

    if not data.startswith("th:"):
        return

    channel = data[3:]
    user_id = query.from_user.id

    logger.info(f"🕳️ Tree hole from {user_id} {query.from_user.username or ''} for {channel}")

    # Check rate limit
    last_time = treehole_rate_limit.get(user_id, 0)
    if time.time() - last_time < TREEHOLE_COOLDOWN:
        remaining = int(TREEHOLE_COOLDOWN - (time.time() - last_time))
        return await query.answer(f"发送太频繁了，请 {remaining} 秒后再试~", show_alert=True)

    # Check if blocked
    if db.is_blocked(user_id, channel):
        return await query.answer("你已经被这个频道的主人屏蔽了哦~", show_alert=True)

    # Check if channel has an owner
    owner_id = db.get_channel_owner(channel)
    if not owner_id:
        return await query.answer("这个频道还没有设置主人哦~", show_alert=False)

    # Try to DM the user
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"🕳️ 树洞模式\n\n想对频道 @{channel} 的主人说什么呢？（发送文字消息即可，消息将会匿名发送）"
        )
        user_states[user_id] = {"action": "treehole", "channel": channel}
        await query.answer("请查看 bot 的私聊~", show_alert=False)
    except Exception:
        await query.answer("请先私聊 bot 发送 /start 才能使用树洞功能哦~", show_alert=True)


async def reply_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the channel owner clicking reply to a tree hole message."""
    query = update.callback_query
    data = query.data

    # Format: reply:{sender_id}:{channel}
    parts = data.split(":", 2)
    if len(parts) != 3:
        return

    _, sender_id_str, channel = parts
    sender_id = int(sender_id_str)
    owner_id = query.from_user.id

    # Verify the person clicking is the channel owner
    actual_owner = db.get_channel_owner(channel)
    if actual_owner != owner_id:
        return await query.answer("只有频道主人才能回复哦~", show_alert=False)

    user_states[owner_id] = {"action": "reply", "sender_id": sender_id, "channel": channel}
    await query.answer()
    await context.bot.send_message(
        chat_id=owner_id,
        text="💬 回复模式\n\n请输入你想回复的内容（发送文字消息即可）"
    )


async def block_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the channel owner clicking block on a tree hole message sender."""
    query = update.callback_query
    data = query.data

    # Format: block:{sender_id}:{channel}
    parts = data.split(":", 2)
    if len(parts) != 3:
        return

    _, sender_id_str, channel = parts
    sender_id = int(sender_id_str)
    owner_id = query.from_user.id

    # Verify the person clicking is the channel owner
    actual_owner = db.get_channel_owner(channel)
    if actual_owner != owner_id:
        return await query.answer("只有频道主人才能屏蔽哦~", show_alert=False)

    if db.block_user(sender_id, channel):
        await query.answer("✅ 已屏蔽该发送者", show_alert=True)
    else:
        await query.answer("该发送者已经被屏蔽了", show_alert=False)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages for tree hole composing and owner replies."""
    if update.message.chat.type != "private":
        return

    user_id = update.message.from_user.id
    state = user_states.get(user_id)

    if not state:
        return

    if state["action"] == "treehole":
        channel = state["channel"]
        del user_states[user_id]

        # Update rate limit
        treehole_rate_limit[user_id] = time.time()

        # Get channel owner
        owner_id = db.get_channel_owner(channel)
        if not owner_id:
            return await update.message.reply_text("这个频道还没有设置主人哦~")

        # Send to owner anonymously
        reply_btn = InlineKeyboardMarkup([
            [InlineKeyboardButton("💬 回复", callback_data=f"reply:{user_id}:{channel}")],
            [InlineKeyboardButton("🚫 屏蔽发送者", callback_data=f"block:{user_id}:{channel}")],
        ])

        try:
            await context.bot.send_message(
                chat_id=owner_id,
                text=f"🕳️ 树洞消息\n\n有人匿名对你的频道 @{channel} 说：\n\n{update.message.text}",
                reply_markup=reply_btn
            )
            await update.message.reply_text("✅ 消息已匿名发送~")
        except Exception:
            await update.message.reply_text("发送失败了... 频道主人可能还没有启用 bot")

    elif state["action"] == "reply":
        sender_id = state["sender_id"]
        channel = state["channel"]
        del user_states[user_id]

        try:
            await context.bot.send_message(
                chat_id=sender_id,
                text=f"💬 频道 @{channel} 的主人回复了你的树洞消息：\n\n{update.message.text}"
            )
            await update.message.reply_text("✅ 回复已发送~")
        except Exception:
            await update.message.reply_text("回复发送失败了...")


# Add handlers
bot.add_handler(CommandHandler("start", start))
bot.add_handler(CommandHandler("leaf", plant))
bot.add_handler(CallbackQueryHandler(water_callback, pattern=r"^water:"))
bot.add_handler(CallbackQueryHandler(treehole_callback, pattern=r"^th:"))
bot.add_handler(CallbackQueryHandler(reply_callback, pattern=r"^reply:"))
bot.add_handler(CallbackQueryHandler(block_callback, pattern=r"^block:"))
bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))


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


layout_html = (Path(__file__).parent / "public" / "layout.html").read_text()
fmt_html = lambda x: layout_html.replace("{{CONTENT}}", x).replace("\n", "")


@app.get("/c/{channel}", response_class=HTMLResponse)
def channel_info(channel: str):
    info = db.channel_info(channel)

    if not info:
        return fmt_html(f"""
            <h1>TGCN 频道树！</h1>
            <p>频道 @{channel} 不在树上哦~</p>
        """)

    leaf_txt = '树枝' if info.children else '树叶'

    return fmt_html(f"""
        <h1>TGCN 频道树！</h1>
        <p>这里是频道 <a href="https://t.me/{channel}">@{channel}</a> - {info.name}，{
            f'在频道树的第 {info.height + 1} 层，是 <a href="https://t.me/{info.parent}">@{info.parent}</a> (<a href="/c/{info.parent}">🔗</a>) 的{leaf_txt}哦~'
            if info.parent else "是树根哦~"
        }</p>
        {f"""<p>下面这些是这个频道的树枝：</p>
        <ul>
            {"".join(f'<li><a href="https://t.me/{child.username}">@{child.username}</a> (<a href="/c/{child.username}">🔗</a>) - {child.name}</li>' for child in info.children)}
        </ul>""" if info.children else "这个频道是树叶哦~"}
        <p class="note">（如果你也有公开频道，想成为这个频道的树叶的话，就去给 <a href="https://t.me/tgtreebot">@tgtreebot</a> 发送 <code>/leaf {channel} {{你的频道名}}</code> 吧! &gt; &lt;）</p>
    """)


app.mount("/", StaticFiles(directory="public", html=True))


if __name__ == '__main__':
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=9498)
