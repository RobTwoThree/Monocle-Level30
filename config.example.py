### Define a unique instance id. It needs to be different for each instance running.
### If not set explicitly, monocle root dir will be used as default.
#
#INSTANCE_ID = '/var/www/Monocle'


### All lines that are commented out (and some that aren't) are optional ###

DB_ENGINE = 'sqlite:///db.sqlite'
#DB_ENGINE = 'mysql://user:pass@localhost/monocle'
#DB_ENGINE = 'postgresql://user:pass@localhost/monocle

### DB queue/pool size settings
### These are to be used if you see errors relating to pool_size from sqlalchemy
### DO not set extremely high
#
# DB_POOL_SIZE = 5     # sqlalchemy defualt
# DB_MAX_OVERFLOW = 10 # sqlalchemy default

## Reconnect db session after x seconds. It solves lost connection error if DB wait_timeout is set to lower values.
# DB_POOL_RECYCLE = 600

AREA_NAME = 'SLC'     # the city or region you are scanning
LANGUAGE = 'EN'       # ISO 639-1 codes EN, DE, ES, FR, IT, JA, KO, PT, or ZH for Pokémon/move names
MAX_CAPTCHAS = 100    # stop launching new visits if this many CAPTCHAs are pending
SCAN_DELAY = 10       # wait at least this many seconds before scanning with the same account
SPEED_UNIT = 'miles'  # valid options are 'miles', 'kilometers', 'meters'
SPEED_LIMIT = 19.5    # limit worker speed to this many SPEED_UNITs per hour

# The number of simultaneous workers will be these two numbers multiplied.
# On the initial run, workers will arrange themselves in a grid across the
# rectangle you defined with MAP_START and MAP_END.
# The rows/columns will also be used for the dot grid in the console output.
# Provide more accounts than the product of your grid to allow swapping.
GRID = (4, 4)  # rows, columns

### Extra accounts to pull from DB in percentage of total workers for swap.
### Default 0.0 (0%)
#EXTRA_ACCOUNT_PERCENT = 0.0
#
### For example, if you want to have extra 10% accounts for periodic swapping, set
#EXTRA_ACCOUNT_PERCENT = 0.1

### Lv30 accounts to pull from DB in percentage of total workers for encounter.
### Setting this will enable Lv30 pool for encounters
### Default 0.0(0%)
#LV30_PERCENT_OF_WORKERS = 0.0
#
### For example, if you want to have 5% level 30 acccounts for encounter, set
#LV30_PERCENT_OF_WORKERS = 0.05

### This will use 7 level 30, adjust to your needs
#LV30_PERCENT_OF_WORKERS = float(7 / (GRID[0] * GRID[1]) - 0.001) 

#
### Delay in seconds before starting next encounter.
### This allows adjustment of overall encounter rate (to make it slower).
#LV30_ENCOUNTER_WAIT=0.0

### Gym Raider accounts to pull from DB in percentage of total gyms inside the borders for gym scanning.
### Default 0.0(0%) Monkey Raiders turned off by default
#RAIDERS_PER_GYM = 0
#
### For example, if you want to have 0.03 raiders per gym, set 0.03.
### As a basic guideline, 0.03 would result in around 5 mins refresh time for all gyms.
### The following describes requirement of 3 workers per 100 gyms with guarantee of maximum 5 mins refresh time.
#RAIDERS_PER_GYM = 0.03

### Do GMO requests for lv30 accounts.
### Setting False will increase encounter rate and reduce hashing usage as it will apply insta-teleport encounter.
### Setting True will reduce account ban risks as it will apply normal Monocle behavior.
### Default False.
#LV30_GMO = False

### Maximum speed for lv30 accounts in SPEED_UNIT/hr.
### Default is 0.0 to disable.
### When disabled, worker will not take any traveling time to encounter. (insta-teleport activated!)
#LV30_MAX_SPEED = 0.0

