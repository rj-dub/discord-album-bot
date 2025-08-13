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
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from unidecode import unidecode

load_dotenv()

# Environment variables
TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
SHEET_NAME = os.getenv("GOOGLE_SHEET_NAME")
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON")

SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")

# Parse Google credentials JSON string into a dict
google_creds = json.loads(GOOGLE_CREDENTIALS_JSON)

# Setup Google Sheets client
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_dict(google_creds, scope)
gc = gspread.authorize(creds)
sheet = gc.open(SHEET_NAME).sheet1  # Using the first sheet with headers on the first row

# Setup Spotify client
spotify_auth_manager = SpotifyClientCredentials(client_id=SPOTIFY_CLIENT_ID, client_secret=SPOTIFY_CLIENT_SECRET)
sp = spotipy.Spotify(auth_manager=spotify_auth_manager)

intents = discord.Intents.default()
intents.message_content = True
intents.messages = True
intents.reactions = True

bot = commands.Bot(command_prefix="!", intents=intents)

POST_TIME = time(hour=8, minute=0)  # 8 AM daily
RATING_EMOJIS = ['1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣', '6️⃣', '7️⃣', '8️⃣', '9️⃣', '🔟']

last_posted_message_id = None
ratings_store = {}

# File to store played albums so we don't repeat
PLAYED_FILE = "played_albums.json"

def load_played_albums():
    if os.path.exists(PLAYED_FILE):
        with open(PLAYED_FILE, 'r') as f:
            return set(json.load(f))
    return set()

def save_played_albums(played):
    with open(PLAYED_FILE, 'w') as f:
        json.dump(list(played), f)

played_albums = load_played_albums()

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}!")
    if not daily_album_poster.is_running():
        daily_album_poster.start()

async def post_random_album():
    global last_posted_message_id, ratings_store, played_albums

    channel = bot.get_channel(CHANNEL_ID)
    if channel is None:
        print("Could not find the channel. Check CHANNEL_ID.")
        return

    records = sheet.get_all_records(head=2)

    if not records:
        print("No albums found in the Google Sheet.")
        return

    available_albums = [
        r for r in records
        if r.get('Album') and r.get('Artist') and r['Album'] not in played_albums
    ]

    if not available_albums:
        print("All albums have been posted. Resetting played albums list.")
        played_albums.clear()
        save_played_albums(played_albums)
        available_albums = [
            r for r in records if r.get('Album') and r.get('Artist')
        ]

    album = random.choice(available_albums)
    album_name = album['Album']
    artist_name = album['Artist']
    suggester_name = album.get('Suggester') or "Unknown"

    album_cover_url = None
    spotify_link = None

    try:
        results = sp.search(
            q=f"album:{unidecode(album_name)} artist:{unidecode(artist_name)}",
            type='album',
            limit=1
        )
        albums = results.get('albums', {}).get('items', [])
        if albums:
            album_data = albums[0]
            album_cover_url = album_data['images'][0]['url'] if album_data['images'] else None
            spotify_link = album_data['external_urls']['spotify']
    except Exception as e:
        print(f"Spotify search error for {album_name} by {artist_name}: {e}")

    # Build embed — if no Spotify data, show without link/cover
    if spotify_link:
        embed = discord.Embed(
            title=f"{album_name} — {artist_name}",
            url=spotify_link,
            description=f"💡 Suggested by: **{suggester_name}**\n\nReact with 1️⃣ to 🔟 to rate this album!"
        )
    else:
        embed = discord.Embed(
            title=f"{album_name} — {artist_name}",
            description=f"💡 Suggested by: **{suggester_name}**\n\n(Spotify link not found)\n\nReact with 1️⃣ to 🔟 to rate this album!"
        )

    if album_cover_url:
        embed.set_thumbnail(url=album_cover_url)

    embed.set_footer(text="Ratings will be averaged automatically.")

    message = await channel.send(embed=embed)

    for emoji in RATING_EMOJIS:
        await message.add_reaction(emoji)

    last_posted_message_id = message.id
    ratings_store[last_posted_message_id] = {
        'album': album_name,
        'ratings': {}
    }

    played_albums.add(album_name)
    save_played_albums(played_albums)

    global last_posted_message_id, ratings_store, played_albums

    channel = bot.get_channel(CHANNEL_ID)
    if channel is None:
        print("Could not find the channel. Check CHANNEL_ID.")
        return

    records = sheet.get_all_records(head=2)

    if not records:
        print("No albums found in the Google Sheet.")
        return

    # Filter out albums already played
    available_albums = [
        r for r in records
        if r.get('Album') and r.get('Artist') and r['Album'] not in played_albums
    ]

    if not available_albums:
        # Reset if all played
        print("All albums have been posted. Resetting played albums list.")
        played_albums.clear()
        save_played_albums(played_albums)
        available_albums = [
            r for r in records if r.get('Album') and r.get('Artist')
        ]

    album = random.choice(available_albums)
    album_name = str(album['Album'])
    artist_name = str(album['Artist'])
    suggester_name = str(album.get('Suggester') or "Unknown")

    # Spotify API search
    album_cover_url = None
    spotify_link = None
    try:
        results = sp.search(
            q=f"album:{unidecode(album_name)} artist:{unidecode(artist_name)}",
            type='album',
            limit=1
        )
        albums = results.get('albums', {}).get('items', [])
        if albums:
            album_data = albums[0]
            album_cover_url = album_data['images'][0]['url'] if album_data['images'] else None
            spotify_link = album_data['external_urls']['spotify']
    except Exception as e:
        print(f"Spotify search error: {e}")

    if not spotify_link:
        print(f"Could not find Spotify link for album: {album_name} by {artist_name}")
        return

    embed = discord.Embed(
        title=f"{album_name} — {artist_name}",
        url=spotify_link,
        description=f"💡 Suggested by: **{suggester_name}**\n\nReact with 1️⃣ to 🔟 to rate this album!"
    )
    if album_cover_url:
        embed.set_thumbnail(url=album_cover_url)
    embed.set_footer(text="Ratings will be averaged automatically.")

    message = await channel.send(embed=embed)

    for emoji in RATING_EMOJIS:
        await message.add_reaction(emoji)

    last_posted_message_id = message.id
    ratings_store[last_posted_message_id] = {
        'album': album_name,
        'ratings': {}
    }

    # Mark album as played and save
    played_albums.add(album_name)
    save_played_albums(played_albums)

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

