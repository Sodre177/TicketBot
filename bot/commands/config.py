from cmdClient import cmd
from cmdClient.lib import UserCancelled, ResponseTimedOut

from utils.seekers import find_role, find_channel  # noqa
from utils.interactive import input  # noqa
from utils.ctx_addons import embedreply  # noqa

from wards import has_manage_guild, registered_guild

"""
Commands:
    config:
        setup - Setup and initialise a server, prompt for staffrole, etc
        addrole - Add a tracked role
        rmrole - Deactivate a tracked role
        importbans - import current ban list as resolved tickets
"""


@cmd("setup",
     group="Configuration",
     desc="Register the guild with TicketBot.",
     aliases=["register"])
@has_manage_guild()
async def cmd_setup(ctx):
    """
    Usage``:
        setup
    Description:
        Set up the current guild for use with TicketBot.
        This will prompt for the staffrole
        and the modlog channel.
        Most commands will required the guild to have been set up.

        This command requires the `manage_guild` permission.
    Related:
        addrole, rmrole
    """
    # Prompt the user for the staff role and the modlog channel
    staffrole = None
    modlog = None
    try:
        while staffrole is None:
            response = await ctx.input(
                "Please enter the staff role.\n"
                "This role is used for access to the ticket and history commands, "
                "specifically `ticket`, `tickethistory`, `userlog`, `setreason`, "
                "`changemod` and `claim`.\n"
                "This role does not allow adding or removing tracked roles, or registering the guild.\n"
                "(Accepted input: rolename, roleid, or rolemention.)"
            )
            staffrole = await ctx.find_role(response, interactive=True)

        while modlog is None:
            response = await ctx.input(
                "Please enter the modlog channel.\n"
                "I will use this channel to post moderation tickets "
                "each time a tracked moderation action (kick, (un)ban, or tracked role modification) occurs.\n"
                "Please ensure I have message posting and embed link permissions in this channel.\n"
                "(Accepted input: channelname, channelid, or channelmention.)"
            )
            modlog = await ctx.find_channel(response, interactive=True)
            # TODO: Check permissions on this channel
    except UserCancelled:
        return await ctx.error_reply(
            "User cancelled.\n"
            "The guild has not been registered."
        )
    except ResponseTimedOut:
        return await ctx.error_reply(
            "Timed out waiting for a response.\n"
            "The guild has not been registered."
        )

    # Register the guild
    ctx.client.tickets.register_guild(ctx.guild.id, staffrole.id, modlog.id)
    await ctx.embedreply(
        "The guild has been successfully set up for use with TicketBot.\n"
        "I will now create tickets when tracked moderation events are detected, "
        "and remind the responsible moderators to set reasons.\n"
        "To add roles where the addition or removal of the roles is considered "
        "a moderation event, see the command `addrole`."
    )


# TODO: Note, maybe add an "autoresolved" type of role which doesn't need a reason?
@cmd("addrole",
     group="Configuration",
     desc="Add a tracked role.",
     aliases=["trackrole"])