### If encounter jobs queue up more than this amount, new sightings will be saved without encounter.
### Defaults to 0, which means no max limit.
#LV30_MAX_QUEUE = 0
#
###It is recommended to set it to this formula if you decided to cap the max queue size.
LV30_MAX_QUEUE = int(LV30_PERCENT_OF_WORKERS * GRID[0] * GRID[1] * 10.0)



# the corner points of a rectangle for your workers to spread out over before
# any spawn points have been discovered
MAP_START = (40.7913, -111.9398)
MAP_END = (40.7143, -111.8046)

# ensure that you visit within this many meters of every part of your map during bootstrap
# lower values are more thorough but will take longer
BOOTSTRAP_RADIUS = 70

GIVE_UP_KNOWN = 300   # try to find a worker for a known spawn for this many seconds before giving up
GIVE_UP_UNKNOWN = 1500 # try to find a worker for an unknown point for this many seconds before giving up
SKIP_SPAWN = 1500      # don't even try to find a worker for a spawn if the spawn time was more than this many seconds ago

# How often should the mystery queue be reloaded (default 90s)
# this will reduce the grouping of workers around the last few mysteries
#RESCAN_UNKNOWN = 90

### Import Accounts directly into your database with
### 'python3 scripts/import_accounts.py account.csv' for level 30 Accounts add '--level 30'
# filename of accounts CSV
#ACCOUNTS_CSV = 'accounts.csv'

### Swap out accounts on warning popup
#ACCOUNTS_SWAP_OUT_ON_WARN = False
#
### Set period for account hibernation.
### For hibernation to work, set up cron for cleanup.py. See wiki for details.
#ACCOUNTS_HIBERNATE_DAYS = 7.0

# the directory that the pickles folder, socket, CSV, etc. will go in
# defaults to working directory if not set
#DIRECTORY = None

# Allows you to specify how many log files to keep before recycling
# Monocle defaults to scan.log plus 4 for a total of 5
#LOGGED_FILES = 4

# Allows you to specify size for log files to keep 
# Monocle defaults to scan.log 
#LOGGED_SIZE = 500000

# Limit the number of simultaneous logins to this many at a time.
# Lower numbers will increase the amount of time it takes for all workers to
# get started but are recommended to avoid suddenly flooding the servers with
# accounts and arousing suspicion.
SIMULTANEOUS_LOGINS = 4

# Limit the number of workers simulating the app startup process simultaneously.
SIMULTANEOUS_SIMULATION = 10

# Immediately select workers whose speed are below (SPEED_UNIT)p/h instead of
# continuing to try to find the worker with the lowest speed.
# May increase clustering if you have a high density of workers.
GOOD_ENOUGH = 0.1

# Seconds to sleep after failing to find an eligible worker before trying again.
SEARCH_SLEEP = 2.5

## alternatively define a Polygon to use as boundaries (requires shapely)
## more information available in the shapely manual:
## http://toblerity.org/shapely/manual.html#polygons
#from shapely.geometry import Polygon
#BOUNDARIES = Polygon(((40.799609, -111.948556), (40.792749, -111.887341), (40.779264, -111.838078), (40.761410, -111.817908), (40.728636, -111.805293), (40.688833, -111.785564), (40.689768, -111.919389), (40.750461, -111.949938)))

# key for Bossland's hashing server, needed if you're not using Go Hash.
#HASH_KEY = '9d87af14461b93cb3605'  # this key is fake

#GO_HASH = False

# key for Go Hash a new hashing service that acts as a hash surge buffer on top of Bosslands hash server with a pay per hash model. Needed if you're not using a key direct from Bossland
#GO_HASH_KEY = 'PH7B03W1LSD4S2LHY8UH' # this is a fake key

### Optional conguration for hash server.
### Do not mess with the following hash configs if you don't know what you are doing.
#
### Buddyauth endpoint
#HASH_ENDPOINT="http://pokehash.buddyauth.com"
#
### Gohash endpoint 
#GOHASH_ENDPOINT="http://hash.gomanager.biz"

