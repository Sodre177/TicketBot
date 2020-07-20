from cmdClient import cmd
from cmdClient.lib import UserCancelled, ResponseTimedOut

from utils.seekers import find_member # noqa
from utils.interactive import input  # noqa

from wards import is_moderator

"""
Commands:
    moderation:
        queue - Show your current ticket queue and resolve the tickets.
        note - Create a note ticket for a user.
"""


# TODO: Handle user being in multiple guilds.
# Put guildname in list when in DMS, and only show tickets from current guild otherwise.
@cmd("queue",
     group="Moderation",
     desc="Display your personal ticket queue and resolve tickets.",
     aliases=["q"])
async def cmd_queue(ctx):
    """
    Usage``:
        queue
    Description:
        Display your personal queue of unresolved tickets you are assigned to.
        When viewing the queue you may select a ticket to resolve,
        whereupon you will be prompted to enter a reason for the ticket.

        This command works in direct messages,
        which is expected to be the most convenient place to resolve tickets.
    """
    tmod = ctx.client.tickets.mods.get(ctx.author.id, None)
    if not tmod or not tmod.ticket_queue:
        return await ctx.reply("Your ticket queue is empty, good job! ✨")
    queue = tmod.ticket_queue.copy()

    # TODO: Not really threadsafe, the ticket details might change
    while True:
        if not queue:
            return await ctx.reply("You have reached the end of your queue! ✨")

        summary_list = [ticket.summary for ticket in queue]

        try:
            index = await ctx.selector("Please select a ticket to resolve.", summary_list)
        except ResponseTimedOut:
            return await ctx.reply("Queue timed out.")
        except UserCancelled:
            return await ctx.reply("User closed queue.")

        await ctx.client.tickets.prompt_mod(tmod, queue[index])
        queue = tmod.ticket_queue.copy()


@cmd("note",
     group="Moderation",
     desc="Add a note to a user.")
@is_moderator()
async def cmd_note(ctx):
    """
    Usage``:
        note <user>
    Description:
        Create a note ticket on the specified user.

        This requires you to be a guild moderator (i.e. have the staff role or `manage_guild`).
    Parameters::
        user: User to create the note for. Can be a userid, name, or mention.
    Related:
        show, userlog
    """
    if not ctx.arg_str:
        return await ctx.error_reply("**USAGE:** `note <user>`")

    # Obtain target user
    try:
        user = await ctx.find_member(ctx.arg_str, interactive=True)
    except UserCancelled:
        return await ctx.error_reply("User cancelled, no note was created.")
    except ResponseTimedOut:
        return await ctx.error_reply("Member selection timed out, no note was created.")

    if user is None:
        return await ctx.error_reply("No members found matching `{}`".format(ctx.arg_str))

    # Obtain note
    try:
        note = await ctx.input("What is the note?")
    except ResponseTimedOut:
        return await ctx.error_reply("Note input timed out, no note was created.")

    # Create ticket
    await ctx.client.tickets.create_ticket(
        guild_id=ctx.guild.id,
        action=ctx.client.tickets.ActionTypes.NOTE,
        mod_id=ctx.author.id,
        victim_id=user.id,
        resolved=True,
        reason=note,
    )

    await ctx.reply("Note created.")
