import shutil
from pathlib import Path

from hypy_utils import write

import bot
import db
import gentree

src = Path(__file__).parent

if __name__ == '__main__':
    # Delete dist if already exists, and copy public to dist
    shutil.rmtree(src / "dist", ignore_errors=True)
    shutil.copytree(src / "public", src / "dist")

    # Pre-render all channel info
    for channel in db.Channel.select():
        html = bot.channel_info(channel.username)
        write(src / f"dist/c/{channel.username}.html", html)

    # Generate the full tree
    gentree.gen_tree(src / "dist")