# Skip PokéStop spinning and egg incubation if your request rate is too high
# for your hashing subscription.
# e.g.
#   75/150 hashes available 35/60 seconds passed => fine
#   70/150 hashes available 30/60 seconds passed => throttle (only scan)
# value: how many requests to keep as spare (0.1 = 10%), False to disable
#SMART_THROTTLE = False

# Swap the worker that has seen the fewest Pokémon every x seconds
# Defaults to whatever will allow every worker to be swapped within 6 hours
#SWAP_OLDEST = 300  # 5 minutes
# Only swap if it's been active for more than x minutes
#MINIMUM_RUNTIME = 10

### these next 6 options use more requests but look more like the real client
APP_SIMULATION = True     # mimic the actual app's login requests
COMPLETE_TUTORIAL = True  # complete the tutorial process and configure avatar for all accounts that haven't yet
INCUBATE_EGGS = True      # incubate eggs if available

## encounter Pokémon to store IVs.
## valid options:
# 'all' will encounter every Pokémon that hasn't been already been encountered
# 'some' will encounter Pokémon if they are in ENCOUNTER_IDS or eligible for notification
# None will never encounter Pokémon
ENCOUNTER = None
#ENCOUNTER_IDS = (3, 6, 9, 45, 62, 71, 80, 85, 87, 89, 91, 94, 114, 130, 131, 134)

# PokéStops
SPIN_POKESTOPS = True  # spin all PokéStops that are within range
SPIN_COOLDOWN = 300    # spin only one PokéStop every n seconds (default 300)

## Gyms

### Toggles scanning for gym names.
#GYM_NAMES = True 

### Toggles scanning gyms for gym_defenders.
### Set this to False if you want to call GYM_GET_INFO RPC only for gym names.
#GYM_DEFENDERS = True

# minimum number of each item to keep if the bag is cleaned
# bag cleaning is disabled if this is not present or is commented out
''' # triple quotes are comments, remove them to use this ITEM_LIMITS example
ITEM_LIMITS = {
    1:    0,  # Poké Ball
    2:    0,  # Great Ball
    3:    5,  # Ultra Ball
    4:    10,  # Master Ball
    101:   0,  # Potion
    102:   0,  # Super Potion
    103:   0,  # Hyper Potion
    104:  5,  # Max Potion
    201:   0,  # Revive
    202:  5,  # Max Revive
    301:  5,  # Lucky Egg
    401:  5,  # Incense
    501:  5,  # Lure Module 
    701:  5,  # Razz Berry
    702:  5,  # Bluk Berry
    703:  5,  # Nanab Berry
    704:  5,  # Wepar Berry
    705:  5,  # Pinap Berry
    902:  5,  # Incubator
}
'''

# Update the console output every x seconds
REFRESH_RATE = 0.75  # 750ms
# Update the seen/speed/visit/speed stats every x seconds
STAT_REFRESH = 5

# sent with GET_PLAYER requests, should match your region
PLAYER_LOCALE = {'country': 'US', 'language': 'en', 'timezone': 'America/Denver'}

# retry a request after failure this many times before giving up
MAX_RETRIES = 3

# number of seconds before timing out on a login request
LOGIN_TIMEOUT = 2.5

# add spawn points reported in cell_ids to the unknown spawns list
#MORE_POINTS = False 

# Set to True to kill the scanner when a newer version is forced
#FORCED_KILL = False

### Exclude these Pokémon from the map by default (only visible in trash layer) 
### DB insert is not affected. The will still be inserted to DB as normal. See NO_DB_INSERT_IDS config below.
TRASH_IDS = (
    16, 19, 21, 29, 32, 41, 46, 48, 50, 52, 56, 74, 77, 96, 111, 133,
    161, 163, 167, 177, 183, 191, 194
)

### Prevent these pokemon from being inserted to the database and thus visible on the map; at all
### Default is None (Everything is inserted)
#NO_DB_INSERT_IDS = None

### To set it the same as TRASH_IDS do the following.
#NO_DB_INSERT_IDS = TRASH_IDS

