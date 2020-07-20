import datetime
import discord


class Ticket(object):
    ticket_fields = (
        'guild_id',
        'guild_ticket_id',
        'action_id',
        'action',
        'moderator_id',
        'victim_id',
        'modlog_msg_id',
        'auditlog_id',
        'undo_at',
        'role_id',
        'reason',
        'resolved',
        'created_at',
        'modified_by_id',
        'modified_at'
    )

    def __init__(self, interface, **ticket_data):
        self.interface = interface
        self.client = interface.client
        self.message = None

        for field in self.ticket_fields:
            setattr(self, field, ticket_data.get(field, None))

    def __lt__(self, other):
        return self.created_at < other.created_at

    def __eq__(self, other):
        return self.guild_id == other.guild_id and self.guild_ticket_id == other.guild_ticket_id

    @property
    def embed(self):
        user = self.client.get_user(self.victim_id)
        embed = discord.Embed(
            title="{} {} {}".format(
                self.action,
                self.victim_id,
                "({})".format(user) if user else ""),
            description="**Acting moderator:** <@{id}>".format(id=self.moderator_id),
            timestamp=self.created_at
        )
        embed.set_author(name="Ticket #{}".format(self.guild_ticket_id))
        embed.set_footer(text="Created at")

        if self.action_id == self.interface.ActionTypes.NOTE:
            embed.add_field(name="Note", value=self.reason, inline=False)
        else:
            embed.add_field(name="Reason", value=self.reason, inline=False)
        return embed

    @property
    def summary(self):
        user = self.client.get_user(self.victim_id)
        guild = self.client.get_guild(self.guild_id)

        return "(#{}) {} {} {} {}".format(
                self.guild_ticket_id,
                self.action,
                self.victim_id,
                "({})".format(user) if user else "",
                "in {}".format(guild) if guild else ""
        )

    async def refresh(self):
        """
        Updates the ticket embed in the mod log.
        Assumes `msgid` is set and the ticket has been posted.
        """
        if not self.message:
            channel = self.client.get_channel(self.interface.guilds[self.guild_id].modlog_id)
            self.message = await channel.fetch_message(self.modlog_msg_id)
            if self.message is None:
                # TODO: Complain loudly, maybe repost?
                raise Exception("Attempting to update a ticket, but couldn't find the ticket message!")
        await self.message.edit(embed=self.embed)

    def update(self, **new_ticket_data):
        # Update ticket in database
        set_str = ", ".join("{} = %s".format(key) for key in new_ticket_data.keys())
        with self.interface.conn.cursor() as cursor:
            cursor.execute(
                "UPDATE Tickets SET {} WHERE guild_id = %s AND guild_ticket_id = %s".format(set_str),
                (*new_ticket_data.values(), self.guild_id, self.guild_ticket_id)
            )
            self.interface.conn.commit()

        # Store old attributes for mod queues
        old_moderator_id = self.moderator_id
        old_resolved = self.resolved

        # Update own attributes
        for attr, value in new_ticket_data.items():
            setattr(self, attr, value)

        # Modify the mod queues appropriately
        if not old_resolved:
            old_tmod = self.interface.mods.get(old_moderator_id, None)
            if self.resolved:
                # Remove the ticket from the mod queue
                if old_tmod is not None:
                    old_tmod.remove_ticket(self)
            elif self.moderator_id != old_moderator_id:
                # Move the ticket
                if old_tmod is not None:
                    old_tmod.remove_ticket(self)
                asyncio.ensure_future(self.interface.queue_ticket(self))

    async def update_reason(self, modified_by_id, new_reason, resolved=True):
        self.update(
            modified_by_id=modified_by_id,
            reason=new_reason,
            resolved=resolved
        )
        await self.refresh()

    async def update_moderator(self, modified_by_id, new_mod_id):
        self.update(
            modified_by_id=modified_by_id,
            moderator_id=new_mod_id
        )
        await self.refresh()
