# discord-album-bot
just a fun project I wrote with for some friends.<br />
it takes a google sheets file with album names and artists and fires them into a discord channel at random once per day<br />
you can rate them using the emojis from 1-5<br />
it'll average out your ratings in the footer<br />

## Setup

to run, you'll need a .env file with the following:

DISCORD_TOKEN=<br />
CHANNEL_ID= // discord channel ID<br />
GOOGLE_SHEET_NAME= // just the name of your google sheet<br />
GOOGLE_CREDENTIALS_JSON= // needs to be escaped<br />
SPOTIFY_CLIENT_ID=<br />
SPOTIFY_CLIENT_SECRET=<br />

run a pip install and python3 discordAlbumBot.py will get you up and running! :)