# include these Pokémon on the "rare" report
RARE_IDS = (3, 6, 9, 45, 62, 71, 80, 85, 87, 89, 91, 94, 114, 130, 131, 134)

from datetime import datetime
REPORT_SINCE = datetime(2017, 2, 17)  # base reports on data from after this date

# used for altitude queries and maps in reports
#GOOGLE_MAPS_KEY = 'OYOgW1wryrp2RKJ81u7BLvHfYUA6aArIyuQCXu4'  # this key is fake
REPORT_MAPS = True  # Show maps on reports
#ALT_RANGE = (1250, 1450)  # Fall back to altitudes in this range if Google query fails

## Round altitude coordinates to this many decimal places
## More precision will lead to larger caches and more Google API calls
## Maximum distance from coords to rounded coords for precisions (at Lat40):
## 1: 7KM, 2: 700M, 3: 70M, 4: 7M
#ALT_PRECISION = 2

## Automatically resolve captchas using 2Captcha key.
#CAPTCHA_KEY = '1abc234de56fab7c89012d34e56fa7b8'
## the number of CAPTCHAs an account is allowed to receive before being swapped out
#CAPTCHAS_ALLOWED = 3
## Get new accounts from the CAPTCHA queue first if it's not empty
#FAVOR_CAPTCHA = True
## Use anticaptcha instead of 2captcha
#USE_ANTICAPTCHA = True

# allow displaying the live location of workers on the map
MAP_WORKERS = True
# filter these Pokemon from the map to reduce traffic and browser load
#MAP_FILTER_IDS = [161, 165, 16, 19, 167]

# unix timestamp of last spawn point migration, spawn times learned before this will be ignored
LAST_MIGRATION = 1481932800  # Dec. 17th, 2016

# Treat a spawn point's expiration time as unknown if nothing is seen at it on more than x consecutive visits
#FAILURES_ALLOWED = 3 

## Map data provider and appearance, previews available at:
## https://leaflet-extras.github.io/leaflet-providers/preview/
#MAP_PROVIDER_URL = '//{s}.tile.openstreetmap.org/{z}/{x}/{y}.png'
#MAP_PROVIDER_ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'

# set of proxy addresses and ports
# SOCKS requires aiosocks to be installed
#PROXIES = {'http://127.0.0.1:8080', 'https://127.0.0.1:8443', 'socks5://127.0.0.1:1080'}

# Bytestring key to authenticate with manager for inter-process communication
#AUTHKEY = b'm3wtw0'
# Address to use for manager, leave commented if you're not sure.
#MANAGER_ADDRESS = r'\\.\pipe\monocle'  # must be in this format for Windows
#MANAGER_ADDRESS = 'monocle.sock'       # the socket name for Unix systems
#MANAGER_ADDRESS = ('127.0.0.1', 5002)  # could be used for CAPTCHA solving and live worker maps on remote systems

# Store the cell IDs so that they don't have to be recalculated every visit.
# Enabling will (potentially drastically) increase memory usage.
#CACHE_CELLS = False

# Only for use with web_sanic (requires PostgreSQL)
#DB = {'host': '127.0.0.1', 'user': 'monocle_role', 'password': 'pik4chu', 'port': '5432', 'database': 'monocle'}

# Disable to use Python's event loop even if uvloop is installed
#UVLOOP = True

# The number of coroutines that are allowed to run simultaneously.
#COROUTINES_LIMIT = GRID[0] * GRID[1]

### FRONTEND CONFIGURATION
LOAD_CUSTOM_HTML_FILE = False # File path MUST be 'templates/custom.html'
LOAD_CUSTOM_CSS_FILE = False  # File path MUST be 'static/css/custom.css'
LOAD_CUSTOM_JS_FILE = False   # File path MUST be 'static/js/custom.js'

#FB_PAGE_ID = None
#TWITTER_SCREEN_NAME = None  # Username withouth '@' char
#DISCORD_INVITE_ID = None
#TELEGRAM_USERNAME = None  # Username withouth '@' char

