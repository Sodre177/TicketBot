import datetime
import asyncio
import bisect
from enum import IntEnum

import mysql.connector
import discord

from .ticket import Ticket


class TicketGuild(object):
    __slots__ = (
        "guild_id",
        "staffrole_id",
        "modlog_id",
        "active_roles",
        "ticket_count",
        "last_checked",
        "last_audit_entry",
        "auditevents_handled",
        "auditreader_lock"
    )

    def __init__(self, guild_id, staffrole_id, modlog_id, ticket_count, last_checked):
        self.guild_id = guild_id
        self.staffrole_id = staffrole_id
        self.modlog_id = modlog_id
        self.ticket_count = ticket_count
        self.last_checked = last_checked

        self.active_roles = set()

        self.last_audit_entry = 0
        self.auditevents_handled = set()
        self.auditreader_lock = asyncio.Lock()


class TicketMod(object):
    __slots__ = (
        "user",
        "ticket_queue",
        "last_reminder"
    )

    def __init__(self, user):
        self.user = user
        self.ticket_queue = []
        self.last_reminder = 0

    def insert_ticket(self, ticket):
        bisect.insort(self.ticket_queue, ticket)
        return self  # For chaining

    def remove_ticket(self, ticket):
        try:
            self.ticket_queue.remove(ticket)
        except ValueError:
            pass

    def touch(self):
        self.last_reminder = datetime.datetime.utcnow().timestamp()

    async def poke(self):
        await self.user.send(
            "{}, you have {} tickets in your queue awaiting reasons!".format(
                self.user.mention,
                len(self.ticket_queue)
            )
        )
        self.touch()


