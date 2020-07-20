from cmdClient.Check import check
from cmdClient.checks import in_guild


@check(
    name="HAS_MANAGE_GUILD",
    msg="You need the `MANAGE_GUILD` permission to use this command!",
    requires=[in_guild]
)
async def has_manage_guild(ctx, *args, **kwargs):
    return ctx.ch.permissions_for(ctx.author).manage_guild


@check(
    name="REGISTERED_GUILD",
    msg="The guild needs to be registered using the `setup` command first!",
    requires=[in_guild]
)
async def registered_guild(ctx, *args, **kwargs):
    return ctx.guild.id in ctx.client.tickets.guilds


@check(
    name="IS_MODERATOR",
    msg="You need to be a moderator to use this command!",
    requires=[registered_guild]
)
async def is_moderator(ctx, *args, **kwargs):
    manage_guild = ctx.ch.permissions_for(ctx.author).manage_guild
    staffrole_id = ctx.client.tickets.guilds[ctx.guild.id].staffrole_id
    return manage_guild or staffrole_id in [r.id for r in ctx.author.roles]
