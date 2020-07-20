from cmdClient import cmd
from cmdClient.lib import UserCancelled, ResponseTimedOut

from utils.seekers import find_member # noqa
from utils.interactive import input  # noqa

from wards import is_moderator

"""
Commands:
    tickets:
        show - Show a ticket with a given number
        setreason - Set the reason for a specified ticket
        setmod - set the mod for a specified ticket
        claim - claim as specified ticket as your own case
"""


@cmd("show",
     group="Tickets",
     desc="Display the given ticket.",
     aliases=["showticket"])
@is_moderator()
async def cmd_show(ctx):
    """
    Usage``:
        show <ticket#>
    Description:
        Display the ticket with the given number for this guild.

        This requires you to be a guild moderator (i.e. have the staff role or `manage_guild`).
    Parameters::
        ticket#: The number of the ticket you wish to view.
    Related:
        tickethistory, userlog
    Example``:
        show 1
    """
    # Check the ticket number is provided and sane
    if not ctx.arg_str or not ctx.arg_str.isdigit():
        return await ctx.error_reply(
            "**USAGE:** `show <ticket#>`"
        )
    ticket_num = int(ctx.arg_str)
    if ticket_num > ctx.client.tickets.guilds[ctx.guild.id].ticket_count:
        return await ctx.error_reply(
            "Ticket `{}` doesn't yet exist!".format(ticket_num)
        )

    # Retrieve the ticket
    ticket = ctx.client.tickets.get_ticket(ctx.guild.id, ticket_num)

    # Display the ticket
    await ctx.reply(embed=ticket.embed)


@cmd("setreason",
     group="Tickets",
     desc="Set the reason for the specified ticket(s).",
     aliases=["reason"])
@is_moderator()
async def cmd_setreason(ctx):
    """
    Usage``:
        setreason <ticket#>; <reason>
        setreason <ticket#>, <ticket#>, <ticket#>...; <reason>
    Description:
        Sets the given reason for all the specified tickets.

        This requires you to be a guild moderator (i.e. have the staff role or `manage_guild`).
    Parameters::
        ticket#: The number of the ticket you wish to set the reason for.
        reason: A non-empty reason for the specified tickets.
    Related:
        show, changemod, tickethistory, userlog
    Examples``:
        setreason 1; Said naughty words.
        setreason 1,2,3,4; Raiding.
    """
    usage_str = (
        "**USAGE:**\n"
        "`setreason <ticket#>; <reason>`\n"
        "`setreason <ticket#>, <ticket#>, <ticket#>...; <reason>`"
    )
    if ';' not in ctx.arg_str:
        return await ctx.error_reply(usage_str)

    ticketstr, reason = ctx.arg_str.split(';')
    reason = reason.strip()
    tstrs = [tstr.strip() for tstr in ticketstr.split(',')]

    if not ticketstr or not reason or not all(tstr.isdigit() for tstr in tstrs):
        return await ctx.error_reply(usage_str)

    tickets = [int(tstr) for tstr in tstrs]
    max_ticket = ctx.client.tickets.guilds[ctx.guild.id].ticket_count
    dud_ticket = next((ticket for ticket in tickets if ticket > max_ticket), None)
    if dud_ticket is not None:
        return await ctx.error_reply(
            "Ticket `{}` doesn't yet exist!".format(dud_ticket)
        )

    for ticket in tickets:
        await ctx.client.tickets.get_ticket(ctx.guild.id, ticket).update_reason(
            ctx.author.id,
            reason
        )

    await ctx.reply("`{}` tickets have been updated!".format(len(tickets)))


@cmd("changemod",
     group="Tickets",
     desc="Change the moderator assigned to the specified ticket(s).",
     aliases=["setmod"])