class TicketInterface(object):
    def __init__(self, client, dbopts):
        self.client = client

        self.ActionTypes = None  # Enum of moderator action types, set in `load_types`
        self.actionmap = {}  # action_id: action_name, set in `load_types`

        self.guilds = {}  # guildid: TicketGuild
        self.mods = {}  # modid: TicketMod

        self.conn = mysql.connector.connect(**dbopts)

        self.ready = False
        self.setup_client()

    def setup_client(self):
        self.client.tickets = self
        self.client.add_after_event("ready", self.launch)
        self.client.add_after_event("member_update", self.member_update_hook)
        self.client.add_after_event("member_ban", self.ban_unban_hook)
        self.client.add_after_event("member_unban", self.ban_unban_hook)
        self.client.add_after_event("member_remove", self.kick_hook)

    async def launch(self, client):
        # Quit if we have already launched
        if self.ready:
            return

        # Load guilds and active roles
        self.load_types()
        self.load_guilds()
        self.load_mods()

        self.ready = True

        await self.audit_catchup()
        asyncio.ensure_future(self.modloop())

    def load_types(self):
        with self.conn.cursor() as cursor:
            cursor.execute(
                "SELECT action_name, action_id from ActionTypes"
            )
            action_tuples = [tuple(action_pair) for action_pair in cursor.fetchall()]
            self.ActionTypes = IntEnum("ActionTypes", action_tuples)
            self.action_map = {action_pair[1]: action_pair[0] for action_pair in action_tuples}

    def load_guilds(self):
        """
        Read and cache guild data from DB.
        """
        with self.conn.cursor() as cursor:
            cursor.execute("SELECT * FROM GuildView")
            for guilddata in cursor.fetchall():
                guild_id, staffrole_id, modlog_id, role_id, ticket_count = guilddata[:5]
                created_at, last_checked, last_audit_entry = guilddata[5:]
                print(guild_id, staffrole_id, modlog_id, role_id, ticket_count or 0, last_checked, last_audit_entry)
                if guild_id not in self.guilds:
                    tguild = TicketGuild(
                        guild_id,
                        staffrole_id,
                        modlog_id,
                        ticket_count or 0,
                        last_checked or created_at
                    )
                    tguild.last_audit_entry = last_audit_entry or 0
                    self.guilds[guild_id] = tguild
                if role_id:
                    self.guilds[guild_id].active_roles.add(role_id)

    def load_mods(self):
        """
        Read and cache unresolved tickets from DB.
        """
        mods = {}
        dud_moderators = set()
        with self.conn.cursor(dictionary=True) as cursor:
            cursor.execute(
                "SELECT * FROM TicketView WHERE resolved = FALSE ORDER BY created_at"
            )
            for ticketdata in cursor.fetchall():
                ticket = Ticket(self, **ticketdata)
                if ticket.moderator_id in mods:
                    mods[ticket.moderator_id].insert_ticket(ticket)
                elif ticket.moderator_id in dud_moderators:
                    continue
                else:
                    user = self.client.get_user(ticket.moderator_id)
                    if user is None or user.bot:
                        # The client can't see this user, no point making a queue for them, or
                        # The user is a bot, they can't handle queues anyway.
                        dud_moderators.add(ticket.moderator_id)
                        continue
                    else:
                        mods[ticket.moderator_id] = TicketMod(user).insert_ticket(ticket)
        self.mods = mods

    async def audit_catchup(self):
        guilds = []
        for guildid in self.guilds:
            guild = self.client.get_guild(guildid)
            if guild is not None:
                guilds.append(guild)
        await asyncio.gather(*(self.check_audit_log(guild) for guild in guilds))

    async def modloop(self):
        while True:
            now = datetime.datetime.utcnow().timestamp()
            for mod in self.mods.values():
                if now - mod.last_reminder > 60 * 1 and len(mod.ticket_queue) > 0:
                    # Notify the moderator
                    asyncio.ensure_future(mod.poke())
            await asyncio.sleep(300)

    async def prompt_mod(self, tmod, ticket=None):
        """
        Message the moderator and request they submit a reason for an unresolved ticket in their queue.
        """
        tmod.touch()
        if not ticket:
            ticket = tmod.ticket_queue[-1]

        # Send the message to the user
        try:
            out_msg = await tmod.user.send(
                embed=ticket.embed,
                content="Please enter a reason for the moderation action below, or `c` to cancel this prompt."
            )
        except discord.Forbidden:
            # Cannot send a message to this moderator
            # TODO: Whine in modlog
            return

        # Wait for their reply
        try:
            reply = await self.client.wait_for(
                "message",
                check=lambda m: m.channel.type == discord.ChannelType.private and m.author == tmod.user,
                timeout=300
            )
        except asyncio.TimeoutError:
            await out_msg.edit(content="Timed out waiting for a reason.")
        content = reply.content
        if content.lower() == 'c':
            # User cancelled
            await out_msg.edit(content="Cancelled reason entry, ticket returned to your queue.")
            pass
        else:
            # Set the ticket reason
            await ticket.update_reason(tmod.user.id, content, resolved=True)
            tmod.remove_ticket(ticket)
            await out_msg.edit(content="", embed=ticket.embed)

    async def queue_ticket(self, ticket):
        """
        Adds the ticket to the appropriate moderator queue.
        """
        if ticket.moderator_id in self.mods:
            mod = self.mods[ticket.moderator_id]
            mod.insert_ticket(ticket)
            if len(mod.ticket_queue) == 1:
                asyncio.ensure_future(self.prompt_mod(mod))
            elif mod.last_reminder + 60 * 5 < datetime.datetime.utcnow().timestamp():
                mod.touch()
                asyncio.ensure_future(
                    mod.user.send("{}, you have a new ticket in your queue!".format(mod.user.mention))
                )
        else:
            user = self.client.get_user(ticket.moderator_id)
            if user is not None and not user.bot:
                self.mods[ticket.moderator_id] = TicketMod(user).insert_ticket(ticket)
                asyncio.ensure_future(self.prompt_mod(self.mods[ticket.moderator_id]))

    async def member_update_hook(self, client, before, after):
        if before.guild.id in self.guilds and before.roles != after.roles:
            roles_changed = [role for role in after.roles if role not in before.roles]
            roles_changed.extend([role for role in before.roles if role not in after.roles])

            if any(role.id in self.guilds[after.guild.id].active_roles for role in roles_changed):
                await self.check_audit_log(after.guild)

    async def ban_unban_hook(self, client, guild, user):
        await self.check_audit_log(guild)

    async def kick_hook(self, client, member):
        await self.check_audit_log(member.guild)

    async def check_audit_log(self, guild):
        # Wait until we are ready
        while not self.ready:
            await asyncio.sleep(1)

        # Check if we need to handle this guild
        if guild.id not in self.guilds:
            return
        tguild = self.guilds[guild.id]

        async with tguild.auditreader_lock:
            # Set the new last_checked time to avoid concurrency issues
            last_checked = tguild.last_checked
            now = datetime.datetime.utcnow()
            tguild.last_checked = now
            # print("Last checked: {}".format(last_checked))

            async for entry in guild.audit_logs(limit=None, after=tguild.last_audit_entry or last_checked):
                # Check if the event has already been handled
                if entry.id in tguild.auditevents_handled:
                    continue
                # Check if we already checked this entry
                if entry.created_at <= last_checked or entry.id <= tguild.last_audit_entry:
                    print("Skipping {} entry at: {}".format(entry.action, entry.created_at))
                    continue
                # print("Reading {} entry at: {}".format(entry.action, entry.created_at))

                tguild.last_audit_entry = entry.id

                if entry.action == discord.AuditLogAction.ban:
                    tguild.auditevents_handled.add(entry.id)
                    # Create ban ticket
                    await self.create_ticket(
                        guild.id,
                        self.ActionTypes.BAN,
                        entry.user.id,
                        entry.target.id,
                        resolved=bool(entry.reason),
                        reason=entry.reason or None,
                        auditlog_id=entry.id,
                        created_at=entry.created_at,
                    )
                elif entry.action == discord.AuditLogAction.unban:
                    tguild.auditevents_handled.add(entry.id)
                    # Create unban ticket
                    await self.create_ticket(
                        guild.id,
                        self.ActionTypes.UNBAN,
                        entry.user.id,
                        entry.target.id,
                        resolved=bool(entry.reason),
                        reason=entry.reason or None,
                        auditlog_id=entry.id,
                        created_at=entry.created_at,
                    )
                elif entry.action == discord.AuditLogAction.kick:
                    tguild.auditevents_handled.add(entry.id)
                    # Create kick ticket
                    await self.create_ticket(
                        guild.id,
                        self.ActionTypes.KICK,
                        entry.user.id,
                        entry.target.id,
                        resolved=bool(entry.reason),
                        reason=entry.reason or None,
                        auditlog_id=entry.id,
                        created_at=entry.created_at,
                    )
                elif entry.action == discord.AuditLogAction.member_role_update:
                    tguild.auditevents_handled.add(entry.id)
                    # Check for active role changes
                    roles_added = [role for role in entry.after.roles if role not in entry.before.roles]
                    roles_removed = [role for role in entry.before.roles if role not in entry.after.roles]

                    # If there are any, create a ROLE_ADD or ROLE_RM ticket
                    for role in roles_added:
                        if role.id in tguild.active_roles:
                            await self.create_ticket(
                                guild.id,
                                self.ActionTypes.ROLE_ADD,
                                entry.user.id,
                                entry.target.id,
                                role_id=role.id,
                                resolved=bool(entry.reason),
                                reason=entry.reason or None,
                                auditlog_id=entry.id,
                                created_at=entry.created_at,
                            )

                    for role in roles_removed:
                        if role.id in tguild.active_roles:
                            await self.create_ticket(
                                guild.id,
                                self.ActionTypes.ROLE_RM,
                                entry.user.id,
                                entry.target.id,
                                role_id=role.id,
                                resolved=bool(entry.reason),
                                reason=entry.reason or None,
                                auditlog_id=entry.id,
                                created_at=entry.created_at,
                            )

    def register_guild(self, guild_id, staffrole_id, modlog_id):
        """
        Register a new guild or update the details for an existing one.
        """
        # Add guild to db
        with self.conn.cursor() as cursor:
            cursor.execute(
                ("INSERT INTO Guilds (guild_id, staffrole_id, modlog_id) VALUES (%s, %s, %s) "
                 "ON DUPLICATE KEY UPDATE staffrole_id = %s, modlog_id = %s"),
                (guild_id, staffrole_id, modlog_id, staffrole_id, modlog_id)
            )
            self.conn.commit()
        if guild_id in self.guilds:
            tguild = self.guilds[guild_id]
            tguild.staffrole_id = staffrole_id
            tguild.modlog_id = modlog_id
        else:
            tguild = TicketGuild(guild_id, staffrole_id, modlog_id, 0, datetime.datetime.utcnow())
            self.guilds[guild_id] = tguild

    def create_active_role(self, guildid, roleid, add_action, rm_action):
        """
        Create an active role, the addition or removal of which
        is treated as a moderation action.
        """
        with self.conn.cursor() as cursor:
            cursor.execute(
                ("INSERT INTO ActiveRoles (guild_id, role_id, add_action_name, rm_action_name, active) "
                 "VALUES (%s, %s, %s, %s, %s) "
                 "ON DUPLICATE KEY UPDATE add_action_name = %s, rm_action_name = %s"),
                (guildid, roleid, add_action, rm_action, True, add_action, rm_action)
            )
            self.conn.commit()
        self.guilds[guildid].active_roles.add(roleid)

    def deactivate_role(self, guildid, roleid):
        """
        Deactivate an active role, if it is currently active.
        """
        if roleid in self.guilds[guildid].active_roles:
            with self.conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE ActiveRoles SET active = FALSE WHERE role_id = %s",
                    (roleid, )
                )
                self.conn.commit()
            self.guilds[guildid].active_roles.remove(roleid)

    def get_ticket(self, guildid, ticketid):
        """
        Retrieve a ticket with the given parameters.
        Returns: Ticket
        """
        with self.conn.cursor(dictionary=True) as cursor:
            cursor.execute(
                "SELECT * FROM TicketView WHERE guild_id = %s AND guild_ticket_id = %s",
                (guildid, ticketid)
            )
            ticketdata = cursor.fetchone()
            return Ticket(self, **ticketdata) if ticketdata else None

    def get_ticket_history(self, guildid, ticketid):
        """
        Retrieve history of a given ticket.
        Returns: List of ticketdata tuples,
            in order of oldest to most recent.
        """
        tickets = []
        with self.conn.cursor(dictionary=True) as cursor:
            cursor.execute(
                "SELECT * FROM TicketHistory WHERE guild_id = %s AND guild_ticket_id = %s",
                (guildid, ticketid)
            )
            for ticketdata in cursor.fetchall():
                tickets.append(Ticket(self, **ticketdata))
        return tickets

    def get_member_tickets(self, guildid, userid):
        """
        Retrieve the tickets associated to a given user.
        """
        tickets = []
        with self.conn.cursor(dictionary=True) as cursor:
            cursor.execute(
                "SELECT * FROM TicketView WHERE guild_id = %s AND victim_id = %s ORDER BY modified_at",
                (guildid, userid)
            )
            for ticketdata in cursor.fetchall():
                tickets.append(Ticket(self, **ticketdata))
        return tickets

    async def create_ticket(self, guild_id, action, mod_id, victim_id, resolved=False, **kwargs):
        # Wait until we are ready
        while not self.ready:
            await asyncio.sleep(1)

        # Increment the relevant guild ticket counter
        self.guilds[guild_id].ticket_count += 1

        # Build required ticket data
        ticketid = self.guilds[guild_id].ticket_count
        ticket_data = {
            'guild_id': guild_id,
            'guild_ticket_id': ticketid,
            'action_id': int(action),
            'moderator_id': mod_id,
            'victim_id': victim_id,
            'modified_by_id': mod_id,
            'resolved': resolved
        }

        # Add extra ticket data if provided
        optional_fields = (
            'auditlog_id',
            'undo_at',
            'role_id',
            'reason',
            'created_at'
        )
        if 'created_at' in kwargs:
            kwargs['created_at'] = self.dt_to_timestamp(kwargs['created_at'])
        for field in kwargs:
            if field in optional_fields:
                ticket_data[field] = kwargs[field]
            else:
                raise ValueError("Unrecognised field `{}` passed to `create_ticket`".format(field))

        # TODO: Make this more atomic so it rolls back changes and deletes the modlog message if something goes wrong
        # Post a placeholder ticket in the modlog to get the modlog message id
        channel = self.client.get_channel(self.guilds[guild_id].modlog_id)
        if channel is None:
            # TODO: Better exception
            raise Exception("Modlog for guild (gid: {}) no longer exists.".format(guild_id))
        message = await channel.send(embed=discord.Embed().set_author(name="Ticket #{}".format(ticketid)))
        ticket_data['modlog_msg_id'] = message.id

        # Insert ticket into registry
        with self.conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO Tickets ({}) VALUES ({})".format(
                    ", ".join(ticket_data.keys()),
                    ", ".join("%s" for field in ticket_data)
                ),
                tuple(ticket_data.values())
            )
            self.conn.commit()

        # Generate the ticket and properly post to modlog
        ticket = self.get_ticket(guild_id, ticketid)
        await ticket.refresh()

        # Add the ticket to the appropriate queue here if it has not been resolved
        if not ticket.resolved:
            await self.queue_ticket(ticket)
        return ticket

    @staticmethod
    def dt_to_timestamp(dt):
        if dt.tzinfo:
            # Convert to UTC
            dt = dt.astimezone(datetime.timezone.utc)
        return dt.strftime('%Y-%m-%d %H:%M:%S+00:00')
