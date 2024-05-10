import discord
from discord.ext import commands
import sqlite3
from datetime import datetime, timedelta
from dotenv import load_dotenv
import os
import pytz

oslo_tz = pytz.timezone('Europe/Oslo')

load_dotenv()
token = os.getenv('DISCORD_TOKEN')
AFK_CHANNEL_ID = int(os.getenv('AFK_CHANNEL_ID'))

intents = discord.Intents.all()
bot = commands.Bot(command_prefix='!', intents=intents)

conn = sqlite3.connect('activity.db', detect_types=sqlite3.PARSE_DECLTYPES|sqlite3.PARSE_COLNAMES)
c = conn.cursor()

c.execute('''
    CREATE TABLE IF NOT EXISTS activity (
        user_id INTEGER PRIMARY KEY,
        last_activity_time TIMESTAMP
    )
''')

c.execute('''
    CREATE TABLE IF NOT EXISTS voice_channel_join_times (
        user_id INTEGER,
        channel_id INTEGER,
        join_time TIMESTAMP,
        PRIMARY KEY(user_id, channel_id)
    )
''')

c.execute('''
    CREATE TABLE IF NOT EXISTS messages (
        user_id INTEGER,
        channel_id INTEGER,
        message_count INTEGER,
        PRIMARY KEY(user_id, channel_id)
    )
''')

c.execute('''
    CREATE TABLE IF NOT EXISTS voice_channel_times (
        user_id INTEGER,
        channel_id INTEGER,
        time_spent INTEGER,
        PRIMARY KEY(user_id, channel_id)
    )
''')

conn.commit()

@bot.event
async def on_ready():
    print('Ready!')

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    with conn:
        conn.execute('REPLACE INTO activity VALUES (?, ?)', (message.author.id, datetime.now(oslo_tz)))
        conn.execute('INSERT OR IGNORE INTO messages VALUES (?, ?, 0)', (message.author.id, message.channel.id))
        conn.execute('UPDATE messages SET message_count = message_count + 1 WHERE user_id = ? AND channel_id = ?', (message.author.id, message.channel.id))

    await bot.process_commands(message)

@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot:
        return

    if before.channel is not None:
        c.execute('SELECT join_time FROM voice_channel_join_times WHERE user_id = ? AND channel_id = ?', (member.id, before.channel.id))
        join_time = c.fetchone()
        if join_time is not None:
            join_time = oslo_tz.localize(join_time[0])
            time_spent = datetime.now(oslo_tz) - join_time
            with conn:
                conn.execute('UPDATE voice_channel_times SET time_spent = time_spent + ? WHERE user_id = ? AND channel_id = ?', (time_spent.total_seconds(), member.id, before.channel.id))
                conn.execute('DELETE FROM voice_channel_join_times WHERE user_id = ? AND channel_id = ?', (member.id, before.channel.id))

    if after.channel is not None and after.channel.id != AFK_CHANNEL_ID:
        with conn:
            conn.execute('INSERT OR IGNORE INTO voice_channel_times VALUES (?, ?, 0)', (member.id, after.channel.id))
            conn.execute('REPLACE INTO voice_channel_join_times VALUES (?, ?, ?)', (member.id, after.channel.id, datetime.now(oslo_tz)))
            conn.execute('REPLACE INTO activity VALUES (?, ?)', (member.id, datetime.now(oslo_tz)))

