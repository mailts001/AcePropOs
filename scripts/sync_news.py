#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from data.news_pipeline import sync_news, get_sentiment_index
import json

articles = sync_news()
print(f"\nSentiment Index:")
print(json.dumps(get_sentiment_index(), indent=2))
