import time
from pathlib import Path

from hypy_utils import write

import db


src = Path(__file__).parent


def indent(string: str, level: int):
    # Indent each line by level spaces
    return "\n".join(" " * level + line for line in string.split("\n"))


def dfs(channel: str):
    info = db.channel_info(channel)
    out = f"""<span class="tree l{info.height}"><a href="https://t.me/{channel}">@{channel}</a> - {info.name}</span>\n"""
    if not info.children:
        return out

    out += f"""<div class="container l{info.height}">\n"""
    for child in info.children:
        out += indent(dfs(child.username), 2)
    out += f"""</div>\n"""
    return out


def gen_tree():
    of = dfs("hykilp")
    write(src / "public/index.html", (src / "public/layout-full-tree.html").read_text()
          .replace("{{CONTENT}}", of))


if __name__ == '__main__':
    while True:
        print("Generating tree...")
        gen_tree()
        print("Done! Sleeping for 60 seconds...")
        time.sleep(60)
