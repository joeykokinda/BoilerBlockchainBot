import discord
import json
import asyncio
import requests
import time
import os
from datetime import datetime, timedelta

# Load config - Railway uses environment variables
TOKEN = os.getenv('DISCORD_TOKEN')
CHANNEL_ID_STR = os.getenv('CHANNEL_ID', '0')
TWITTER_BEARER_TOKEN = os.getenv('TWITTER_BEARER_TOKEN', '')

# Validate environment variables
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

# Twitter accounts to monitor
TWITTER_ACCOUNTS = ["BoilerChain"]  # Add your accounts here
CHECK_INTERVAL = 300  # Check every 5 minutes
last_check_time = {}

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
            print("Fix: Make sure bot has 'Send Messages' permission in that channel")
        except Exception as e:
            print(f"Error sending message: {e}")
        
        # Start monitoring Twitter
        client.loop.create_task(monitor_twitter())
    else:
        print(f"Could not find channel with ID: {CHANNEL_ID}")
        print("Fix: Make sure the channel ID is correct and bot is in the server")

@client.event
async def on_message(message):
    # Don't respond to own messages
    if message.author == client.user:
        return
    
    # Simple test command
    if message.content.startswith('!test'):
        await message.channel.send('Bot is working!')

async def get_latest_tweets(username, limit=5):
    """Get latest tweets from a username using Twitter API"""
    if not TWITTER_BEARER_TOKEN:
        print(f"No Twitter API key configured. Skipping @{username}")
        return []
    
    try:
        # Get user ID first
        user_url = f"https://api.twitter.com/2/users/by/username/{username}"
        headers = {"Authorization": f"Bearer {TWITTER_BEARER_TOKEN}"}
        
        user_response = requests.get(user_url, headers=headers)
        if user_response.status_code != 200:
            print(f"Error getting user ID for @{username}: {user_response.status_code}")
            return []
        
        user_data = user_response.json()
        if "data" not in user_data:
            print(f"User @{username} not found")
            return []
        
        user_id = user_data["data"]["id"]
        
        # Get recent tweets
        tweets_url = f"https://api.twitter.com/2/users/{user_id}/tweets"
        params = {
            "max_results": limit,
            "tweet.fields": "created_at,public_metrics",
            "exclude": "retweets,replies"
        }
        
        tweets_response = requests.get(tweets_url, headers=headers, params=params)
        if tweets_response.status_code != 200:
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
    """Post social media update to Discord"""
    channel = client.get_channel(CHANNEL_ID)
    if channel:
        if platform.lower() == "twitter":
            message = f"Hey @everyone, {username} just posted a new Tweet!\n{post_url}"
        elif platform.lower() == "instagram":
            message = f"Hey @everyone, {username} just posted a new shot!\n{post_url}"
        elif platform.lower() == "linkedin":
            message = f"Hey @everyone, {username} just posted on LinkedIn!\n{post_url}"
        else:
            message = f"Hey @everyone, new post from {username}!\n{post_url}"
        
        await channel.send(message)

async def monitor_twitter():
    """Monitor Twitter accounts for new posts"""
    print("Starting Twitter monitoring...")
    
    # Initialize last check times
    for account in TWITTER_ACCOUNTS:
        last_check_time[account] = datetime.now() - timedelta(hours=1)
    
    while True:
        try:
            for account in TWITTER_ACCOUNTS:
                print(f"Checking tweets for @{account}...")
                tweets = await get_latest_tweets(account, 5)
                
                for tweet in tweets:
                    # Only post tweets newer than our last check
                    if tweet['date'] > last_check_time[account]:
                        print(f"New tweet found from @{account}: {tweet['url']}")
                        await post_social_update("twitter", account, tweet['url'])
                        
                # Update last check time
                last_check_time[account] = datetime.now()
                
                # Small delay between accounts
                await asyncio.sleep(2)
                
        except Exception as e:
            print(f"Error in Twitter monitoring: {e}")
        
        # Wait before next check
        print(f"Waiting {CHECK_INTERVAL} seconds before next check...")
        await asyncio.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    client.run(TOKEN)