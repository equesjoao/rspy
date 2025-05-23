import feedparser
import json
import os
import requests
import subprocess
import webbrowser
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
import time
import logging
from urllib.parse import urljoin

# --- Configuration ---
MAX_AGE_HOURS = 24  # Articles older than this won't be shown
MAX_WORKERS = 20
REQUEST_TIMEOUT = 5
RETRY_ATTEMPTS = 2
CACHE_DIR = ".cache"
CACHE_FILE = os.path.join(CACHE_DIR, "rss_cache.json")

# --- Logging Configuration
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# --- Cache Management ---

def read_cache(current_feed_names):
    """Load and filter cached articles based on current feed names."""
    if not os.path.exists(CACHE_FILE):
        return []
    try:
        with open(CACHE_FILE, 'r') as f:
            cache_data = json.load(f)

        cached_articles = cache_data.get("articles", [])
        current_time = datetime.now()
        age_limit = timedelta(hours=MAX_AGE_HOURS)

        valid_articles = [
            a for a in cached_articles
            if current_time - datetime.fromisoformat(a['timestamp']) <= age_limit
            and a['feed'] in current_feed_names
        ]
        print(f"Loaded {len(valid_articles)} cached articles.")
        return valid_articles
    except Exception as e:
        print(f"Error reading cache: {e}")
        return []

def write_cache(articles):
    """Save articles with timestamp."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache_data = {
        "timestamp": datetime.now().isoformat(),
        "articles": articles
    }
    try:
        with open(CACHE_FILE, 'w') as f:
            json.dump(cache_data, f, indent=2)
    except Exception as e:
        print(f"Error writing cache: {e}")

# --- Feed Fetching ---

def fetch_feed(feed):
    """Fetch and parse a single feed."""
    name = feed.get('name')
    url = feed.get('url')
    if not name or not url:
        return []

    print(f"Fetching {name}...")

    try:
        headers = {'User-Agent': 'RSSBrowser/1.0'}
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        parsed_feed = feedparser.parse(response.content)
    except Exception as e:
        print(f"Error fetching {name}: {e}")
        return []

    if parsed_feed.bozo:
        print(f"Error parsing feed {name}: {parsed_feed.bozo_exception}")
        return []

    current_time = datetime.now()
    age_limit = timedelta(hours=MAX_AGE_HOURS)
    new_articles = []

    for entry in parsed_feed.entries:
        if 'published_parsed' not in entry:
            continue
        try:
            published_time = datetime.fromtimestamp(time.mktime(entry.published_parsed))
        except Exception:
            continue

        if current_time - published_time > age_limit:
            continue

        new_articles.append({
            'feed': name,
            'title': entry.get('title', 'No title'),
            'link': entry.get('link', 'No link'),
            'timestamp': published_time.isoformat()
        })

    return new_articles


def fetch_feeds(feeds):
    """Fetch feeds concurrently using provided feed list."""
    results = []

    print("Fetching feeds concurrently...")
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(fetch_feed, feed) for feed in feeds]
        for future in futures:
            try:
                results.extend(future.result())
            except Exception as e:
                print(f"Error in feed fetch thread: {e}")

    return results
# --- Article Selection ---

def get_fzf_selection(options):
    """Use fzf to select an article."""
    if not options:
        print("No articles found.")
        return None

    fzf = subprocess.Popen(
        ['fzf', '--prompt=Select Article >'],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    stdout, _ = fzf.communicate(input='\n'.join(options).encode('utf-8'))
    return stdout.decode('utf-8').strip() if fzf.returncode == 0 else None

# --- Main Function ---

def main():
    # Load config first
    try:
        with open('config.json', 'r') as f:
            config = json.load(f)
    except Exception as e:
        print(f"Error loading config: {e}")
        return

    feeds = config.get('feeds', [])
    current_feed_names = {feed['name'] for feed in feeds if 'name' in feed}

    # Read cache with current feeds
    cached_articles = read_cache(current_feed_names)

    # Fetch new articles
    new_articles = fetch_feeds(feeds)

    # Merge new and cached articles
    seen_links = set()
    merged_articles = []

    # Add new articles first to prioritize newer ones
    for a in new_articles:
        if a['link'] not in seen_links and a['link'] != 'No link':
            seen_links.add(a['link'])
            merged_articles.append(a)

    # Add cached articles not already added
    for a in cached_articles:
        if (
            a['link'] not in seen_links
            and a['link'] != 'No link'
            and a['feed'] in current_feed_names
        ):
            seen_links.add(a['link'])
            merged_articles.append(a)

    # Update cache with merged articles
    write_cache(merged_articles)

    # Cleanup
    if merged_articles:
        write_cache(merged_articles)
    else:
        if os.path.exists(CACHE_FILE):
            os.remove(CACHE_FILE)
        print("No valid articles to cache. Cache file removed.")

    # ... rest of the main function
    if not merged_articles:
        print("No articles found.")
        return

    # Format for fzf
    fzf_options = [f"{a['feed']} | {a['title']}" for a in merged_articles]

    while True:
        selected = get_fzf_selection(fzf_options)
        if not selected:
            print("Exiting...")
            break

        for article in merged_articles:
            if f"{article['feed']} | {article['title']}" == selected:
                link = article['link']
                if link and link != 'No link':
                    print(f"\nOpening in browser: {link}\n")
                    webbrowser.open(link)
                else:
                    print("\nThis article does not have a valid link.\n")
                break

if __name__ == "__main__":
    main()
