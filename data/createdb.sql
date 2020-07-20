USE TicketRegistry;

DROP TABLE IF EXISTS Guilds, ActionTypes, ActiveRoles, Tickets, TicketHistory;
DROP VIEW IF EXISTS TicketView, GuildView;
DROP FUNCTION IF EXISTS TO_UTC;


CREATE FUNCTION TO_UTC (ts TIMESTAMP)
RETURNS TIMESTAMP
RETURN CONVERT_TZ(ts, @@session.time_zone, '+00:00');


CREATE TABLE Guilds (
  guild_id BIGINT PRIMARY KEY,
  staffrole_id BIGINT NOT NULL,
  modlog_id BIGINT NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE ActionTypes (
  action_id TINYINT PRIMARY KEY,
  action_name VARCHAR(255)
);

CREATE TABLE ActiveRoles (
  role_id BIGINT PRIMARY KEY,
  guild_id BIGINT NOT NULL,
  add_action_name VARCHAR(255),
  rm_action_name VARCHAR(255),
  default_duration INT,
  active BOOL NOT NULL DEFAULT TRUE,
  FOREIGN KEY (guild_id)
    REFERENCES Guilds (guild_id)
);

CREATE TABLE Tickets (
  guild_id BIGINT,
  guild_ticket_id INT,
  action_id TINYINT NOT NULL,
  moderator_id BIGINT NOT NULL,
  victim_id BIGINT NOT NULL,
  modlog_msg_id BIGINT NOT NULL,
  auditlog_id BIGINT,
  undo_at BIGINT,
  role_id BIGINT,
  reason VARCHAR(2047),
  resolved BOOL NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  modified_by_id BIGINT,
  modified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (guild_id, guild_ticket_id),
  FOREIGN KEY (guild_id)
    REFERENCES Guilds (guild_id),
  FOREIGN KEY (action_id)
    REFERENCES ActionTypes (action_id),
  FOREIGN KEY (role_id)
    REFERENCES ActiveRoles (role_id)
);

CREATE TABLE TicketHistory (
  guild_id BIGINT,
  guild_ticket_id INT,
  action_id TINYINT NOT NULL,
  moderator_id BIGINT NOT NULL,
  victim_id BIGINT NOT NULL,
  modlog_msg_id BIGINT NOT NULL,
  auditlog_id BIGINT,
  undo_at BIGINT,
  role_id BIGINT,
  reason VARCHAR(2047),
  resolved BOOL NOT NULL,
  created_at TIMESTAMP,
  modified_by_id BIGINT,
  modified_at TIMESTAMP,
  FOREIGN KEY (guild_id, guild_ticket_id)
    REFERENCES Tickets (guild_id, guild_ticket_id)
);


CREATE VIEW TicketView
AS
SELECT 
  t1.guild_id,
  t1.guild_ticket_id,
  t1.action_id,
  t1.moderator_id,
  t1.victim_id,
  t1.modlog_msg_id,
  t1.auditlog_id,
  t1.undo_at,
  t1.role_id,
  t1.reason,
  t1.resolved,
  TO_UTC(t1.created_at) as created_at,
  t1.modified_by_id,
  TO_UTC(t1.modified_at) as modified_at,
  t3.active as role_active,
  CASE t2.action_name
    WHEN 'ROLE_ADD' THEN t3.add_action_name
    WHEN 'ROLE_RM' THEN t3.rm_action_name
    ELSE t2.action_name
  END as action
FROM Tickets t1
INNER JOIN ActionTypes t2 USING (action_id)
LEFT JOIN ActiveRoles t3 USING (role_id);

CREATE VIEW GuildView
AS
SELECT 
  t1.guild_id,
  t1.staffrole_id,
  t1.modlog_id,
  t3.role_id,
  MAX(t2.guild_ticket_id) AS ticket_count, 
  TO_UTC(t1.created_at) AS utc_created_at, 
  TO_UTC(MAX(t2.created_at)) AS last_ticket_created,
  MAX(t2.auditlog_id) AS last_audit_entry
FROM Guilds t1 
LEFT JOIN Tickets t2 USING (guild_id) 
LEFT JOIN ActiveRoles t3 ON t3.guild_id = t2.guild_id AND t3.active = TRUE 
GROUP BY t1.guild_id, t1.staffrole_id, t1.modlog_id, t3.role_id, utc_created_at;


CREATE TRIGGER ticket_insert_history
  AFTER INSERT
  ON Tickets FOR EACH ROW
    INSERT INTO TicketHistory SELECT * FROM Tickets WHERE guild_id = NEW.guild_id AND guild_ticket_id = NEW.guild_ticket_id;

CREATE TRIGGER ticket_update_history
  AFTER UPDATE
  ON Tickets FOR EACH ROW
    INSERT INTO TicketHistory SELECT * FROM Tickets WHERE guild_id = NEW.guild_id AND guild_ticket_id = NEW.guild_ticket_id;
