import re

from tqdm import tqdm

import db
from bot import channel_html


def totals():
    total_channels = db.Channel.select().where(db.Channel.hidden == False).count()
    print(f'总频道数量: {total_channels}')


def get_tallest():
    tallest = db.Channel.select().where(db.Channel.hidden == False).order_by(db.Channel.height.desc()).first()
    equally_tall = db.Channel.select().where((db.Channel.height == tallest.height) & (db.Channel.hidden == False))
    for ch in equally_tall:
        print(f'高度最高: {ch.username} - {ch.height}')


def get_most_subscribed():
    chans = []
    groups = []
    bots = []
    people = []
    r_chan = re.compile(r"([\d ]+) subscribers")
    r_grp = re.compile(r"([\d ]+) members")
    # Select non-hidden channels
    for entity in tqdm(db.Channel.select().where(db.Channel.hidden == False)):
        html = channel_html(entity.username)
        if m := r_chan.search(html):
            chans.append((
                entity.username,
                int(m.group(1).replace(" ", "")),
                db.get_votes(entity.username),
                entity.name
            ))
        elif m := r_grp.search(html):
            groups.append((entity.username, int(m.group(1).replace(" ", "")), db.get_votes(entity.username), entity.name))
        elif "Start Bot" in html and entity.username.endswith("bot"):
            bots.append((entity.username, 0, db.get_votes(entity.username), entity.name))
        elif "Send Message" in html:
            people.append((entity.username, 0, db.get_votes(entity.username), entity.name))

    chans.sort(key=lambda x: x[1], reverse=True)
    print(f'订阅者最多: {chans[0][0]} - {chans[0][1]}')
    chans.sort(key=lambda x: x[2], reverse=True)
    print(f'水最多: {chans[0][0]} - {chans[0][2]}')
    chans.sort(key=lambda x: len(x[0]), reverse=True)
    print(f'最长频道: {chans[0][0]} - {len(chans[0][0])} characters')
    chans.sort(key=lambda x: len(x[3]), reverse=True)
    print(f'最长名字: {chans[0][0]} ({chans[0][3]}) - {len(chans[0][3])} characters')

    print(f'总群数量: {len(groups)}')
    groups.sort(key=lambda x: x[1], reverse=True)
    print(f'群成员最多: {groups[0][0]} - {groups[0][1]}')
    groups.sort(key=lambda x: x[2], reverse=True)
    print(f'群水最多: {groups[0][0]} - {groups[0][2]}')

    print(f'总机器人数量: {len(bots)}')

    print(f'总个人账户数量: {len(people)}')


def leaf_and_non_leaf_count(name):
    # Count leaf and nodes in children (leaf is a channel without children)
    xl = db.channel_info(name)
    leaf_count = 0
    node_count = 0
    for child in xl.children:
        if child.children:
            node_count += 1
        else:
            leaf_count += 1
    print(f"Leaf: {leaf_count}, Node: {node_count}")


def get_most_leafs():
    # Find the channel with the most leafs and the channel with the most non-leafs
    most_leafs = None
    most_non_leafs = None
    most_leafs_count = 0
    most_non_leafs_count = 0
    total_leaf_count = 0
    total_non_leaf_count = 0

    for channel in tqdm(db.Channel.select().where(db.Channel.hidden == False)):
        if channel.height == 0:
            continue

        if channel.children:
            total_leaf_count += 1
        else:
            total_non_leaf_count += 1

        leaf_count = 0
        non_leaf_count = 0
        for child in channel.children:
            if child.children:
                non_leaf_count += 1
            else:
                leaf_count += 1

        if leaf_count > most_leafs_count:
            most_leafs = channel
            most_leafs_count = leaf_count

        if non_leaf_count > most_non_leafs_count:
            most_non_leafs = channel
            most_non_leafs_count = non_leaf_count

    print(f"最多树叶: {most_leafs.username}")
    leaf_and_non_leaf_count(most_leafs.username)
    print(f"最多树枝: {most_non_leafs.username}")
    leaf_and_non_leaf_count(most_non_leafs.username)
    print(f"总树叶数量: {total_leaf_count}")
    print(f"总树枝数量: {total_non_leaf_count}")


def rank_by_centrality(mode="closeness"):
    nodes = list(db.Channel.select().where(db.Channel.hidden == False))
    adj = {n.username: [] for n in nodes}
    for n in nodes:
        if n.parent_id and n.parent_id in adj:
            adj[n.username].append(n.parent_id)
            adj[n.parent_id].append(n.username)

    if mode == "closeness":
        scores = []
        for start in tqdm(adj.keys(), desc="Closeness Centrality"):
            visited = {start: 0}
            queue = [start]
            head = 0
            while head < len(queue):
                curr = queue[head]
                head += 1
                dist = visited[curr]
                for nxt in adj[curr]:
                    if nxt not in visited:
                        visited[nxt] = dist + 1
                        queue.append(nxt)
            if len(visited) > 1:
                avg_len = sum(visited.values()) / (len(visited) - 1)
                scores.append((start, avg_len, len(visited)))
        scores.sort(key=lambda x: x[1])
        print(f"\n--- Top Closeness Centrality (smaller better) ---")
        for i, (u, score, reachable) in enumerate(scores[:10]):
            print(f"{i+1}. {u}: {score:.4f}")

    elif mode == "betweenness":
        betweenness = {u: 0 for u in adj}
        
        # Calculate total paths in the graph (sum of paths in each connected component)
        total_paths = 0
        visited_global = set()
        for start in adj:
            if start not in visited_global:
                q = [start]
                visited_global.add(start)
                comp_size = 0
                while q:
                    curr = q.pop(0)
                    comp_size += 1
                    for nxt in adj[curr]:
                        if nxt not in visited_global:
                            visited_global.add(nxt)
                            q.append(nxt)
                total_paths += comp_size * (comp_size - 1) // 2

        for start in tqdm(adj.keys(), desc="Betweenness Centrality"):
            visited = {start}
            queue = [start]
            head = 0
            parents = {start: None}
            order = []
            while head < len(queue):
                curr = queue[head]
                order.append(curr)
                head += 1
                for nxt in adj[curr]:
                    if nxt not in visited:
                        visited.add(nxt)
                        parents[nxt] = curr
                        queue.append(nxt)
            
            subtree_size = {u: 1 for u in order}
            for u in reversed(order):
                p = parents[u]
                if p is not None:
                    subtree_size[p] += subtree_size[u]
                if p is not None and p != start:
                    betweenness[p] += subtree_size[u]

        for u in betweenness:
            betweenness[u] //= 2
            
        scores = [(u, betweenness[u]) for u in betweenness]
        scores.sort(key=lambda x: x[1], reverse=True)
        print(f"\n--- Top Betweenness Centrality (larger better) ---")
        for i, (u, score) in enumerate(scores[:10]):
            pct = (score / total_paths * 100) if total_paths > 0 else 0
            print(f"{i+1}. {u}: {score} ({pct:.3f}%)")


if __name__ == '__main__':
    totals()
    get_tallest()
    get_most_subscribed()
    get_most_leafs()

    rank_by_centrality("closeness")
    rank_by_centrality("betweenness")
