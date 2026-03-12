import re

from tqdm import tqdm

import db
from bot import channel_html


def exp1():
    pop = []
    r = re.compile(r"([\d ]+) subscribers")
    for channel in tqdm(db.Channel.select()):
        html = channel_html(channel.username)
        m = r.search(html)
        pop.append((channel.username, int(m.group(1).replace(" ", "")) if m else 0))

    pop.sort(key=lambda x: x[1], reverse=True)
    for channel, subscribers in pop:
        print(f"{channel} - {subscribers}")


def exp2(name):
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


def exp3():
    # Find the channel with the most leafs and the channel with the most non-leafs
    most_leafs = None
    most_non_leafs = None
    most_leafs_count = 0
    most_non_leafs_count = 0

    for channel in tqdm(db.Channel.select()):
        if channel.height == 0:
            continue
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

    print(f"Most Leafs: {most_leafs.username} - {most_leafs_count}")
    print(f"Most Non Leafs: {most_non_leafs.username} - {most_non_leafs_count}")


if __name__ == '__main__':
    # exp1()

    # exp2("XLDFDZ")
    # exp2("Billchenla")

    exp3()