@daily_album_poster.error
async def daily_album_poster_error(error):
    print(f"⚠️ daily_album_poster encountered an error: {error}")
    await asyncio.sleep(10)  # wait a bit before retry
    if not daily_album_poster.is_running():
        print("🔄 Restarting daily_album_poster...")
        daily_album_poster.start()

@bot.command(name="play")
async def play_album(ctx, *, album_name: str):
    """Test Spotify search for a given album."""
    try:
        # Force album_name to string and strip extra spaces
        album_name = str(album_name).strip()

        results = sp.search(
            q=f"album:{unidecode(album_name)}",
            type='album',
            limit=1
        )

        albums = results.get('albums', {}).get('items', [])
        if not albums:
            await ctx.send(f"❌ Could not find an album called `{album_name}` on Spotify.")
            return

        album_data = albums[0]
        artist_name = album_data['artists'][0]['name']
        spotify_link = album_data['external_urls']['spotify']
        album_cover_url = album_data['images'][0]['url'] if album_data['images'] else None

        embed = discord.Embed(
            title=f"{album_data['name']} — {artist_name}",
            url=spotify_link
        )
        if album_cover_url:
            embed.set_thumbnail(url=album_cover_url)

        await ctx.send(embed=embed)

    except Exception as e:
        await ctx.send(f"⚠️ Error searching for `{album_name}`: `{e}`")

@bot.event
async def on_reaction_add(reaction, user):
    await handle_reaction_change(reaction, user, added=True)

@bot.event
async def on_reaction_remove(reaction, user):
    await handle_reaction_change(reaction, user, added=False)

async def handle_reaction_change(reaction, user, added: bool):
    if user.bot:
        return

    message = reaction.message
    if message.id != last_posted_message_id:
        return

    emoji = reaction.emoji
    if emoji not in RATING_EMOJIS:
        return

    rating = RATING_EMOJIS.index(emoji) + 1

    album_rating_data = ratings_store.get(message.id)
    if album_rating_data is None:
        return

    user_ratings = album_rating_data['ratings']

    if added:
        user_ratings[user.id] = rating
    else:
        if user.id in user_ratings and user_ratings[user.id] == rating:
            del user_ratings[user.id]

    if user_ratings:
        average = sum(user_ratings.values()) / len(user_ratings)
        average = round(average, 2)
        rating_count = len(user_ratings)
        new_footer = f"Average rating: {average} ⭐️ from {rating_count} votes."
    else:
        new_footer = "No ratings yet. React with 1️⃣ to 🔟 to rate!"

    embed = message.embeds[0]
    embed.set_footer(text=new_footer)
    await message.edit(embed=embed)

if __name__ == "__main__":
    bot.run(TOKEN)