## Variables below will be used as default values on frontend
#RAIDS_FILTER = (1, 2, 3, 4, 5)  # Levels shown by default on map
FIXED_OPACITY = False  # Make marker opacity independent of remaining time
SHOW_TIMER = False  # Show remaining time on a label under each pokemon marker
SHOW_TIMER_RAIDS = True  # Show remaining time on a label under each raid marker

### OPTIONS BELOW THIS POINT ARE ONLY NECESSARY FOR NOTIFICATIONS ###
NOTIFY = False  # enable notifications

# create images with Pokémon image and optionally include IVs and moves
# requires cairo and ENCOUNTER = 'notifying' or 'all'
TWEET_IMAGES = True
# IVs and moves are now dependant on level, so this is probably not useful
IMAGE_STATS = False

# As many hashtags as can fit will be included in your tweets, these will
# be combined with landmark-specific hashtags (if applicable).
HASHTAGS = {AREA_NAME, 'Monocle', 'PokemonGO'}
#TZ_OFFSET = 0  # UTC offset in hours (if different from system time)

# the required number of seconds remaining to notify about a Pokémon
TIME_REQUIRED = 600  # 10 minutes

### Only set either the NOTIFY_RANKING or NOTIFY_IDS, not both!
# The (x) rarest Pokémon will be eligible for notification. Whether a
# notification is sent or not depends on its score, as explained below.
NOTIFY_RANKING = 90

# Pokémon to potentially notify about, in order of preference.
# The first in the list will have a rarity score of 1, the last will be 0.
#NOTIFY_IDS = (130, 89, 131, 3, 9, 134, 62, 94, 91, 87, 71, 45, 85, 114, 80, 6)

# Sightings of the top (x) will always be notified about, even if below TIME_REQUIRED
# (ignored if using NOTIFY_IDS instead of NOTIFY_RANKING)
ALWAYS_NOTIFY = 14

# Always notify about the following Pokémon even if their time remaining or scores are not high enough
#ALWAYS_NOTIFY_IDS = {89, 130, 144, 145, 146, 150, 151}

# Never notify about the following Pokémon, even if they would otherwise be eligible
#NEVER_NOTIFY_IDS = TRASH_IDS

# Override the rarity score for particular Pokémon
# format is: {pokemon_id: rarity_score}
#RARITY_OVERRIDE = {148: 0.6, 149: 0.9}

# Ignore IV score and only base decision on rarity score (default if IVs not known)
#IGNORE_IVS = False

# Ignore rarity score and only base decision on IV score
#IGNORE_RARITY = False

# The Pokémon score required to notify goes on a sliding scale from INITIAL_SCORE
# to MINIMUM_SCORE over the course of FULL_TIME seconds following a notification
# Pokémon scores are an average of the Pokémon's rarity score and IV score (from 0 to 1)
# If NOTIFY_RANKING is 90, the 90th most common Pokémon will have a rarity of score 0, the rarest will be 1.
# IV score is the IV sum divided by 45 (perfect IVs).
FULL_TIME = 1800  # the number of seconds after a notification when only MINIMUM_SCORE will be required
INITIAL_SCORE = 0.7  # the required score immediately after a notification
MINIMUM_SCORE = 0.4  # the required score after FULL_TIME seconds have passed

### The following values are fake, replace them with your own keys to enable
### notifications, otherwise exclude them from your config
### You must provide keys for at least one service to use notifications.

#PB_API_KEY = 'o.9187cb7d5b857c97bfcaa8d63eaa8494'
#PB_CHANNEL = 0  # set to the integer of your channel, or to None to push privately

#TWITTER_CONSUMER_KEY = '53d997264eb7f6452b7bf101d'
#TWITTER_CONSUMER_SECRET = '64b9ebf618829a51f8c0535b56cebc808eb3e80d3d18bf9e00'
#TWITTER_ACCESS_KEY = '1dfb143d4f29-6b007a5917df2b23d0f6db951c4227cdf768b'
#TWITTER_ACCESS_SECRET = 'e743ed1353b6e9a45589f061f7d08374db32229ec4a61'

