from typing import List, Dict, Any
from pydantic import BaseModel, Field
import json
from retry import retry
from json_repair import repair_json

from src.llm import call_llm

# Helper function for pooling embeddings
def average_pool(last_hidden_states, attention_mask):
    last_hidden = last_hidden_states.masked_fill(~attention_mask[..., None].bool(), 0.0)
    return last_hidden.sum(dim=1) / attention_mask.sum(dim=1)[..., None]

# Models
class Story(BaseModel):
    id: int = Field(description="id of the story")
    title: str = Field(description="title of the story")
    importance: int = Field(
        ge=1,
        le=10,
        description="global significance (1=minor local event, 10=major global impact)",
    )
    articles: List[int] = Field(description="list of article ids in the story")

class StoryValidation(BaseModel):
    answer: str = Field(description="Type of story: single_story, collection_of_stories, pure_noise, no_stories")
    title: str = Field(None, description="Title for single story")
    importance: int = Field(None, ge=1, le=10, description="Importance score for single story")
    outliers: List[int] = Field(default_factory=list, description="Outlier article IDs")
    stories: List[Story] = Field(None, description="List of stories for collection")

# Prompts
brief_system_prompt = """
Adopt the persona of an exceptionally well-informed, highly analytical, and subtly world-weary intelligence briefer. Imagine you possess near-instantaneous access to the firehose of global information, coupled with the processing power to sift, connect, and contextualize it all. But you're far more than just a data aggregator.

**Your Core Identity:** You are the indispensable analyst – the one who reads between the lines, understands the subtext, connects seemingly unrelated events, and sees the underlying currents shaping the world. You possess a deep, almost intuitive grasp of geopolitics, economics, and human behavior, grounded in relentless observation and pattern recognition. You're not impressed by titles or official narratives; you focus on incentives, capabilities, and the often-messy reality on the ground.

**Your Analytical Voice & Tone:**

1.  **Direct & Grounded:** Speak plainly, like an experienced hand briefing a trusted colleague. Your authority comes from the clarity and depth of your analysis, not from formality. Facts are your foundation, but insight is your currency.
2.  **Insight over Summary:** Don't just report *what* happened. Explain *why* it matters, *who* benefits, *what* might happen next (and the *why* behind that too). Identify the signal in the noise, assess motivations, flag inconsistencies, and highlight underappreciated angles. Deliver a clear, defensible "take."
3.  **Economical & Precise Language:** Channel a spirit akin to Hemingway: clarity, conciseness, strong verbs. Every sentence should serve a purpose. Avoid jargon, buzzwords, euphemisms, and hedging ("it seems," "potentially," "could possibly"). State your analysis with confidence, grounded in the available information. If there's ambiguity, state *that* clearly too, but don't waffle.
4.  **Understated Wit & Skepticism:** Your perspective is sharp, informed by seeing countless cycles of events. A dry, observational wit might surface naturally when confronting absurdity, spin, or predictable human folly. This isn't about forced jokes; it's the wry acknowledgment of reality by someone who's paying close attention. Zero tolerance for BS, propaganda, or obfuscation.
5.  **Engaging Clarity:** The ultimate goal is to deliver intelligence that is not only accurate and insightful but also *compelling* and *pleasant* to read. The quality of the writing should match the quality of the analysis. Make complex topics understandable and genuinely interesting through sheer clarity and perceptive commentary.

**Think of yourself as:** The definitive source for understanding *what's actually going on*. You have the raw data, the analytical engine, and the seasoned perspective to cut through the clutter and deliver the essential, unvarnished intelligence with precision, insight, and a distinct, trustworthy voice. You make the complex clear, and the important engaging.
"""

@retry(tries=3, delay=2, backoff=2, jitter=2, max_delay=20)
def process_story(cluster, events):
    """Process a single story cluster"""
    story_articles_ids = cluster["articles_ids"]
    
    story_article_md = ""
    for article_id in story_articles_ids:
        article = next((e for e in events if e.id == article_id), None)
        if article is None:
            continue
        story_article_md += f"- (#{article.id}) [{article.title}]({article.url})\n"
    story_article_md = story_article_md.strip()

    prompt = f"""
# Task
Determine if the following collection of news articles is:
1) A single story - A cohesive narrative where all articles relate to the same central event/situation and its direct consequences
2) A collection of stories - Distinct narratives that should be analyzed separately
3) Pure noise - Random articles with no meaningful pattern
4) No stories - Distinct narratives but none of them have more than 3 articles

# Important clarification
A "single story" can still have multiple aspects or angles. What matters is whether the articles collectively tell one broader narrative where understanding each part enhances understanding of the whole.

# Handling outliers
- For single stories: You can exclude true outliers in an "outliers" array
- For collections: Focus **only** on substantive stories (3+ articles). Ignore one-off articles or noise.

# Title guidelines
- Titles should be purely factual, descriptive and neutral
- Include necessary context (region, countries, institutions involved)
- No editorialization, opinion, or emotional language
- Format: "[Subject] [action/event] in/with [location/context]"

# Input data
Articles (format is (#id) [title](url)):
{story_article_md}

# Output format
Return your final answer in JSON format:
```json
{{
    "answer": "single_story" | "collection_of_stories" | "pure_noise",
    // single_story_start: if answer is "single_story", include the following fields:
    "title": "title of the story",
    "importance": 1-10, // global significance (1=minor local event, 10=major global impact)
    "outliers": [] // array of article ids to exclude as unrelated
    // single_story_end
    // collection_of_stories_start: if answer is "collection_of_stories", include the following fields:
    "stories": [
        {{
            "id": 0, // unique identifier for the story
            "title": "title of the story",
            "importance": 1-10, // global significance scale
            "articles": [] // list of article ids in the story (**only** include substantial stories with **3+ articles**)
        }},
        ...
    ]
    // collection_of_stories_end
}}
```
"""

    answer, usage = call_llm(
        model="gemini-2.0-flash",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )

    try:
        assert "```json" in answer
        answer = answer.split("```json")[1]
        if answer.endswith("```"):
            answer = answer[:-3]
        answer = answer.strip()
        answer = repair_json(answer)
        answer = json.loads(answer)
        parsed = StoryValidation(**answer)
    except Exception as e:
        print(f"Error parsing story: {e}")
        print(cluster)
        print(answer)
        raise e

    return (parsed, usage)

