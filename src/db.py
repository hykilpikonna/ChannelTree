from peewee import Model, CharField, ForeignKeyField, IntegerField, BigIntegerField, BooleanField, CompositeKey, PostgresqlDatabase

from utils import CONFIG

# Database configuration
db = PostgresqlDatabase('tgtree', user='cat',
                        password=CONFIG["db-pass"], host=CONFIG["db-host"], port=CONFIG["db-port"])


class BaseModel(Model):
    class Meta:
        database = db


class Channel(BaseModel):
    username = CharField(primary_key=True)  # Unique username as primary key
    name = CharField()  # Channel name
    parent = ForeignKeyField('self', null=True, backref='children', on_delete='CASCADE', field='username')
    height = IntegerField(default=0)  # Tree height (depth)
    owner_id = BigIntegerField(null=True)  # Telegram user ID of the channel owner
    hidden = BooleanField(default=False)  # Whether the channel is hidden from the tree


class Vote(BaseModel):
    user_id = BigIntegerField()  # Telegram user ID
    channel = ForeignKeyField(Channel, backref='votes', on_delete='CASCADE', field='username')

    class Meta:
        primary_key = CompositeKey('user_id', 'channel')


class Block(BaseModel):
    user_id = BigIntegerField()  # Blocked Telegram user ID
    channel = ForeignKeyField(Channel, backref='blocks', on_delete='CASCADE', field='username')

    class Meta:
        primary_key = CompositeKey('user_id', 'channel')


class OwnerPref(BaseModel):
    user_id = BigIntegerField(primary_key=True)  # Owner's Telegram user ID
    treehole_optout = BooleanField(default=False)  # Whether the owner opted out of tree hole messages
    treehole_notified = BooleanField(default=False)  # Whether the owner has been sent the intro notice


class TreeholeMsg(BaseModel):
    """Stores metadata for treehole messages so callback data doesn't expose user IDs."""
    sender_id = BigIntegerField()  # The anonymous sender's Telegram user ID
    channel = ForeignKeyField(Channel, backref='treehole_msgs', on_delete='CASCADE', field='username')


with db:
    db.create_tables([Channel, Vote, Block, OwnerPref, TreeholeMsg])


def channel_info(username: str) -> Channel | None:
    """Fetch channel information using the username as an identifier."""
    try:
        return Channel.get(Channel.username == username)
    except Channel.DoesNotExist:
        return None


def remove_channel(username: str) -> bool:
    """Remove a channel and its descendants (via CASCADE)."""
    try:
        ch = Channel.get(Channel.username == username)
        ch.delete_instance(recursive=True)
        return True
    except Channel.DoesNotExist:
        return False


def set_hidden(username: str, hidden: bool) -> bool:
    """Toggle the hidden status of a channel."""
    try:
        ch = Channel.get(Channel.username == username)
        ch.hidden = hidden
        ch.save()
        return True
    except Channel.DoesNotExist:
        return False


def get_all_channels(include_hidden: bool = True) -> list[Channel]:
    """Get all registered channels."""
    query = Channel.select()
    if not include_hidden:
        query = query.where(Channel.hidden == False)
    return list(query.order_by(Channel.height, Channel.username))


def register(username: str, name: str, parent_username: str = None, owner_id: int = None):
    """Register a channel using its username and assign the correct height."""
    if parent_username:
        try:
            parent = Channel.get(Channel.username == parent_username)
            height = parent.height + 1  # Child height is parent's height + 1
        except Channel.DoesNotExist:
            raise ValueError("Parent channel does not exist.")
    else:
        parent = None
        height = 0  # Root nodes have height 0

    Channel.create(username=username, name=name, parent=parent, height=height, owner_id=owner_id)
    return height


def add_vote(user_id: int, channel_username: str) -> bool:
    """Add a vote for a channel. Returns True if the vote was added, False if already voted."""
    try:
        Vote.create(user_id=user_id, channel=channel_username)
        return True
    except Exception:
        return False


def get_votes(channel_username: str) -> int:
    """Get the total number of votes for a channel."""
    return Vote.select().where(Vote.channel == channel_username).count()


def has_voted(user_id: int, channel_username: str) -> bool:
    """Check if a user has already voted for a channel."""
    return Vote.select().where(
        (Vote.user_id == user_id) & (Vote.channel == channel_username)
    ).exists()


def get_channel_owner(channel_username: str) -> int | None:
    """Get the owner's Telegram user ID for a channel."""
    try:
        ch = Channel.get(Channel.username == channel_username)
        return ch.owner_id
    except Channel.DoesNotExist:
        return None


def block_user(user_id: int, channel_username: str) -> bool:
    """Block a user from sending tree hole messages to a channel. Returns True if newly blocked."""
    try:
        Block.create(user_id=user_id, channel=channel_username)
        return True
    except Exception:
        return False


def is_blocked(user_id: int, channel_username: str) -> bool:
    """Check if a user is blocked from sending tree hole messages to a channel."""
    return Block.select().where(
        (Block.user_id == user_id) & (Block.channel == channel_username)
    ).exists()


def create_treehole_msg(sender_id: int, channel_username: str) -> int:
    """Create a treehole message record and return its numeric ID."""
    msg = TreeholeMsg.create(sender_id=sender_id, channel=channel_username)
    return msg.id


def get_treehole_msg(msg_id: int) -> TreeholeMsg | None:
    """Look up a treehole message by its ID."""
    try:
        return TreeholeMsg.get_by_id(msg_id)
    except TreeholeMsg.DoesNotExist:
        return None


def is_treehole_opted_out(owner_id: int) -> bool:
    """Check if an owner has opted out of receiving tree hole messages."""
    try:
        pref = OwnerPref.get(OwnerPref.user_id == owner_id)
        return pref.treehole_optout
    except OwnerPref.DoesNotExist:
        return False


def set_treehole_optout(owner_id: int, opted_out: bool):
    """Set whether an owner has opted out of tree hole messages."""
    pref, _ = OwnerPref.get_or_create(user_id=owner_id)
    pref.treehole_optout = opted_out
    pref.save()


def is_treehole_notified(owner_id: int) -> bool:
    """Check if the owner has received the first-time tree hole intro notice."""
    try:
        pref = OwnerPref.get(OwnerPref.user_id == owner_id)
        return pref.treehole_notified
    except OwnerPref.DoesNotExist:
        return False


def set_treehole_notified(owner_id: int):
    """Mark the owner as having received the tree hole intro notice."""
    pref, _ = OwnerPref.get_or_create(user_id=owner_id)
    pref.treehole_notified = True
    pref.save()


if __name__ == '__main__':
    with db:
        # db.drop_tables([Channel])
        db.create_tables([Channel])

    register('hykilp', '小桂桂的回忆录 📒')

    # Test the register function
    print(register('test', 'Test Channel'))
    print(register('test2', 'Test Channel 2', 'test'))
    print(register('test3', 'Test Channel 3', 'test2'))

    # Test the channel_info function
    print(channel_info('test'))
    print(channel_info('test2'))
    print(channel_info('test3'))
    print(channel_info('nonexistent'))