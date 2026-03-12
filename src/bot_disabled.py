from telegram import Update
from telegram.ext import CommandHandler, Application, ContextTypes

from utils import CONFIG


async def disabled(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type != "private":
        return

    await update.message.reply_text("""
植树节活动结束了哦，感谢大家一起种树！

为了防止被滥用，频道树现在是只读的，不能再添加新的频道了。

最终的频道树在这里 qwq
https://tree.aza.moe
""".strip())


if __name__ == '__main__':
    BOT_TOKEN = CONFIG["token"]

    bot = Application.builder().token(BOT_TOKEN).build()

    # Add handlers
    bot.add_handler(CommandHandler("start", disabled))
    bot.add_handler(CommandHandler("leaf", disabled))

    bot.run_polling()