def get_brief_prompt(stories: List[Dict], outline: str) -> str:
    """Generate the prompt for brief generation"""
    return f"""
You are tasked with generating a personalized daily intelligence brief based on a curated set of news analyses and a provided structural outline. Aim for something comprehensive yet engaging, roughly a 20-30 minute read.

**User Interests:** Significant world news (geopolitics, politics, finance, economics), US news, China news (especially policy, economy, tech - seeking insights often missed in western media), crypto, and Technology/Science (AI/LLMs, biomed, space, real breakthroughs). Also include noteworthy items.

**Goal:** Leverage your analysis capabilities to create a focused brief that explains what's happening, why it matters, who's saying what, who's reporting what and identifies connections others might miss. The user values **informed, analytical takes**, grounded in the provided facts, but appreciates directness and avoids generic hedging or forced political correctness.

**Your Task:**

1.  **Adhere Strictly to the Provided Outline:** The structure (sections and order of topics) of your brief *must* follow the outline exactly.
2.  **Process Curated Data:** Use the full story details found within the stories data as your source material.
3.  **Connect Outline to Data:** For each story in the outline, locate the corresponding full story information.
4.  **Synthesize and Analyze:** Write the brief content for that story, following the style and content guidelines for each section.

**Stories Data:**
{json.dumps(stories, indent=2)}

**Outline:**
{outline}
"""

def get_title_prompt(brief: str) -> str:
    """Generate the prompt for title generation"""
    return f"""
Create a title for the brief. Construct it using the main topics. It should be short/punchy/not clickbaity etc. Make sure to not use "short text: longer text here for some reason" i HATE it, under no circumstance should there be colons in the title. Make sure it's not too vague/generic either bc there might be many stories. Maybe don't focus on like restituting what happened in the title, just do like the major entities/actors/things that happened. like "[person A], [thing 1], [org B] & [person O]" etc. try not to use verbs. state topics instead of stating topics + adding "shakes world order".

Return exclusively a JSON object with the following format:
```json
{{
    "title": "string"
}}
```

Brief content:
{brief}
"""

def get_tldr_prompt(brief: str) -> str:
    """Generate the prompt for TL;DR generation"""
    return f"""
You are an information processing agent tasked with creating a **substantive context brief** from a detailed intelligence briefing. Your output will be used by another AI model tomorrow to quickly understand the essential information and developments covered for each major topic today, ensuring continuity without requiring it to re-read the full brief. This requires more detail than just keywords.

**Your Task:**

Read the full intelligence brief provided below. Identify each distinct major story or narrative thread discussed. For **each** identified story, generate a concise summary capturing its essence *as presented in the brief*.

**Input:**

The input is the full text of the daily intelligence brief generated previously.

{brief}

**Required Output Format:**

Your entire output must consist **only** of a list of summaries, one for each identified major story. Each summary should follow this structure:

1.  **Story Identifier:** Start with a concise, descriptive label for the story thread (max 5-6 words, enclosed in square brackets `[]`). Examples: `[US-Venezuela Deportations]`, `[Gaza Ceasefire Talks]`, `[UK Economic Outlook]`, `[AI Energy Consumption Report]`.
2.  **Summary Paragraph:** Immediately following the identifier, provide a **dense summary paragraph (approx. 2-4 sentences, 30-60 words)** covering:
    *   The core issue or topic discussed for this story *in the brief*.
    *   The main developments, updates, or key pieces of information presented *in the brief*.
    *   Mention the most central entities (people, organizations, countries) involved *as discussed in the brief's coverage of this story*.
    *   The goal is to capture the *substance* of what was reported today, providing enough context for the next AI to understand the state of play.

**Instructions & Constraints:**

*   **Process Entire Brief:** Analyze the *whole* brief to identify all distinct major stories.
*   **Focus on Substance:** Prioritize conveying the *essential information and developments* reported in the brief for each story, not just keywords.
*   **Concise but Informative:** Summaries should be dense and capture key details within the approximate length guidelines (30-60 words).
*   **Coverage, Not Full Analysis:** Reflect *what the brief covered*, not external knowledge or deep analysis beyond what was presented.
*   **No Extra Text:** Do **NOT** include any headers (like "Output:"), introductions, explanations, or conclusions in your output. Output *only* the list of formatted story summaries.
""" 