import hashlib
import re
import tomllib
from pathlib import Path
from typing import NamedTuple


CONFIG = tomllib.loads((Path(__file__).parent / "config.toml").read_text())


def gen_sha(channel: str, uid: int, parent: str):
    # 生成验证码
    sha = hashlib.sha1()
    sha.update(f"{channel}/{uid}/{parent}".encode())
    return sha.hexdigest()[:6]


class PageMeta(NamedTuple):
    title: str
    description: str


def extract_meta_tags(html):
    title_pattern = re.search(r'<meta property="og:title" content="(.*?)">', html)
    description_pattern = re.search(r'<meta property="og:description" content="(.*?)">', html)

    title = title_pattern.group(1) if title_pattern else None
    description = description_pattern.group(1) if description_pattern else None

    return PageMeta(title, description)