## Telegram bot token is the one Botfather sends to you after completing bot creation.
## Chat ID can be two different values:
## 1) '@channel_name' for channels
## 2) Your chat_id if you will use your own account. To retrieve your ID, write to your bot and check this URL:
##     https://api.telegram.org/bot<BOT_TOKEN_HERE>/getUpdates
##
## TELEGRAM_MESSAGE_TYPE can be 0 or 1:
## => 0 you'll receive notifications as venue (as you already seen before in Monocle)
## => 1 you'll receive notifications as text message with GMaps link
#TELEGRAM_BOT_TOKEN = '123456789:AA12345qT6QDd12345RekXSQeoZBXVt-AAA'
#TELEGRAM_CHAT_ID = '@your_channel'
#TELEGRAM_MESSAGE_TYPE = 0

### The following raid notification related configs
### only apply to Chrale's version of raids notification (no webhook support, only Telegram and Discord)
### For webhook raids notification, see below for NOTIFY_RAIDS_WEBHOOK
###
#NOTIFY_RAIDS = False # Enable raid notifications. Default False
#RAIDS_LVL_MIN = 1
#RAIDS_IDS = {143, 248}
#RAIDS_DISCORD_URL = "https://discordapp.com/api/webhooks/xxxxxxxxxxxx/xxxxxxxxxxxx"
#TELEGRAM_RAIDS_CHAT_ID = '@your_channel'

#ICONS_URL = "https://raw.githubusercontent.com/ZeChrales/monocle-icons/larger-outlined/larger-icons/{}.png"

#WEBHOOKS = {'http://127.0.0.1:4000'}

#####
## Webhook formatting config
##
## Allows configuration of outgoing raid webhooks.
## Defines <our field name>:<recipient's field name>
##
## The following are all the available fields for raid webhook.
##   "external_id", "latitude", "longitude", "level", "pokemon_id",
##   "team", "cp", "move_1", "move_2",
##   "raid_begin", "raid_battle", "raid_end",
##   "gym_id", "base64_gym_id", "gym_name", "gym_url"
##
## For PokeAlarm, no config is needed since it is supported out of the box.
#
#WEBHOOK_RAID_MAPPING = {}
#
## For others, the following is an example to map rename the field `raid_seed` to `external_id`.
#
#WEBHOOK_RAID_MAPPING = {
#    'raid_seed': 'external_id',
#    'gym_name': 'name',
#    'gym_url': 'url',
#}


##### Referencing landmarks in your tweets/notifications

#### It is recommended to store the LANDMARKS object in a pickle to reduce startup
#### time if you are using queries. An example script for this is in:
#### scripts/pickle_landmarks.example.py
#from pickle import load
#with open('pickles/landmarks.pickle', 'rb') as f:
#    LANDMARKS = load(f)

### if you do pickle it, just load the pickle and omit everything below this point

#from monocle.landmarks import Landmarks
#LANDMARKS = Landmarks(query_suffix=AREA_NAME)

# Landmarks to reference when Pokémon are nearby
# If no points are specified then it will query OpenStreetMap for the coordinates
# If 1 point is provided then it will use those coordinates but not create a shape
# If 2 points are provided it will create a rectangle with its corners at those points
# If 3 or more points are provided it will create a polygon with vertices at each point
# You can specify the string to search for on OpenStreetMap with the query parameter
# If no query or points is provided it will query with the name of the landmark (and query_suffix)
# Optionally provide a set of hashtags to be used for tweets about this landmark
# Use is_area for neighborhoods, regions, etc.
# When selecting a landmark, non-areas will be chosen first if any are close enough
# the default phrase is 'in' for areas and 'at' for non-areas, but can be overriden for either.

### replace these with well-known places in your area

## since no points or query is provided, the names provided will be queried and suffixed with AREA_NAME
#LANDMARKS.add('Rice Eccles Stadium', shortname='Rice Eccles', hashtags={'Utes'})
#LANDMARKS.add('the Salt Lake Temple', shortname='the temple', hashtags={'TempleSquare'})

