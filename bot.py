import discord
from discord.ext import commands
import sqlite3
from datetime import datetime
from dotenv import load_dotenv
import os
import pytz

oslo_tz = pytz.timezone('Europe/Oslo')

# Convert UTC time to Oslo time
oslo_time = datetime.utcnow().replace(tzinfo=pytz.utc).astimezone(oslo_tz)

SPECIFIC_CHANNEL_ID = 374135608056086528

load_dotenv()
token = os.getenv('DISCORD_TOKEN')

intents = discord.Intents.all()  # Use all intents to track reactions
bot = commands.Bot(command_prefix='!', intents=intents)

# Connect to the SQLite database (or create it if it doesn't exist)
conn = sqlite3.connect('activity.db', detect_types=sqlite3.PARSE_DECLTYPES|sqlite3.PARSE_COLNAMES)
c = conn.cursor()

# Create the activity table if it doesn't exist
c.execute('''
    CREATE TABLE IF NOT EXISTS activity (
        user_id INTEGER PRIMARY KEY,
        last_activity_time TIMESTAMP
    )
''')

# Create the voice channel join times table if it doesn't exist
c.execute('''
    CREATE TABLE IF NOT EXISTS voice_channel_join_times (
        user_id INTEGER PRIMARY KEY,
        join_time TIMESTAMP
    )
''')

conn.commit()

@bot.event
async def on_ready():
    print('Ready!')

@bot.event
async def on_message(message):
    try:
        # Update the last activity time for the user who sent the message
        with conn:
            conn.execute('REPLACE INTO activity VALUES (?, ?)', (message.author.id, datetime.utcnow()))

        # Process commands after updating activity times
        await bot.process_commands(message)
    except Exception as e:
        print(f"Error occurred: {e}")

@bot.event
async def on_reaction_add(reaction, user):
    try:
        # Update the last activity time for the user who added the reaction
        with conn:
            conn.execute('REPLACE INTO activity VALUES (?, ?)', (user.id, datetime.utcnow()))
    except Exception as e:
        print(f"Error occurred: {e}")

@bot.event
async def on_reaction_remove(reaction, user):
    try:
        # Update the last activity time for the user who removed the reaction
        with conn:
            conn.execute('REPLACE INTO activity VALUES (?, ?)', (user.id, datetime.utcnow()))
    except Exception as e:
        print(f"Error occurred: {e}")

@bot.event
async def on_voice_state_update(member, before, after):
    try:
        # Check if the user joined a voice channel, switched channels, or left a channel and rejoined
        if (before.channel is None or after.channel is None or (before.channel is not None and after.channel is not None and before.channel.id != after.channel.id)):
            # If the user moved to the specific channel, do not update the join time
            if after.channel is not None and after.channel.id == SPECIFIC_CHANNEL_ID:
                return

            # The user joined a voice channel, switched channels, or left a channel and rejoined, so update the join time in the database
            with conn:
                conn.execute('REPLACE INTO voice_channel_join_times VALUES (?, ?)', (member.id, datetime.utcnow()))
                conn.execute('REPLACE INTO activity VALUES (?, ?)', (member.id, datetime.utcnow()))
    except Exception as e:
        print(f"Error occurred: {e}")

@bot.command()
async def afk(ctx, member: discord.Member = None):
    try:
        oslo_tz = pytz.timezone('Europe/Oslo')

        # If no member is specified, use the author of the command
        if member is None:
            member = ctx.author

        # Get the last activity time for the member
        c.execute('SELECT last_activity_time FROM activity WHERE user_id = ?', (member.id,))
        last_activity_time = c.fetchone()

        if last_activity_time is None:
            await ctx.send(f"🔍 {member.name} hasn't been active yet.")
        else:
            # Calculate the total time of inactivity
            inactivity_time = datetime.utcnow().replace(tzinfo=pytz.utc).astimezone(oslo_tz) - last_activity_time[0].replace(tzinfo=pytz.utc).astimezone(oslo_tz)
            days, remainder = divmod(inactivity_time.total_seconds(), 86400)
            hours, remainder = divmod(remainder, 3600)
            minutes, _ = divmod(remainder, 60)
            await ctx.send(f"⏰ {member.name} has been inactive for {int(days)}d {int(hours)}h {int(minutes)}m.")

        # Check if the member is currently in a voice channel
        if member.voice is not None and member.voice.channel is not None:
            voice_channel = member.voice.channel.name

            # Get the join time from the database
            c.execute('SELECT join_time FROM voice_channel_join_times WHERE user_id = ?', (member.id,))
            join_time = c.fetchone()

            if join_time is not None:
                join_time_str = join_time[0].replace(tzinfo=pytz.utc).astimezone(oslo_tz).strftime("%H:%M:%S")
                await ctx.send(f"🎧 {member.name} is in {voice_channel} since {join_time_str}.")
    except Exception as e:
        print(f"Error occurred: {e}")

bot.run(token)