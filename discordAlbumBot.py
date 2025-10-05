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

# --- Environment Variables ---
TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
SHEET_NAME = os.getenv("GOOGLE_SHEET_NAME")
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON")

SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")

# --- Google Sheets Setup ---
google_creds = json.loads(GOOGLE_CREDENTIALS_JSON)
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_dict(google_creds, scope)
gc = gspread.authorize(creds)
sheet = gc.open(SHEET_NAME).sheet1  # first sheet

# --- Spotify Setup ---
spotify_auth_manager = SpotifyClientCredentials(
    client_id=SPOTIFY_CLIENT_ID, client_secret=SPOTIFY_CLIENT_SECRET
)
sp = spotipy.Spotify(auth_manager=spotify_auth_manager)

# --- Discord Setup ---
intents = discord.Intents.default()
intents.message_content = True
intents.messages = True
intents.reactions = True
bot = commands.Bot(command_prefix="!", intents=intents)

POST_TIME = time(hour=8, minute=0)
RATING_EMOJIS = ['1️⃣','2️⃣','3️⃣','4️⃣','5️⃣','6️⃣','7️⃣','8️⃣','9️⃣','🔟']

last_posted_message_id = None
ratings_store = {}

# --- Helper Functions ---
def get_unplayed_albums():
    """Return all albums that don't have 'Yes' in the Played column."""
    records = sheet.get_all_records(head=2)
    unplayed = [r for r in records if not str(r.get("Played", "")).strip().lower() in ["yes", "y", "true", "1"]]
    return unplayed

def mark_album_as_played(album_name):
    """Mark the album as played in the sheet."""
    cell = sheet.find(album_name)
    if cell:
        row = cell.row
        headers = sheet.row_values(2)
        if "Played" in headers:
            played_col = headers.index("Played") + 1
            sheet.update_cell(row, played_col, "Yes")
        else:
            print("No 'Played' column found in sheet.")

# --- Post Album Function ---
async def post_random_album():
    global last_posted_message_id, ratings_store

    channel = bot.get_channel(CHANNEL_ID)
    if channel is None:
        print("Could not find the channel. Check CHANNEL_ID.")
        return

    unplayed_albums = get_unplayed_albums()

    if not unplayed_albums:
        print("No unplayed albums left! Reset or add more to the sheet.")
        return

    album = random.choice(unplayed_albums)
    album_name = album.get("Album")
    artist_name = album.get("Artist")
    suggester_name = album.get("Suggester") or "Unknown"

    # Spotify search
    album_cover_url = None
    spotify_link = None
    try:
        query = f"album:{unidecode(album_name)} artist:{unidecode(artist_name)}"
        results = sp.search(q=query, type='album', limit=1)
        albums = results.get('albums', {}).get('items', [])
        if albums:
            album_data = albums[0]
            album_cover_url = album_data['images'][0]['url'] if album_data['images'] else None
            spotify_link = album_data['external_urls']['spotify']
    except Exception as e:
        print(f"Spotify search error: {e}")

    # Create the embed — even if Spotify fails
    embed_description = f"💡 Suggested by: **{suggester_name}**\n\nReact with 1️⃣ to 🔟 to rate this album!"
    embed = discord.Embed(title=f"{album_name} — {artist_name}", description=embed_description)

    if spotify_link:
        embed.url = spotify_link
    if album_cover_url:
        embed.set_thumbnail(url=album_cover_url)
    else:
        embed.set_thumbnail(url="https://upload.wikimedia.org/wikipedia/commons/6/65/No-Image-Placeholder.svg")

    embed.set_footer(text="Ratings will be averaged automatically.")

    message = await channel.send(embed=embed)

    for emoji in RATING_EMOJIS:
        await message.add_reaction(emoji)

    last_posted_message_id = message.id
    ratings_store[last_posted_message_id] = {'album': album_name, 'ratings': {}}

    # Mark as played in Google Sheets
    mark_album_as_played(album_name)

# --- Task Loop ---
@tasks.loop(hours=24)
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
async def on_ready():
    print(f"Logged in as {bot.user}!")
    if not daily_album_poster.is_running():
        daily_album_poster.start()

# --- Test Command ---
@bot.command()
async def test(ctx):
    """Manually trigger a test album post."""
    await ctx.send("🎵 Testing album post now!")
    await post_random_album()

# --- Rating Handlers ---
@bot.event
async def on_reaction_add(reaction, user):
    await handle_reaction_change(reaction, user, added=True)

@bot.event
async def on_reaction_remove(reaction, user):
    await handle_reaction_change(reaction, user, added=False)

async def handle_reaction_change(reaction, user, added: bool):
    if user.bot or reaction.message.id != last_posted_message_id:
        return

    emoji = reaction.emoji
    if emoji not in RATING_EMOJIS:
        return

    rating = RATING_EMOJIS.index(emoji) + 1
    album_rating_data = ratings_store.get(reaction.message.id)
    if not album_rating_data:
        return

    user_ratings = album_rating_data['ratings']
    if added:
        user_ratings[user.id] = rating
    else:
        user_ratings.pop(user.id, None)

    if user_ratings:
        avg = round(sum(user_ratings.values()) / len(user_ratings), 2)
        footer = f"Average rating: {avg} ⭐️ from {len(user_ratings)} votes."
    else:
        footer = "No ratings yet. React with 1️⃣ to 🔟 to rate!"

    embed = reaction.message.embeds[0]
    embed.set_footer(text=footer)
    await reaction.message.edit(embed=embed)

# --- Run Bot ---
if __name__ == "__main__":
    bot.run(TOKEN)
