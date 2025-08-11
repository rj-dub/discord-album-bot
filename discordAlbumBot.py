import os
import json
import random
import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv
from datetime import datetime, time, timedelta
import asyncio
import gspread
from oauth2client.service_account import ServiceAccountCredentials

load_dotenv()

# Environment variables
TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
SHEET_NAME = os.getenv("GOOGLE_SHEET_NAME")
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON")

# Parse Google credentials JSON string into a dict
google_creds = json.loads(GOOGLE_CREDENTIALS_JSON)

# Setup Google Sheets client
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_dict(google_creds, scope)
gc = gspread.authorize(creds)
sheet = gc.open(SHEET_NAME).sheet1  # Using the first sheet

POSTED_FILE = 'posted_albums.json'

def load_posted():
    if os.path.exists(POSTED_FILE):
        with open(POSTED_FILE, 'r') as f:
            return set(json.load(f))
    return set()

def save_posted(posted_set):
    with open(POSTED_FILE, 'w') as f:
        json.dump(list(posted_set), f)

posted_albums = load_posted()

intents = discord.Intents.default()
intents.message_content = True
intents.messages = True  # needed to get reaction events

bot = commands.Bot(command_prefix="!", intents=intents)
# Ensure the bot has the necessary permissions to read messages and add reactions

# The time to post each day (24h format)
POST_TIME = time(hour=20, minute=0)  # 8:00 PM daily

# Emoji for ratings 1 to 5
RATING_EMOJIS = ['1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣']

# Store message ID of last posted album to track ratings
last_posted_message_id = None

# Store album info to keep track of ratings per album/message
# Key: message_id, Value: {'album': album_name, 'ratings': {user_id: rating_int}}
ratings_store = {}

def get_unposted_album(records):
    unposted = [album for album in records if album.get('Spotify Link') not in posted_albums]
    if not unposted:
        return None
    album = random.choice(unposted)
    posted_albums.add(album.get('Spotify Link'))
    save_posted(posted_albums)
    return album

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}!')
    daily_album_poster.start()  # Start the daily posting task

async def post_random_album():
    global last_posted_message_id
    global ratings_store

    channel = bot.get_channel(CHANNEL_ID)
    if channel is None:
        print("Could not find the channel. Check CHANNEL_ID.")
        return

    # Fetch all rows from sheet (assuming columns: Album Name, Spotify Link)
    records = sheet.get_all_records()
    if not records:
        print("No albums found in the Google Sheet.")
        return

    album = get_unposted_album(records)
    if album is None:
        # All albums posted, reset posted list and pick again
        posted_albums.clear()
        save_posted(posted_albums)
        album = get_unposted_album(records)
        if album is None:
            print("No albums found after reset, exiting post.")
            return

    album_name = album.get('Album Name') or album.get('Album') or album.get('Name')
    spotify_link = album.get('Spotify Link') or album.get('Link') or album.get('URL')

    if not album_name or not spotify_link:
        print("Album or Spotify link missing in the sheet row.")
        return

    # Compose message
    embed = discord.Embed(title=album_name, url=spotify_link, description="React with 1️⃣ to 5️⃣ to rate this album!")
    embed.set_footer(text="Ratings will be averaged automatically.")

    message = await channel.send(embed=embed)

    # Add reaction emojis for rating
    for emoji in RATING_EMOJIS:
        await message.add_reaction(emoji)

    # Save message ID and reset ratings
    last_posted_message_id = message.id
    ratings_store[last_posted_message_id] = {
        'album': album_name,
        'ratings': {}
    }

@tasks.loop(minutes=1)
async def daily_album_poster():
    now = datetime.now()
    target = datetime.combine(now.date(), POST_TIME)

    if now > target:
        target += timedelta(days=1)

    wait_seconds = (target - now).total_seconds()
    print(f"Waiting {wait_seconds:.0f} seconds until next post.")
    await asyncio.sleep(wait_seconds)

    await post_random_album()

@bot.event
async def on_reaction_add(reaction, user):
    await handle_reaction_change(reaction, user, added=True)

@bot.event
async def on_reaction_remove(reaction, user):
    await handle_reaction_change(reaction, user, added=False)

async def handle_reaction_change(reaction, user, added: bool):
    if user.bot:
        return  # Ignore bot reactions

    message = reaction.message
    if message.id != last_posted_message_id:
        return  # Only handle reactions on the latest album post

    emoji = reaction.emoji
    if emoji not in RATING_EMOJIS:
        return  # Ignore other emojis

    rating = RATING_EMOJIS.index(emoji) + 1

    # Update the stored ratings
    album_rating_data = ratings_store.get(message.id)
    if album_rating_data is None:
        return

    user_ratings = album_rating_data['ratings']

    if added:
        user_ratings[user.id] = rating
    else:
        # Reaction removed, remove user's rating if it matches
        if user.id in user_ratings and user_ratings[user.id] == rating:
            del user_ratings[user.id]

    # Calculate average rating
    if user_ratings:
        average = sum(user_ratings.values()) / len(user_ratings)
        average = round(average, 2)
        rating_count = len(user_ratings)
        new_footer = f"Average rating: {average} ⭐️ from {rating_count} votes."
    else:
        new_footer = "No ratings yet. React with 1️⃣ to 5️⃣ to rate!"

    # Update embed footer with average rating
    embed = message.embeds[0]
    embed.set_footer(text=new_footer)
    await message.edit(embed=embed)

if __name__ == "__main__":
    bot.run(TOKEN)