@has_manage_guild()
@registered_guild()
async def cmd_addrole(ctx):
    """
    Usage``:
        addrole
        addrole <role>, <add_action_name>, <rm_action_name>
    Description:
        Mark a guild role as "tracked", so that adding or removing
        this role is counted as a moderation action,
        and will generate a ticket and prompt for a reason.

        This command may be used without arguments, in which case
        it will prompt for the required information.

        Requires the `MANAGE_GUILD` permission,
        and for the guild to have been registered.
    Parameters::
        role: The role to be tracked. May be a rolename, roleid, or mention.
        add_action_name: The action name to be used when the role is added, e.g. `MUTED`.
        rm_action_name: The action name to be used when the role is removed, e.g. `UNMUTED`.
    Related:
        setup, rmrole
    Examples``:
        addrole muted, MUTED, UNMUTED
        addrole staff, PROMOTED, DEMOTED
        addrole warned, WARNED, UNWARNED
    """
    role = None
    add_action_name = None
    rm_action_name = None

    # Obtain the role information
    try:
        if ctx.arg_str:
            # Extract the role information from the arguments
            splits = ctx.arg_str.split(",")
            if len(splits) != 3:
                return await ctx.error_reply(
                    "**USAGE:**\n"
                    "`addrole`\n"
                    "`addrole <role>, <add_action_name>, <rm_action_name>`\n\n"
                    "See the command help for more information."
                )
            rolestr, add_action_name, rm_action_name = [s.strip() for s in splits]
            role = await ctx.find_role(rolestr, interactive=True)
            if role is None:
                return
        else:
            # Prompt for the role information
            while role is None:
                response = await ctx.input(
                    "Please enter the role to track.\n"
                    "Whenever this role is added or removed from a member, "
                    "a ticket will be created, and the responsible actor will "
                    "be asked for the reason.\n"
                    "(Accepted input: rolename, roleid, or rolemention.)"
                )
                role = await ctx.find_role(response, interactive=True)
            add_action_name = await ctx.input(
                "Please enter the name of the action associated to adding the role.\n"
                "For example, if the role is a mute role, this might be `MUTED`. "
                "Alternatively, if the roled is a staff role, this might be `PROMOTED`."
            )
            rm_action_name = await ctx.input(
                "Please enter the name of the action associated to removing the role.\n"
                "In the case of a mute role, this might be `UNMUTED`, "
                "and for a staff role this could be `DEMOTED`."
            )
    except UserCancelled:
        return await ctx.error_reply(
            "User cancelled.\n"
            "No tracked role has been created."
        )
    except ResponseTimedOut:
        return await ctx.error_reply(
            "Timed out waiting for a response.\n"
            "No tracked role has been created."
        )

    # Add the tracked role
    ctx.client.tickets.create_active_role(
        ctx.guild.id,
        role.id,
        add_action_name,
        rm_action_name
    )

    await ctx.embedreply(
        "The role {} was successfully registered as a tracked role!".format(role.mention)
    )


@cmd("rmrole",
     group="Configuration",
     desc="Remove a tracked role.")
@has_manage_guild()
@registered_guild()
async def cmd_rmrole(ctx):
    """
    Usage``:
        rmrole <role>
    Description:
        Remove a currently tracked role,
        so that additions and removals no longer count as moderation actions.

        Requires the `MANAGE_GUILD` permission,
        and for the guild to have been registered.
    Parameters::
        role: The role. May be a rolename, roleid, or mention.
    Related:
        setup, addrole
    """
    role_id = None
    role = None
    if not ctx.arg_str:
        return await ctx.error_reply("**USAGE:** `rmrole <role>`")
    elif ctx.arg_str.isdigit():
        role_id = int(ctx.arg_str)
    else:
        try:
            role = await ctx.find_role(ctx.arg_str, interactive=True)
        except UserCancelled:
            return await ctx.error_reply("User cancelled. Tracked roles were not updated.")
        except ResponseTimedOut:
            return await ctx.error_reply("Query timed out. Tracked roles were not updated.")

        if role is None:
            return
        role_id = role.id

    if role_id not in ctx.client.tickets.guilds[ctx.guild_id].active_roles:
        return await ctx.error_reply(
            "This role is not being tracked!"
        )

    ctx.client.tickets.deactivate_role(ctx.guild.id, role_id)

    await ctx.embedreply(
        "The role {} is no longer being tracked.".format(
            role.mention if role else "`{}`".format(role_id)
        )
    )


@cmd("importallbans",
     group="Configuration",
     desc="Import all past bans.")
@has_manage_guild()
@registered_guild()
async def cmd_importallbans(ctx):
    """
    Usage``:
        importallbans
    Description:
        Imports all the current bans in the guild as resolved tickets.
        ***Only use this command once.***

        Requires the `MANAGE_GUILD` permission,
        and for the guild to have been registered.
    """
    bans = await ctx.guild.bans()

    for ban in bans:
        user = ban.user,
        reason = ban.reason
        await ctx.client.tickets.create_ticket(
            ctx.guild.id,
            ctx.client.tickets.ActionTypes.BAN,
            0,
            user.id,
            resolved=True,
            reason=reason
        )

    await ctx.reply("Loaded `{}` tickets from the ban list.".format(len(bans)))