@is_moderator()
async def cmd_changemod(ctx):
    """
    Usage``:
        changemod <ticket#>; <newmod>
        changemod <ticket#>, <ticket#>, <ticket#>...; <newmod>
    Description:
        Changes the assigned moderator for all the specified tickets.

        This requires you to be a guild moderator (i.e. have the staff role or `manage_guild`).
    Parameters::
        ticket#: The number of the ticket you wish to change the moderator for.
        newmod: The new moderator. May be a mention, id or name.
    Related:
        show, claim, setreason, tickethistory, userlog
    Examples``:
        changemod 1; Bob
        changemod 1,2,3,4; Bob
    """
    usage_str = (
        "**USAGE:**\n"
        "`changemod <ticket#>; <newmod>`\n"
        "`changemod <ticket#>, <ticket#>, <ticket#>...; <newmod>`"
    )
    if ';' not in ctx.arg_str:
        return await ctx.error_reply(usage_str)

    ticketstr, newmodstr = ctx.arg_str.split(';')
    tstrs = [tstr.strip() for tstr in ticketstr.split(',')]

    if not ticketstr or not newmodstr or not all(tstr.isdigit() for tstr in tstrs):
        return await ctx.error_reply(usage_str)

    tickets = [int(tstr) for tstr in tstrs]
    max_ticket = ctx.client.tickets.guilds[ctx.guild.id].ticket_count
    dud_ticket = next((ticket for ticket in tickets if ticket > max_ticket), None)
    if dud_ticket is not None:
        return await ctx.error_reply(
            "Ticket `{}` doesn't yet exist!".format(dud_ticket)
        )
    try:
        newmod = await ctx.find_member(newmodstr, interactive=True)
    except UserCancelled:
        return await ctx.error_reply(
            "User cancelled moderator selection. Tickets were not updated."
        )
    except ResponseTimedOut:
        return await ctx.error_reply(
            "Moderator selection timed out. Tickets were not updated."
        )

    if newmod is None:
        return await ctx.error_reply(
            "Member `{}` could not be found.".format(newmodstr)
        )

    for ticket in tickets:
        await ctx.client.tickets.get_ticket(ctx.guild.id, ticket).update_moderator(
            ctx.author.id,
            newmod.id
        )

    await ctx.reply("`{}` tickets have been updated!".format(len(tickets)))


@cmd("claim",
     group="Tickets",
     desc="Claim the specified ticket(s) as your own.")
@is_moderator()
async def cmd_claim(ctx):
    """
    Usage``:
        claim <ticket#>
        claim <ticket#>, <ticket#>, <ticket#>...
    Description:
        Changes the assigned moderator for all the specified tickets to yourself.
        This may be useful if e.g. you have used a bot to perform a moderation action,
        in which case the bot will initially be credited as the moderator.

        This requires you to be a guild moderator (i.e. have the staff role or `manage_guild`).
    Parameters::
        ticket#: The number of the ticket you wish to claim.
    Related:
        show, changemod, setreason, tickethistory, userlog
    Examples``:
        claim 1
        claim 1, 2, 3, 4
    """
    usage_str = (
        "**USAGE:**\n"
        "`claim <ticket#>`\n"
        "`claim <ticket#>, <ticket#>, <ticket#>...`"
    )

    tstrs = [tstr.strip() for tstr in ctx.arg_str.split(',')]
    if not ctx.arg_str or not all(tstr.isdigit() for tstr in tstrs):
        return await ctx.error_reply(usage_str)

    tickets = [int(tstr) for tstr in tstrs]
    max_ticket = ctx.client.tickets.guilds[ctx.guild.id].ticket_count
    dud_ticket = next((ticket for ticket in tickets if ticket > max_ticket), None)
    if dud_ticket is not None:
        return await ctx.error_reply(
            "Ticket `{}` doesn't yet exist!".format(dud_ticket)
        )

    for ticket in tickets:
        await ctx.client.tickets.get_ticket(ctx.guild.id, ticket).update_moderator(
            ctx.author.id,
            ctx.author.id
        )

    await ctx.reply("You have claimed tickets `{}`.".format(
        "`, `".join(tstrs)
    ))