@bot.command()
async def afk(ctx, member: discord.Member = None):
    if member is None:
        member = ctx.author

    c.execute('SELECT last_activity_time FROM activity WHERE user_id = ?', (member.id,))
    last_activity_time = c.fetchone()

    embed = discord.Embed(color=discord.Color.blue())
    embed.set_author(name=str(member), icon_url=member.avatar.url)

    if last_activity_time is None:
        embed.description = f"{member.name} hasn't been active yet."
    else:
        last_activity_time = oslo_tz.localize(last_activity_time[0])

        inactivity_time = datetime.now(oslo_tz) - last_activity_time
        days, remainder = divmod(inactivity_time.total_seconds(), 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, _ = divmod(remainder, 60)
        embed.description = f"{member.name} has been inactive for {int(days)}d {int(hours)}h {int(minutes)}m."

    if member.voice is not None and member.voice.channel is not None:
        voice_channel = member.voice.channel.name

        c.execute('SELECT join_time FROM voice_channel_join_times WHERE user_id = ?', (member.id,))
        join_time = c.fetchone()

        if join_time is not None:
            join_time = oslo_tz.localize(join_time[0])

            join_time_str = join_time.strftime("%H:%M:%S")
            embed.add_field(name="Voice Channel", value=f"{member.name} is in {voice_channel} since {join_time_str}.")

    await ctx.send(embed=embed)

@bot.command()
async def stat(ctx, member: discord.Member = None):
    if member is None:
        member = ctx.author

    embed = discord.Embed(color=discord.Color.blue())
    embed.set_author(name=str(member), icon_url=member.avatar.url)

    # Top Voice Channels
    c.execute('SELECT channel_id, SUM(time_spent) FROM voice_channel_times WHERE user_id = ? GROUP BY channel_id ORDER BY SUM(time_spent) DESC LIMIT 3', (member.id,))
    top_voice_channels = c.fetchall()

    medals = ["🥇", "🥈", "🥉"]

    top_voice_channels_str = ""
    for i, (channel_id, time_spent) in enumerate(top_voice_channels):
        channel = bot.get_channel(channel_id)

        if member.voice is not None and member.voice.channel.id == channel_id:
            c.execute('SELECT join_time FROM voice_channel_join_times WHERE user_id = ? AND channel_id = ?', (member.id, channel_id))
            join_time = c.fetchone()
            if join_time is not None:
                join_time = oslo_tz.localize(join_time[0])
                current_session_time = datetime.now(oslo_tz) - join_time
                time_spent += current_session_time.total_seconds()

        hours, remainder = divmod(time_spent, 3600)
        minutes, seconds = divmod(remainder, 60)
        top_voice_channels_str += f"{medals[i]} {channel.name} ({int(hours)}h {int(minutes)}m {int(seconds)}s)\n"

    embed.add_field(name="Top Voice Channels", value=top_voice_channels_str, inline=True)

    # Top Channels
    c.execute('SELECT channel_id, message_count FROM messages WHERE user_id = ? ORDER BY message_count DESC LIMIT 3', (member.id,))
    top_channels = c.fetchall()

    top_channels_str = ""
    for i, (channel_id, message_count) in enumerate(top_channels):
        channel = bot.get_channel(channel_id)
        top_channels_str += f"{medals[i]} {channel.name} ({message_count} messages)\n"
    
    embed.add_field(name="Top Channels", value=top_channels_str, inline=True)

    # Total Time in Voice Channels
    c.execute('SELECT SUM(time_spent) FROM voice_channel_times WHERE user_id = ?', (member.id,))
    total_time_spent = c.fetchone()[0]
    if total_time_spent is None:
        total_time_spent = 0

    if member.voice is not None and member.voice.channel is not None:
        c.execute('SELECT join_time FROM voice_channel_join_times WHERE user_id = ? AND channel_id = ?', (member.id, member.voice.channel.id))
        join_time = c.fetchone()
        if join_time is not None:
            join_time = oslo_tz.localize(join_time[0])
            current_session_time = datetime.now(oslo_tz) - join_time
            total_time_spent += current_session_time.total_seconds()

    total_hours, remainder = divmod(total_time_spent, 3600)
    total_minutes, total_seconds = divmod(remainder, 60)

    embed.add_field(name="Total Time in Voice Channels", value=f"{int(total_hours)}h {int(total_minutes)}m {int(total_seconds)}s", inline=False)

    # Total Messages Sent
    c.execute('SELECT SUM(message_count) FROM messages WHERE user_id = ?', (member.id,))
    total_messages = c.fetchone()[0]
    if total_messages is None:
        total_messages = 0

    embed.add_field(name="Total Messages Sent", value=str(total_messages), inline=True)

    await ctx.send(embed=embed)

@bot.command()
async def top(ctx):
    embed = discord.Embed(color=discord.Color.blue())
    embed.set_author(name="Top Channels", icon_url=ctx.guild.icon.url)

    # Top 3 voice channels with the highest combined time of all users
    c.execute('SELECT channel_id, SUM(time_spent) FROM voice_channel_times GROUP BY channel_id')
    top_voice_channels = c.fetchall()

    for member in ctx.guild.members:
        if member.voice is not None and member.voice.channel is not None:
            c.execute('SELECT join_time FROM voice_channel_join_times WHERE user_id = ? AND channel_id = ?', (member.id, member.voice.channel.id))
            join_time = c.fetchone()
            if join_time is not None:
                join_time = oslo_tz.localize(join_time[0])
                current_session_time = datetime.now(oslo_tz) - join_time
                for i, (channel_id, time_spent) in enumerate(top_voice_channels):
                    if channel_id == member.voice.channel.id:
                        top_voice_channels[i] = (channel_id, time_spent + current_session_time.total_seconds())

    top_voice_channels.sort(key=lambda x: x[1], reverse=True)
    top_voice_channels = top_voice_channels[:3]

    top_voice_channels_str = ""
    for i, (channel_id, time_spent) in enumerate(top_voice_channels):
        channel = bot.get_channel(channel_id)
        hours, remainder = divmod(time_spent, 3600)
        minutes, seconds = divmod(remainder, 60)
        top_voice_channels_str += f"{i+1}. {channel.name} ({int(hours)}h {int(minutes)}m {int(seconds)}s)\n"

    embed.add_field(name="Top Voice Channels", value=top_voice_channels_str, inline=True)

    # Top 3 channels with the most messages
    c.execute('SELECT channel_id, SUM(message_count) FROM messages GROUP BY channel_id ORDER BY SUM(message_count) DESC LIMIT 3')
    top_message_channels = c.fetchall()

    top_message_channels_str = ""
    for i, (channel_id, message_count) in enumerate(top_message_channels):
        channel = bot.get_channel(channel_id)
        top_message_channels_str += f"{i+1}. {channel.name} ({message_count} messages)\n"

    embed.add_field(name="Top Message Channels", value=top_message_channels_str, inline=True)

    await ctx.send(embed=embed)

bot.run(token)