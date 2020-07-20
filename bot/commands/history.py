import discord
from cmdClient import cmd
from cmdClient.lib import UserCancelled, ResponseTimedOut

from utils.seekers import find_member # noqa

from wards import is_moderator

"""
Commands:
    history - paged summary history of a given ticket.
        Maybe have a syntax to pull up a version of a ticket.
    userlog - Show the tickets associated to a given user,
        as a paged summary.
"""


# TODO: userlog might be best in moderation
# TODO: modlog message links as ticket numbers
@cmd("userlog",
     group="History",
     desc="Display the past tickets associated to a user.")
@is_moderator()
async def cmd_userlog(ctx):
    """
    Usage``:
        userlog <user>
    Description:
        Display the past tickets acting on the specified user in a paged summary.

        This requires you to be a guild moderator (i.e. have the staff role or `manage_guild`).
    Parameters::
        user: User to create the note for. Can be a userid, name, or mention.
    Related:
        show
    """
    if not ctx.arg_str:
        return await ctx.error_reply("**USAGE:** `userlog <user>`")

    # Obtain target user
    try:
        user = await ctx.find_member(ctx.arg_str, interactive=True)
    except UserCancelled:
        return await ctx.error_reply("User cancelled.")
    except ResponseTimedOut:
        return await ctx.error_reply("Member selection timed out.")

    if user is None:
        return await ctx.error_reply("No members found matching `{}`".format(ctx.arg_str))

    # Obtain history
    tickets = ctx.client.tickets.get_member_tickets(ctx.guild.id, user.id)
    tickets.sort(key=lambda ticket: ticket.guild_ticket_id)

    if not tickets:
        return await ctx.reply("No past tickets associated with this user.")

    tguild = ctx.client.tickets.guilds[ctx.guild.id]

    ticket_summaries = []
    for ticket in tickets:
        summary = (
            "{time} "
            "[#{ticket_number}](https://discordapp.com/channels/{guildid}/{modlog}/{modlog_msg_id}): "
            "{action} by {moderator}\n"
            "```{reason}```"
        ).format(
            time=ticket.created_at,
            guildid=ctx.guild.id,
            modlog=tguild.modlog_id,
            modlog_msg_id=ticket.modlog_msg_id,
            ticket_number=ticket.guild_ticket_id,
            action=ticket.action,
            moderator="<@{}>".format(ticket.moderator_id),
            reason=ticket.reason or "No reason."
        )
        ticket_summaries.append(summary)

    pages = []
    current_page = ""
    for summary in ticket_summaries:
        if len(current_page) > 2048:
            pages.append(current_page[:2048])
            current_page = current_page[2048:]

        if current_page and len(current_page) + len(summary) > 2048:
            pages.append(current_page)
            current_page = summary
        else:
            current_page += "\n" + summary

    if current_page:
        pages.append(current_page)

    embeds = []
    for i, page in enumerate(pages):
        embed = discord.Embed(
            title="Log for user {}".format(user),
            description=page
        )
        embed.set_footer(text="Page {}/{}".format(i + 1, len(pages)))
        embeds.append(embed)

    await ctx.pager(embeds, locked=False)


@cmd("tickethistory",
     group="History",
     desc="Display the history of a specified ticket.")
@is_moderator()
async def cmd_history(ctx):
    """
    Usage``:
        history <ticket#>
    Description:
        Display a transactional history of the specified ticket.

        This requires you to be a guild moderator (i.e. have the staff role or `manage_guild`).
    Parameters::
        ticket#: The number of the ticket you want to display history for.
    Related:
        show
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

    # Retrieve the ticket history
    ticket_history = ctx.client.tickets.get_ticket_history(ctx.guild.id, ticket_num)
    ticket_history.sort(key=lambda ticket: ticket.guild_ticket_id)

    # Build the transaction summaries
    transactions = []

    # Creation event
    first_ticket = ticket_history[0]
    transactions.append(
        "{time}: Ticket was created by {moderator} with reason ```{reason}```".format(
            time=first_ticket.created_at,
            moderator="<@{}>".format(first_ticket.moderator_id),
            reason=first_ticket.reason
        )
    )

    for old_ticket, new_ticket in zip(ticket_history, ticket_history[1:]):
        modified_by = new_ticket.modified_by_id
        modified_at = new_ticket.modified_at
        if old_ticket.reason != new_ticket.reason:
            transactions.append(
                "{modified_at}: Ticket reason was changed by <@{modified_by}> to ```{reason}```".format(
                    modified_at=modified_at,
                    modified_by=modified_by,
                    reason=new_ticket.reason
                )
            )
        if old_ticket.moderator_id != new_ticket.moderator_id:
            transactions.append(
                "{modified_at}: Ticket moderator was changed to <@{new_mod}> by <@{modified_by}>.".format(
                    modified_at=modified_at,
                    modified_by=modified_by,
                    new_mod=new_ticket.moderator_id
                )
            )

    pages = []
    current_page = ""
    for summary in transactions:
        if len(current_page) > 2048:
            pages.append(current_page[:2048])
            current_page = current_page[2048:]

        if current_page and len(current_page) + len(summary) > 2048:
            pages.append(current_page)
            current_page = summary
        else:
            current_page += "\n" + summary

    if current_page:
        pages.append(current_page)

    embeds = []
    for i, page in enumerate(pages):
        embed = discord.Embed(
            title="Log for Ticket {}".format(ticket.guild_ticket_id),
            description=page
        )
        embed.set_footer(text="Page {}/{}".format(i + 1, len(pages)))
        embeds.append(embed)

    await ctx.pager(embeds, locked=False)
