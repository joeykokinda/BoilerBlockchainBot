import discord
import json
import asyncio
import requests
import os
import aiofiles
from datetime import datetime, timedelta
from flask import Flask
import threading

TOKEN = os.getenv('DISCORD_TOKEN')
CHANNEL_ID_STR = os.getenv('CHANNEL_ID', '0')
TWITTER_BEARER_TOKEN = os.getenv('TWITTER_BEARER_TOKEN', '')

if not TOKEN:
    print("ERROR: DISCORD_TOKEN environment variable is not set")
    exit(1)

try:
    CHANNEL_ID = int(CHANNEL_ID_STR)
except ValueError:
    print(f"ERROR: CHANNEL_ID must be a number, got: {CHANNEL_ID_STR}")
    exit(1)

if not TWITTER_BEARER_TOKEN:
    print("WARNING: TWITTER_BEARER_TOKEN not set - Twitter monitoring disabled")

print(f"Config loaded - Channel ID: {CHANNEL_ID}, Twitter token: {'✓' if TWITTER_BEARER_TOKEN else '✗'}")

TWITTER_ACCOUNTS = ["BoilerChain"]
LAST_TWEET_IDS_FILE = "last_tweet_ids.json"
CHECK_INTERVAL = 120  # 2 minutes for testing, will change back to 900 later

intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f"Logged in as {client.user}")
    channel = client.get_channel(CHANNEL_ID)
    if channel:
        try:
            await channel.send("BoilerChain bot is live!")
            print(f"Successfully sent message to channel: {channel.name}")
        except discord.Forbidden:
            print(f"ERROR: Bot doesn't have permission to send messages in #{channel.name}")
        except Exception as e:
            print(f"Error sending message: {e}")
        
        client.loop.create_task(monitor_twitter())
    else:
        print(f"Could not find channel with ID: {CHANNEL_ID}")

@client.event
async def on_message(message):
    if message.author == client.user:
        return
    
    if message.content.startswith('!test'):
        await message.channel.send('Bot is working!')
    
    if message.channel.id == CHANNEL_ID and not message.content.startswith('!'):
        if any(platform in message.content.lower() for platform in ['twitter.com', 'instagram.com', 'linkedin.com', 'x.com']):
            announcement = f"Hey, BoilerChain just posted new content!\n{message.content}"
            await message.channel.send(announcement)
            print(f"Auto-announced post: {message.content[:50]}...")

async def get_latest_tweets(username, limit=5):
    if not TWITTER_BEARER_TOKEN:
        print(f"No Twitter API key configured. Skipping @{username}")
        return []
    
    try:
        user_url = f"https://api.twitter.com/2/users/by/username/{username}"
        headers = {"Authorization": f"Bearer {TWITTER_BEARER_TOKEN}"}
        
        user_response = requests.get(user_url, headers=headers)
        if user_response.status_code == 429:
            print(f"Rate limited by Twitter API for @{username}. Waiting...")
            return []
        elif user_response.status_code != 200:
            print(f"Error getting user ID for @{username}: {user_response.status_code}")
            return []
        
        user_data = user_response.json()
        if "data" not in user_data:
            print(f"User @{username} not found")
            return []
        
        user_id = user_data["data"]["id"]
        
        tweets_url = f"https://api.twitter.com/2/users/{user_id}/tweets"
        params = {
            "max_results": limit,
            "tweet.fields": "created_at,public_metrics",
            "exclude": "retweets,replies"
        }
        
        tweets_response = requests.get(tweets_url, headers=headers, params=params)
        if tweets_response.status_code == 429:
            print(f"Rate limited by Twitter API for @{username} tweets. Waiting...")
            return []
        elif tweets_response.status_code != 200:
            print(f"Error getting tweets for @{username}: {tweets_response.status_code}")
            return []
        
        tweets_data = tweets_response.json()
        tweets = []
        
        if "data" in tweets_data:
            for tweet in tweets_data["data"]:
                tweets.append({
                    'url': f"https://twitter.com/{username}/status/{tweet['id']}",
                    'content': tweet['text'],
                    'date': datetime.fromisoformat(tweet['created_at'].replace('Z', '+00:00')),
                    'id': tweet['id']
                })
        
        return tweets
    except Exception as e:
        print(f"Error fetching tweets for {username}: {e}")
        return []

