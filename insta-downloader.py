import instaloader
from datetime import datetime, timedelta
import os
import json
import shutil
import logging
import pytz
import time
import random
import sys
import requests
from functools import partial
from requests.exceptions import RequestException
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

# Set up logging
logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s - %(levelname)s - %(message)s',
                    handlers=[
                        logging.FileHandler("instagram_downloader.log"),
                        logging.StreamHandler()
                    ])
logger = logging.getLogger(__name__)

# Base directory for storing posts
BASE_DIR = "instagram_posts"

# Set the download interval
DOWNLOAD_INTERVAL_HOURS = 48  # Set this to the desired interval

# Log request headers
def log_url(r, *args, **kwargs):
    logger.debug(f"Request URL: {r.url}")
    logger.debug(f"Request headers: {r.request.headers}")

# Patch the requests library to log all requests
requests.get = partial(requests.get, hooks={'response': log_url})
requests.post = partial(requests.post, hooks={'response': log_url})

# Initialize Instaloader
L = instaloader.Instaloader(
    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    dirname_pattern=os.path.join(BASE_DIR, "{profile}", "{shortcode}"),
    filename_pattern="{date_utc:%Y-%m-%d_%H-%M-%S}_UTC",
    download_video_thumbnails=False,
    compress_json=False,
    save_metadata=True
)

# Load session cookies (uncomment and use if you have a session file)
# L.load_session_from_file('YOUR_USERNAME')

def download_post_completely(post, username):
    try:
        post_dir = os.path.join(BASE_DIR, username, post.shortcode)
        os.makedirs(post_dir, exist_ok=True)
        
        # Download all elements of the post
        L.download_post(post, target=post_dir)
        
        # Create a custom JSON file with post metadata
        metadata = {
            "id": post.shortcode,
            "username": username,
            "timestamp": post.date.isoformat(),
            "caption": post.caption,
            "media_type": post.typename,
            "likes": post.likes,
            "comments": post.comments
        }
        
        with open(os.path.join(post_dir, f"{post.date_utc:%Y-%m-%d_%H-%M-%S}_UTC_metadata.json"), "w") as f:
            json.dump(metadata, f, indent=2)
        
        logger.info(f"Successfully downloaded post {post.shortcode}")
        return True
    except Exception as e:
        logger.error(f"Error downloading post {post.shortcode}: {str(e)}")
        # If there's an error, delete the partially downloaded content
        shutil.rmtree(post_dir, ignore_errors=True)
        return False

def download_post_with_retry(post, username, max_retries=3):
    for attempt in range(max_retries):
        try:
            time.sleep(random.uniform(2, 5))  # Random delay between 2-5 seconds
            return download_post_completely(post, username)
        except RequestException as e:
            logger.warning(f"Request failed on attempt {attempt + 1}: {str(e)}")
            if attempt < max_retries - 1:
                time.sleep(random.uniform(10, 30))  # Longer delay between retries
            else:
                logger.error(f"Max retries reached for post {post.shortcode}")
                return False

def download_recent_posts(usernames, hours):
    UNTIL = datetime.now(pytz.UTC)
    SINCE = UNTIL - timedelta(hours=hours)
    
    logger.info(f"Downloading posts from {SINCE} to {UNTIL} (UTC)")
    
    for username in usernames:
        try:
            logger.info(f"Processing account: {username}")
            time.sleep(random.uniform(5, 10))  # Random delay between 5-10 seconds
            profile = instaloader.Profile.from_username(L.context, username)
            logger.debug(f"Profile retrieved for {username}")
            
            # Collect and sort posts
            posts = list(profile.get_posts())
            posts.sort(key=lambda x: x.date, reverse=True)
            logger.debug(f"Collected and sorted {len(posts)} posts for {username}")
            
            post_count = 0
            for post in posts:
                post_date = post.date.replace(tzinfo=pytz.UTC)
                logger.debug(f"Examining post {post.shortcode} from {username}, posted at {post_date}")
                if SINCE <= post_date <= UNTIL:
                    logger.info(f"Attempting to download post {post.shortcode} from {username}")
                    
                    if download_post_with_retry(post, username):
                        post_count += 1
                    else:
                        logger.warning(f"Skipped incomplete post {post.shortcode}")
                else:
                    logger.debug(f"Skipping post {post.shortcode}, posted at {post_date} (outside time range)")
            
            logger.info(f"Downloaded {post_count} posts for {username}")
            
            if post_count == 0:
                logger.warning(f"No posts found for {username} in the specified time range")
                
        except Exception as e:
            logger.error(f"Error processing account {username}: {str(e)}", exc_info=True)

def clear_local_storage():
    if os.path.exists(BASE_DIR):
        shutil.rmtree(BASE_DIR)
    os.makedirs(BASE_DIR)
    logger.info("Local storage cleared")

def run_scheduled_job():
    accounts = ["uncover.ai"]  # Start with just one account for testing

    try:
        clear_local_storage()  # Clear existing data
        download_recent_posts(accounts, DOWNLOAD_INTERVAL_HOURS)
        logger.info(f"Scheduled job completed successfully. Downloaded posts from last {DOWNLOAD_INTERVAL_HOURS} hours.")
    except Exception as e:
        logger.error(f"Unhandled exception in scheduled job: {str(e)}", exc_info=True)

# Usage
if __name__ == "__main__":
    # Log Python and Instaloader versions
    logger.info(f"Python version: {sys.version}")
    logger.info(f"Instaloader version: {instaloader.__version__}")

    # Create a scheduler
    scheduler = BlockingScheduler()

    # Schedule the job to run every DOWNLOAD_INTERVAL_HOURS
    scheduler.add_job(
        run_scheduled_job,
        trigger=IntervalTrigger(hours=DOWNLOAD_INTERVAL_HOURS),
        next_run_time=datetime.now()  # This will make it run immediately on start
    )

    logger.info(f"Scheduler started. Will run every {DOWNLOAD_INTERVAL_HOURS} hours.")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped.")