## provide two corner points to create a square for this area
#LANDMARKS.add('City Creek Center', points=((40.769210, -111.893901), (40.767231, -111.888275)), hashtags={'CityCreek'})

## provide a query that is different from the landmark name so that OpenStreetMap finds the correct one
#LANDMARKS.add('the State Capitol', shortname='the Capitol', query='Utah State Capitol Building')

### area examples ###
## query using name, override the default area phrase so that it says 'at (name)' instead of 'in'
#LANDMARKS.add('the University of Utah', shortname='the U of U', hashtags={'Utes'}, phrase='at', is_area=True)
## provide corner points to create a polygon of the area since OpenStreetMap does not have a shape for it
#LANDMARKS.add('Yalecrest', points=((40.750263, -111.836502), (40.750377, -111.851108), (40.751515, -111.853833), (40.741212, -111.853909), (40.741188, -111.836519)), is_area=True)

### Shadown ban module
#SB_DETECTOR = False
#SB_COMMON_POKEMON_IDS = (16,19,23,27,29,32,41,43,46,52,54,60,69,72,74,77,81,98,118,120,129,161,165,167,177,183,187,191,194,198,209,218)
#SB_MAX_ENC_MISS = 3           # Number of encounter misses before account is marked as sbanned
#SB_MIN_SIGHTING_COUNT = 30    # Minimum sightings required to flag SB
#SB_QUARANTINE_VISITS = 12     # Number of mininum visits needed to check if an account has seen any uncommon
#SB_WEBHOOK = None             # Define webhook end point for SB. Payload is Discord type.

####
### PgScout (Credit to Avatar690)
## MUST MATCH YOUR PGSCOUT CONFIG.JSON.  Will encounter based on ENCOUNTER_IDs above.  
## If encounter fails, worker.py will attempt to encounter with the running acount (if lv > 30)
## If it fails, sighting will be saved without additional encounter info.

### Enter in your address for PGSCOUT hook endpoint including hostname, port (if any) and path.
### If set to a url, PGSCOUT will be used. If None, normal Monocle encounter will be used. 
#
#PGSCOUT_ENDPOINT = None
#
## Example,
#PGSCOUT_ENDPOINT = {"http://127.0.0.1:1234/iv","http://127.0.0.1:1235/iv"}
#
## *Take note that /iv is needed at the end for PGScout. Do not remove it.*

## Set the connection timeout to wait on a response from PGScout.  Default is 40 seconds.
## Timeout will be connection dependent, proxy dependent, etc.  I recommend keeping it at the default.
## Going too high will certainly guarantee a response from a Scout but will lead to greater inefficiency
## and instability for Monocle
#
#PGSCOUT_TIMEOUT = 40 
#


### Record keeping settings
###
### If True, new fort_sightings and raids will be inserted. Else, existing records for the same fort will be updated (if found).
### Default is False
#KEEP_GYM_HISTORY = False
#
### If True, new sightings inserted. Else, existing sighting for the same spawnpoint will be updated (if found).
### Default is True
#KEEP_SPAWNPOINT_HISTORY = True 


### Cleanup
## Max number of rows to delete in each execution per table. Not recommended to set it too high. It will choke the DB.
# CLEANUP_LIMIT = 100000

## Table specific cleanup times. Set -1.0 to disable
# CLEANUP_RAIDS_OLDER_THAN_X_HR = 6.0
# CLEANUP_SIGHTINGS_OLDER_THAN_X_HR = 6.0
# CLEANUP_SPAWNPOINTS_OLDER_THAN_X_HR = 24.0
# CLEANUP_FORT_SIGHTINGS_OLDER_THAN_X_HR = 6.0
# CLEANUP_MYSTERY_SIGHTINGS_OLDER_THAN_X_HR = 24.0

### Discord webhook url for sending scan log messages
#SCAN_LOG_WEBHOOK = None

