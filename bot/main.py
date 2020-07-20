import os

from config import conf
from logger import log
from cmdClient.cmdClient import cmdClient

from tickets.interface import TicketInterface

# Get the real location
__location__ = os.path.realpath(os.path.join(os.getcwd(), os.path.dirname(__file__)))


# Load required data from configs
masters = [int(master.strip()) for master in conf['masters'].split(",")]

# Initialise the client
client = cmdClient(prefix=conf['prefix'], owners=masters)
client.log = log

# Initialise the TicketInterface
dbopts = {
    'username': conf['db_user'],
    'password': conf['db_password'],
    'host': conf['db_host'],
    'database': conf['db_name']
}

TicketInterface(client, dbopts)

# Load the commands
client.load_dir(os.path.join(__location__, 'commands'))

# Log and execute!
log("Initial setup complete, logging in", context='SETUP')
client.run(conf['TOKEN'])