async def post_social_update(platform, username, post_url, content_preview=""):
    channel = client.get_channel(CHANNEL_ID)
    if channel:
        if platform.lower() == "twitter":
            message = f"Hey, {username} just posted a new Tweet!\n{post_url}"
        elif platform.lower() == "instagram":
            message = f"Hey, {username} just posted a new shot!\n{post_url}"
        elif platform.lower() == "linkedin":
            message = f"Hey, {username} just posted on LinkedIn!\n{post_url}"
        else:
            message = f"Hey, new post from {username}!\n{post_url}"
        
        await channel.send(message)
        print(f"Posted to Discord: {message[:100]}...")

async def load_last_tweet_ids():
    try:
        if os.path.exists(LAST_TWEET_IDS_FILE):
            async with aiofiles.open(LAST_TWEET_IDS_FILE, 'r') as f:
                content = await f.read()
                return json.loads(content)
        return {}
    except Exception as e:
        print(f"Error loading last tweet IDs: {e}")
        return {}

async def save_last_tweet_ids(tweet_ids):
    try:
        async with aiofiles.open(LAST_TWEET_IDS_FILE, 'w') as f:
            await f.write(json.dumps(tweet_ids, indent=2))
        print(f"Saved last tweet IDs: {tweet_ids}")
    except Exception as e:
        print(f"Error saving last tweet IDs: {e}")

async def monitor_twitter():
    print("Starting continuous Twitter monitoring...")
    last_tweet_ids = await load_last_tweet_ids()
    print(f"Loaded last tweet IDs: {last_tweet_ids}")
    
    while True:
        try:
            new_posts_found = 0
            updated_tweet_ids = last_tweet_ids.copy()
            
            for account in TWITTER_ACCOUNTS:
                print(f"Checking tweets for @{account}...")
                tweets = await get_latest_tweets(account, 5)
                
                if not tweets:
                    continue
                
                last_seen_id = last_tweet_ids.get(account, "0")
                
                new_tweets = []
                for tweet in tweets:
                    # Convert both to strings for comparison to avoid int/string issues
                    if str(tweet['id']) > str(last_seen_id):
                        new_tweets.append(tweet)
                        print(f"New tweet found from @{account}: {tweet['url']}")
                        print(f"Tweet ID: {tweet['id']} vs Last seen: {last_seen_id}")
                
                for tweet in reversed(new_tweets):
                    await post_social_update("twitter", account, tweet['url'])
                    new_posts_found += 1
                    await asyncio.sleep(1)
                
                if tweets:
                    updated_tweet_ids[account] = tweets[0]['id']
                
                await asyncio.sleep(2)
            
            if updated_tweet_ids != last_tweet_ids:
                await save_last_tweet_ids(updated_tweet_ids)
                last_tweet_ids = updated_tweet_ids
            
            if new_posts_found > 0:
                print(f"Posted {new_posts_found} new tweets to Discord")
            else:
                print("No new tweets found")
                
        except Exception as e:
            print(f"Error in Twitter monitoring: {e}")
        
        print(f"Waiting {CHECK_INTERVAL} seconds before next check...")
        await asyncio.sleep(CHECK_INTERVAL)

def start_health_server():
    app = Flask(__name__)
    
    @app.route('/health')
    def health_check():
        return "Bot is running", 200
    
    @app.route('/')
    def home():
        return "BoilerChain Discord Bot is running", 200
    
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)

if __name__ == "__main__":
    # Start health server in background thread
    health_thread = threading.Thread(target=start_health_server, daemon=True)
    health_thread.start()
    
    # Start Discord bot
    client.run(TOKEN)