"""
NewsIntelAgent — processes Singapore property news for sentiment, policy alerts,
and market signals. The Edge SG + BT + CNA feeds this agent.
Publishes daily Sentiment Index to Telegram (free tier moat signal).
"""

import json
from agents.base_agent import BaseAgent
from data.news_pipeline import (
    get_latest_articles, get_sentiment_index, sync_news, get_opportunity_articles
)


class NewsIntelAgent(BaseAgent):
    name = "NewsIntelAgent"
    preferred_mode = "free"  # Bulk text analysis — use free Gemini tier

    def get_market_briefing(self, max_articles: int = 10) -> dict:
        """
        Daily market briefing: sentiment index + top stories + policy alerts.
        LLM generates 3-sentence narrative using free Gemini tier.
        """
        sentiment = get_sentiment_index()
        articles = get_latest_articles(limit=max_articles)
        policy_articles = get_latest_articles(limit=20, policy_only=True)

        briefing = {
            "sentiment": sentiment,
            "top_stories": [
                {"title": a["title"], "source": a["source"], "link": a["link"]}
                for a in articles[:5]
            ],
            "policy_alerts": [
                {"title": a["title"], "source": a["source"], "link": a["link"]}
                for a in policy_articles[:3]
            ],
        }

        if articles:
            briefing["narrative"] = self._generate_briefing_narrative(sentiment, articles[:5])

        return briefing

    def detect_policy_changes(self) -> list[dict]:
        """
        Scan recent news for ABSD, cooling measures, MAS policy changes.
        Returns list of flagged policy articles with impact assessment.
        Uses LLM to classify impact — important enough to use quality mode here.
        """
        policy_articles = get_latest_articles(limit=30, policy_only=True)
        if not policy_articles:
            return []

        flagged = []
        for article in policy_articles[:5]:
            impact = self._assess_policy_impact(article)
            flagged.append({
                "title": article["title"],
                "source": article["source"],
                "link": article["link"],
                "pub_date": article["pub_date"],
                "impact": impact,
            })

        return flagged

    def get_district_news_sentiment(self, district: int) -> dict:
        """
        Filter news for mentions of a specific district and return sentiment.
        Used by ValuationAgent to add news context to valuations.
        """
        district_keywords = {
            9: ["orchard", "river valley", "d9"],
            10: ["bukit timah", "holland", "d10"],
            11: ["novena", "thomson", "d11"],
            15: ["east coast", "katong", "marine parade", "d15"],
            19: ["hougang", "punggol", "sengkang", "d19"],
            23: ["bukit panjang", "choa chu kang", "d23"],
        }
        keywords = district_keywords.get(district, [f"district {district}", f"d{district}"])
        articles = get_latest_articles(limit=100)
        relevant = [
            a for a in articles
            if any(kw in (a["title"] + a["description"]).lower() for kw in keywords)
        ]

        if not relevant:
            return {"district": district, "sentiment": "neutral", "article_count": 0}

        avg_sentiment = sum(a["sentiment_score"] for a in relevant) / len(relevant)
        return {
            "district": district,
            "sentiment_score": round(avg_sentiment, 3),
            "sentiment_label": "Positive" if avg_sentiment > 0.1 else "Negative" if avg_sentiment < -0.1 else "Neutral",
            "article_count": len(relevant),
            "top_article": relevant[0]["title"] if relevant else None,
        }

    def format_telegram_daily(self) -> str:
        """
        Format daily Telegram message for the free deals channel.
        This is the public funnel — high-quality, free, drives subscriptions.
        """
        sentiment = get_sentiment_index()
        articles = get_latest_articles(limit=5)
        opportunities = get_opportunity_articles()

        emoji_map = {
            "Bullish": "📈", "Mildly Bullish": "🟢",
            "Neutral": "⚪", "Mildly Bearish": "🟡", "Bearish": "📉"
        }
        emoji = emoji_map.get(sentiment["label"], "⚪")

        lines = [
            f"🏠 *PropertyOS Daily Briefing*",
            f"",
            f"{emoji} *Market Sentiment: {sentiment['label']}* ({sentiment['score']:+.2f})",
            f"Based on {sentiment['article_count']} articles today",
        ]

        if sentiment.get("top_policy"):
            lines += ["", f"⚠️ *Policy Alert:*", f"_{sentiment['top_policy']}_"]

        if articles:
            lines += ["", "📰 *Top Stories:*"]
            for a in articles[:3]:
                lines.append(f"• [{a['title'][:60]}...]({a['link']})")

        if opportunities:
            lines += ["", "💡 *Potential Opportunities:*"]
            for a in opportunities[:2]:
                lines.append(f"• {a['title'][:70]}...")

        lines += [
            "",
            "🔍 Want full deal analysis with PSF comparisons?",
            "→ [PropertyOS Premium](https://propertyos.sg)",
        ]

        return "\n".join(lines)

    def _generate_briefing_narrative(self, sentiment: dict, articles: list) -> str:
        """Uses free Gemini tier — narrative for daily briefing."""
        headlines = "\n".join(f"- {a['title']}" for a in articles)
        prompt = f"""
Write a 2-sentence Singapore property market briefing for investors based on today's news.
Sentiment index: {sentiment['label']} ({sentiment['score']})
Headlines:
{headlines}

Be concise and factual. No markdown. Focus on what investors should watch.
"""
        resp = self._llm(prompt, max_tokens=120, use_cache=True)
        return resp.content.strip()

    def _assess_policy_impact(self, article: dict) -> dict:
        """Classify policy impact on buyers, sellers, investors. Uses quality mode."""
        prompt = f"""
Assess the impact of this Singapore property policy news on different buyer types.
Title: {article['title']}
Description: {article['description']}

Respond in JSON with this exact structure:
{{
  "impact_level": "high|medium|low",
  "affects": ["buyers"|"sellers"|"investors"|"landlords"|"agents"],
  "direction": "positive|negative|neutral",
  "one_line": "plain English impact summary under 15 words"
}}
"""
        resp = self._llm(prompt, max_tokens=150, use_cache=True, force_mode="quality")
        return self._parse_json_response(resp.content)
