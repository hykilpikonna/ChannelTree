from peewee import Model, CharField, ForeignKeyField, IntegerField, PostgresqlDatabase

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


with db:
    db.create_tables([Channel])


def channel_info(username: str) -> Channel | None:
    """Fetch channel information using the username as an identifier."""
    try:
        return Channel.get(Channel.username == username)
    except Channel.DoesNotExist:
        return None


def register(username: str, name: str, parent_username: str = None):
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

    Channel.create(username=username, name=name, parent=parent, height=height)
    return height


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