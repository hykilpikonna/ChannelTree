import time
from pathlib import Path

from hypy_utils import write

import db


src = Path(__file__).parent.parent


def indent(string: str, level: int):
    # Indent each line by level spaces
    return "\n".join(" " * level + line for line in string.split("\n"))


def dfs(channel: str, admin: bool = False):
    info = db.channel_info(channel)
    if not info or (info.hidden and not admin):
        return ""

    votes = db.get_votes(channel)
    water = f' 💧{votes}' if votes else ''
    
    # In admin mode, show hidden status and a hide button
    hide_icon = "👁️" if info.hidden else "🚫"
    admin_info = f' <span style="opacity:0.5;">[HIDDEN]</span>' if info.hidden else ''
    hide_btn = f' <button onclick="adminHide(\'{channel}\', {str(not info.hidden).lower()})" title="Hide/Show" style="background:none;border:none;cursor:pointer;font-size:0.8em;opacity:0.6;">{hide_icon}</button>' if admin else ''
    del_btn = f' <button onclick="adminDelete(\'{channel}\')" title="Delete" style="background:none;border:none;cursor:pointer;font-size:0.8em;opacity:0.6;">🗑️</button>' if admin else ''
    
    out = (f"""<span class="tree l{info.height}"><a href="https://t.me/{channel}">@{channel}</a> - {info.name}{water}{admin_info}{hide_btn}{del_btn}</span>\n""")
    
    if not info.children:
        return out

    out += f"""<div class="container l{info.height}">\n"""
    for child in info.children:
        child_out = dfs(child.username, admin)
        if child_out:
            out += indent(child_out, 2)
    out += f"""</div>\n"""
    return out


def gen_tree(d: Path = src / "public"):
    # Generate public index.html
    of = dfs("azaneko", admin=False)
    write(d / "index.html", (src / "public/layout-full-tree.html").read_text('utf-8')
          .replace("{{CONTENT}}", of))

    # Generate admin.html
    of_admin = dfs("azaneko", admin=True)
    admin_layout = (src / "public/layout-full-tree.html").read_text('utf-8')
    admin_script = """
    <script>
    async function adminHide(username, hide) {
        const pw = prompt(`请输入管理员密码以${hide ? '隐藏' : '显示'} @${username}:`);
        if (!pw) return;

        try {
            const res = await fetch(`/api/admin/channels/${username}/hide`, {
                method: 'POST',
                headers: { 
                    'X-Admin-Password': pw,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ hidden: hide })
            });

            if (res.status === 403) {
                alert('密码不对哦');
            } else if (res.ok) {
                alert('操作成功！');
                location.reload();
            } else {
                const err = await res.json();
                alert(`出错啦: ${err.detail || '未知错误'}`);
            }
        } catch (e) {
            alert(`请求失败: ${e.message}`);
        }
    }

    async function adminDelete(username) {
        const pw = prompt(`请输入管理员密码以移除 @${username}:`);
        if (!pw) return;

        if (!confirm(`确定要移除 @${username} 吗？\\n\\n警告：这会同时移除它的所有子频道！`)) return;

        try {
            const res = await fetch(`/api/admin/channels/${username}`, {
                method: 'DELETE',
                headers: { 'X-Admin-Password': pw }
            });

            if (res.status === 403) {
                alert('密码不对哦');
            } else if (res.ok) {
                alert('移除成功！');
                location.reload();
            } else {
                const err = await res.json();
                alert(`出错啦: ${err.detail || '未知错误'}`);
            }
        } catch (e) {
            alert(`请求失败: ${e.message}`);
        }
    }
    </script>
    """
    write(d / "admin.html", admin_layout.replace("{{CONTENT}}", of_admin).replace("</body>", admin_script + "</body>"))


if __name__ == '__main__':
    while True:
        print("Generating tree...")
        gen_tree()
        print("Done! Sleeping for 10 seconds...")
        time.sleep(10)
