# Installs

```python
%pip install -U openai json-repair google-genai gliclass rapidfuzz "transformers>=4.48.0" retry ipywidgets widgetsnbextension pandas-profiling readtime optuna bertopic supabase
```

# Get events

```python
import pandas as pd
from src.events import get_events

sources, events = get_events()
print(f"Number of events: {len(events)}")
print(f"Number of sources: {len(sources)}")

articles_df = pd.DataFrame(events)
# clean up those tuples
for col in articles_df.columns:
    articles_df[col] = articles_df[col].apply(
        lambda x: x[1] if isinstance(x, tuple) else x
    )
articles_df.columns = [
    "id",
    "sourceId",
    "url",
    "title",
    "publishDate",
    "content",
    "location",
    "relevance",
    "completeness",
    "summary",
]
articles_df["summary"] = (
    articles_df["summary"]
    .str.split("EVENT:")
    .str[1]
    .str.split("CONTEXT:")
    .str[0]
    .str.strip()
)
articles_df["text_to_embed"] = "query: " + articles_df["summary"]
articles_df.head(2)
```

# Clustering

## Prep: embeddings

```python
import torch
import torch.nn.functional as F
import numpy as np
from transformers import AutoTokenizer, AutoModel
from tqdm import tqdm

# helper function for pooling (straight from the docs)
def average_pool(last_hidden_states, attention_mask):
    last_hidden = last_hidden_states.masked_fill(~attention_mask[..., None].bool(), 0.0)
    return last_hidden.sum(dim=1) / attention_mask.sum(dim=1)[..., None]

# load the multilingual model
tokenizer = AutoTokenizer.from_pretrained('intfloat/multilingual-e5-small')
model = AutoModel.from_pretrained('intfloat/multilingual-e5-small')


# batch processing to avoid memory issues
batch_size = 64
all_embeddings = []

# process in batches with progress bar
for i in tqdm(range(0, len(articles_df), batch_size)):
    batch_texts = articles_df['text_to_embed'].iloc[i:i+batch_size].tolist()

    # tokenize
    batch_dict = tokenizer(batch_texts, max_length=512, padding=True, truncation=True, return_tensors='pt')

    # generate embeddings
    with torch.no_grad():
        outputs = model(**batch_dict)

    # pool and normalize
    embeddings = average_pool(outputs.last_hidden_state, batch_dict['attention_mask'])
    embeddings = F.normalize(embeddings, p=2, dim=1)

    # convert to numpy and add to list
    all_embeddings.extend(embeddings.numpy())

# store in dataframe
articles_df['embedding'] = all_embeddings
```

## Grid search umap & hdbscan params

```python
import numpy as np
import hdbscan
import umap
from hdbscan.validity import validity_index


def optimize_clusters(embeddings, umap_params, hdbscan_params):
    best_score = -1
    best_params = None

    # grid search both umap and hdbscan params
    for n_neighbors in umap_params["n_neighbors"]:
        # fit umap once per n_neighbors config
        reducer = umap.UMAP(
            n_neighbors=n_neighbors,
            n_components=10,
            min_dist=0.0,
            metric="cosine",
            random_state=42,
        )
        reduced_data = reducer.fit_transform(embeddings)

        for min_cluster_size in hdbscan_params["min_cluster_size"]:
            for min_samples in hdbscan_params["min_samples"]:
                for epsilon in hdbscan_params["epsilon"]:
                    # cluster with hdbscan
                    clusterer = hdbscan.HDBSCAN(
                        min_cluster_size=min_cluster_size,
                        min_samples=min_samples,
                        cluster_selection_epsilon=epsilon,
                        metric="euclidean",
                        prediction_data=True,
                    )

                    cluster_labels = clusterer.fit_predict(reduced_data)

                    # skip if all noise
                    if np.all(cluster_labels == -1):
                        continue

                    # evaluate with dbcv (better for density clusters)
                    valid_points = cluster_labels != -1
                    if (
                        valid_points.sum() > 1
                        and len(set(cluster_labels[valid_points])) > 1
                    ):
                        try:
                            reduced_data_64 = reduced_data[valid_points].astype(
                                np.float64
                            )
                            score = validity_index(
                                reduced_data_64, cluster_labels[valid_points]
                            )

                            if score > best_score:
                                best_score = score
                                best_params = {
                                    "umap": {"n_neighbors": n_neighbors},
                                    "hdbscan": {
                                        "min_cluster_size": min_cluster_size,
                                        "min_samples": min_samples,
                                        "epsilon": epsilon,
                                    },
                                }
                                print(f"new best: {best_score:.4f} with {best_params}")
                        except Exception as e:
                            # sometimes dbcv can fail on weird cluster shapes
                            print(f"failed with {e}")
                            continue

    return best_params, best_score


# param grids - adjust ranges based on your data
umap_params = {"n_neighbors": [10, 15, 20, 30]}

hdbscan_params = {
    "min_cluster_size": [5, 8, 10, 15],
    "min_samples": [2, 3, 5],
    "epsilon": [0.1, 0.2, 0.3],
}

# assuming embeddings is your data
best_params, best_score = optimize_clusters(all_embeddings, umap_params, hdbscan_params)
print(f"best overall: {best_score:.4f} with {best_params}")
```

## Run hdbscan

```python
import matplotlib.pyplot as plt
import seaborn as sns

# use the optimized params
umap_embeddings = umap.UMAP(
    n_neighbors=best_params["umap"]["n_neighbors"],
    n_components=10,  # bumped up from 5
    min_dist=0.0,
    metric="cosine",
).fit_transform(all_embeddings)

# cluster with optimal params
clusterer = hdbscan.HDBSCAN(
    min_cluster_size=best_params["hdbscan"]["min_cluster_size"],
    min_samples=best_params["hdbscan"]["min_samples"],
    cluster_selection_epsilon=best_params["hdbscan"]["epsilon"],
    metric="euclidean",
    prediction_data=True,
)
cluster_labels = clusterer.fit_predict(umap_embeddings)

# add to dataframe same as before
articles_df["cluster"] = cluster_labels

# quick stats
print(f"found {len(set(cluster_labels)) - (1 if -1 in cluster_labels else 0)} clusters")
print(f"noise points: {sum(cluster_labels == -1)}")

# 2d projection for visualization
umap_2d = umap.UMAP(n_components=2, metric="cosine").fit_transform(all_embeddings)

# plotting
plt.figure(figsize=(12, 10))
# plot noise points first (gray)
plt.scatter(
    umap_2d[cluster_labels == -1, 0],
    umap_2d[cluster_labels == -1, 1],
    c="lightgray",
    s=5,
    alpha=0.5,
    label="noise",
)

# plot actual clusters with random colors
unique_clusters = sorted(list(set(cluster_labels) - {-1}))
palette = sns.color_palette("husl", len(unique_clusters))

for i, cluster_id in enumerate(unique_clusters):
    plt.scatter(
        umap_2d[cluster_labels == cluster_id, 0],
        umap_2d[cluster_labels == cluster_id, 1],
        c=[palette[i]],
        s=25,
        label=f"cluster {cluster_id}",
    )

plt.title("article clusters")
plt.tight_layout()
plt.show()
```

# LLM Cluster review

```python
clusters_ids = list(set(cluster_labels) - {-1})
clusters_with_articles = []
for cluster_id in clusters_ids:
    cluster_df = articles_df[articles_df['cluster'] == cluster_id]
    articles_ids = cluster_df['id'].tolist()
    clusters_with_articles.append({
        "cluster_id": cluster_id,
        "articles_ids": articles_ids
    })
# sort clusters by most articles to least articles
clusters_with_articles = sorted(clusters_with_articles, key=lambda x: len(x['articles_ids']), reverse=True)
print(len(clusters_with_articles))
```

````python
import base64
import os
from google.genai import types
from retry import retry
import json
from json_repair import repair_json
from pydantic import BaseModel, Field, model_validator
from typing import List, Literal, Optional
from src.llm import call_llm


class Story(BaseModel):
    title: str = Field(description="title of the story")
    importance: int = Field(
        ge=1,
        le=10,
        description="global significance (1=minor local event, 10=major global impact)",
    )
    articles: List[int] = Field(description="list of article ids in the story")


class StoryValidation(BaseModel):
    answer: Literal["single_story", "collection_of_stories", "pure_noise", "no_stories"]

    # optional fields that depend on the answer type
    title: Optional[str] = None
    importance: Optional[int] = Field(None, ge=1, le=10)
    outliers: List[int] = Field(default_factory=list)
    stories: Optional[List[Story]] = None

    @model_validator(mode="after")
    def validate_structure(self):
        if self.answer == "single_story":
            if self.title is None or self.importance is None:
                raise ValueError(
                    "'title' and 'importance' are required for 'single_story'"
                )
            if self.stories is not None:
                raise ValueError("'stories' should not be present for 'single_story'")

        elif self.answer == "collection_of_stories":
            if not self.stories:
                raise ValueError("'stories' is required for 'collection_of_stories'")
            if self.title is not None or self.importance is not None or self.outliers:
                raise ValueError(
                    "'title', 'importance', and 'outliers' should not be present for 'collection_of_stories'"
                )

        elif self.answer == "pure_noise" or self.answer == "no_stories":
            if (
                self.title is not None
                or self.importance is not None
                or self.outliers
                or self.stories is not None
            ):
                raise ValueError(
                    "no additional fields should be present for 'pure_noise'"
                )

        return self


@retry(tries=3, delay=2, backoff=2, jitter=2, max_delay=20)
def process_story(cluster):

    story_articles_ids = cluster["articles_ids"]

    story_article_md = ""
    for article_id in story_articles_ids:
        article = next((e for e in events if e.id == article_id), None)
        if article is None:
            continue
        story_article_md += f"- (#{article.id}) [{article.title}]({article.url})\n"
        # story_article_md += f"> {article.publishDate}\n\n"
        # story_article_md += f"```\n{article.content}\n```\n\n"
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
Start by reasoning step by step. Consider:
- Central themes and events
- Temporal relationships (are events happening in the same timeframe?)
- Causal relationships (do events influence each other?)
- Whether splitting the narrative would lose important context

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
            "title": "title of the story",
            "importance": 1-10, // global significance scale
            "articles": [] // list of article ids in the story (**only** include substantial stories with **3+ articles**)
        }},
        ...
    ]
    // collection_of_stories_end
}}
````

Example for a single story:

```json
{{
    "answer": "single_story",
    "title": "The Great Fire of London",
    "importance": 8,
    "outliers": [123, 456] // article ids to exclude as unrelated
}}
```

Example for a collection of stories:

```json
{{
    "answer": "collection_of_stories",
    "stories": [
        {{
            "title": "The Great Fire of London",
            "importance": 8,
            "articles": [123, 456] // article ids in the story
        }},
        ...
    ]
}}
```

Example for pure noise:

```json
{{
    "answer": "pure_noise"
}}
```

Example for a distinct narratives with no stories that contain more than 3+ articles:

```json
{{
    "answer": "no_stories",
}}
```

Note:

- Always include articles IDs (outliers, articles, etc...) as integers, not strings and never include the # symbol.
  """.strip()

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

````


```python
from concurrent.futures import ThreadPoolExecutor
from tqdm import tqdm

# Submit all tasks and process in parallel
with ThreadPoolExecutor() as executor:
    # Submit all tasks and get future objects
    futures = [
        executor.submit(process_story, story) for story in clusters_with_articles
    ]

    # Use tqdm to show progress while getting results
    cleaned_clusters_raw = list(
        tqdm(
            (future.result() for future in futures),
            total=len(futures),
            desc="Processing stories",
        )
    )
````

```python
cleaned_clusters = []
for i in range(len(clusters_with_articles)):
    base = clusters_with_articles[i]
    res = cleaned_clusters_raw[i][0]

    if res.answer == "single_story":

        article_ids = base["articles_ids"]
        # filter out outliers
        article_ids = [x for x in article_ids if x not in res.outliers]

        cleaned_clusters.append(
            Story(
                title=res.title,
                importance=res.importance,
                articles=article_ids,
            )
        )
    elif res.answer == "collection_of_stories":
        for story in res.stories:
            cleaned_clusters.append(story)

# sort by importance
cleaned_clusters = sorted(cleaned_clusters, key=lambda x: x.importance, reverse=True)

lowest_importance = cleaned_clusters[0].importance
highest_importance = cleaned_clusters[-1].importance

print(f"lowest importance: {lowest_importance}")
print(f"highest importance: {highest_importance}")

print(len(cleaned_clusters))
```

```python
# plot distribution of importance
importance_values = [cluster.importance for cluster in cleaned_clusters]
plt.hist(importance_values, bins=20, edgecolor='black')
plt.title('Distribution of Importance Scores')
plt.xlabel('Importance Score')
plt.ylabel('Frequency')
plt.show()

# show clusters with importance < 5
low_importance_clusters = [cluster for cluster in cleaned_clusters if cluster.importance < 5]
high_importance_clusters = [cluster for cluster in cleaned_clusters if cluster.importance >= 5]
print(len(low_importance_clusters))
print(len(high_importance_clusters))
```

```python
for x in cleaned_clusters:
    print(f"# {x.title}")
    for article_id in x.articles:
        article = article = next((e for e in events if e.id == article_id), None)
        if article is not None:
            print(f"  - {article.title}")
        else:
            print(f" MISSED article_id: {article_id}")
            # print(f"- {article.title}")
    print("\n")

```

## LLM Analyze & enrich cluster

````python
import base64
import os
import tiktoken

enc = tiktoken.get_encoding("o200k_base")


@retry(
    tries=4, delay=2, backoff=2, jitter=1, max_delay=20
)  # max_delay=180 means never wait more than 3 mins
def final_process_story(title: str, articles_ids: list[int]):

    story_article_md = ""
    full_articles = []
    for article_id in articles_ids:
        article = next((e for e in events if e.id == article_id), None)
        if article is None:
            print(f"Article {article_id} not found")
            continue
        else:
            full_articles.append(article)

    # sort by publish date (from latest to oldest)
    # full_articles = sorted(full_articles, key=lambda x: x["publishDate"], reverse=True)
    for article in full_articles:
        story_article_md += f"## [{article.title}]({article.url}) (#{article.id})\n\n"
        story_article_md += f"> {article.publishDate}\n\n"
        story_article_md += f"```\n{article.content}\n```\n\n"

    story_article_md = story_article_md.strip()

    pre_prompt = """
You are a highly skilled intelligence analyst working for a prestigious agency. Your task is to analyze a cluster of related news articles and extract structured information for an executive intelligence report. The quality, accuracy, precision, and **consistency** of your analysis are crucial, as this report will directly inform a high-level daily brief and potentially decision-making.

First, assess if the articles provided contain sufficient content for analysis:

Here is the cluster of related news articles you need to analyze:

<articles>
""".strip()

    post_prompt = """
</articles>

BEGIN ARTICLE QUALITY CHECK:
Before proceeding with analysis, verify if the articles contain sufficient information:
1. Check if articles appear empty or contain minimal text (fewer than ~50 words each)
2. Check for paywall indicators ("subscribe to continue", "premium content", etc.)
3. Check if articles only contain headlines/URLs but no actual content
4. Check if articles appear truncated or cut off mid-sentence

If ANY of these conditions are true, return ONLY this JSON structure inside <final_json> tags:
<final_json>
{
    "status": "incomplete",
    "reason": "Brief explanation of why analysis couldn't be completed (empty articles, paywalled content, etc.)",
    "availableInfo": "Brief summary of any information that was available"
}
</final_json>

ONLY IF the articles contain sufficient information for analysis, proceed with the full analysis below:

Your goal is to extract and synthesize information from these articles into a structured format suitable for generating a daily intelligence brief.

Before addressing the main categories, conduct a preliminary analysis:
a) List key themes across all articles
b) Note any recurring names, places, or events
c) Identify potential biases or conflicting information
It's okay for this section to be quite long as it helps structure your thinking.

Then, after your preliminary analysis, present your final analysis in a structured JSON format inside <final_json> tags. This must be valid, parseable JSON that follows this **exact refined structure**:

**Detailed Instructions for JSON Fields:**

*   **`executiveSummary`**: Provide a 2-4 sentence concise summary highlighting the most critical developments, key conflicts, and overall assessment from the articles. This should be suitable for a quick read in a daily brief.
*   **`storyStatus`**: Assess the current state of the story's development based *only* on the information in the articles. Use one of: 'Developing', 'Escalating', 'De-escalating', 'Concluding', 'Static'.
*   **`timeline`**: List key events in chronological order.
    *   `description`: Keep descriptions brief and factual.
    *   `importance`: Assess the event's importance to understanding the overall narrative (High/Medium/Low). High importance implies the event is central to the story's development or outcome.
*   **`signalStrength`**: Assess the overall reliability of the reporting *in this cluster*.
    *   `assessment`: Use a qualitative term: 'Very High', 'High', 'Moderate', 'Low', 'Very Low'.
    *   `reasoning`: Justify the assessment based on source corroboration (how many sources report the same core facts?), source quality/reliability (mix of reputable vs. biased sources?), presence of official statements, and degree of conflicting information on core facts.
*   **`undisputedKeyFacts`**: List core factual points that are corroborated across multiple, generally reliable sources within the cluster. Avoid claims made only by highly biased sources unless corroborated.
*   **`keyEntities`**: Identify the main actors.
    *   `list`: Provide basic identification and their role/involvement.
    *   `perspectives.statedPositions`: Focus *only* on the goals, viewpoints, or justifications explicitly stated or clearly implied by the entity *as reported in the articles*. Avoid listing conflicting claims here (that goes in `contradictions`).
*   **`keySources`**: Analyze the provided news sources.
    *   `provided_articles_sources.reliabilityAssessment`: Assess the source's general reliability based on reputation, known biases (political, state affiliation, ideological), and fact-checking standards. Use terms like 'High Reliability', 'Moderate Reliability', 'Low Reliability', 'State-Affiliated/Propaganda Outlet'. Be specific about the *type* of bias.
    *   `provided_articles_sources.framing`: Describe the narrative angle or style used by the source (e.g., 'Emphasizes security threat', 'Focuses on human rights angle', 'Uses neutral language', 'Uses loaded/emotional language', 'Presents government narrative uncritically').
    *   `contradictions`: Detail specific points of disagreement *between sources* or *between entities as reported by sources*.
        *   `issue`: Clearly state what is being contested.
        *   `conflictingClaims`: List the different versions, specifying the `source` reporting it, the `claim` itself, and optionally the `entityClaimed` if the source attributes the claim to a specific entity. Critically evaluate claims originating solely from low-reliability/propaganda sources.
*   **`context`**: List essential background information *mentioned or clearly implied in the articles* needed to understand the story.
*   **`informationGaps`**: Identify crucial pieces of information *missing* from the articles that would be needed for a complete understanding.
*   **`significance`**: Assess the overall importance of the reported events.
    *   `assessment`: Use a qualitative term: 'Critical', 'High', 'Moderate', 'Low'.
    *   `reasoning`: Explain *why* this story matters. Consider immediate impact, potential future developments, strategic implications, precedent setting, regional/global relevance.

**Refined JSON Structure to Follow:**

```json
{
    "status": "complete",
    "executiveSummary": "string",
    "storyStatus": "string",
    "timeline": [
        {
            "date": "YYYY-MM-DD or approximate",
            "description": "brief event description",
            "importance": "string: High/Medium/Low"
        }
    ],
    "signalStrength": {
        "assessment": "string: Very High/High/Moderate/Low/Very Low",
        "reasoning": "string"
    },
    "undisputedKeyFacts": [
        "string"
    ],
    "keyEntities": {
        "list": [
            {
                "name": "entity name",
                "type": "type of entity",
                "description": "brief description",
                "involvement": "why/how involved?"
            }
        ],
        "perspectives": [
            {
                "entity": "entity name",
                "statedPositions": [
                    "string"
                ]
            }
        ]
    },
    "keySources": {
        "provided_articles_sources": [
            {
                "name": "source entity name",
                "articles": [], // int array of IDs
                "reliabilityAssessment": "string",
                "framing": [
                    "string"
                ]
            }
        ],
        "contradictions": [
            {
                "issue": "string",
                "conflictingClaims": [
                    {
                        "source": "media source name",
                        "entityClaimed": "entity name (optional)",
                        "claim": "string"
                    }
                ]
            }
        ]
    },
    "context": [
        "string"
    ],
    "informationGaps": [
        "string"
    ],
    "significance": {
        "assessment": "string: Critical/High/Moderate/Low",
        "reasoning": "string"
    }
}
````

**CRITICAL Quality & Consistency Requirements:**

- **Thoroughness:** Ensure all fields, especially descriptions, reasoning, context, and summaries, are detailed and specific. Avoid superficial or overly brief entries. Your analysis must reflect deep engagement with the provided texts.
- **Grounding:** Base your entire analysis **SOLELY** on the content within the provided `<articles>` tags. Do not introduce outside information, assumptions, or knowledge.
- **No Brevity Over Clarity:** Do **NOT** provide one-sentence descriptions or reasoning where detailed analysis is required by the field definition.
- **Scrutinize Sources:** Pay close attention to the reliability assessment of sources when evaluating claims, especially in the `contradictions` section. Note when a claim originates primarily or solely from a low-reliability source.
- **Validity:** Your JSON inside `<final_json></final_json>` tags MUST be 100% fully valid with no trailing commas, properly quoted strings and escaped characters where needed, and follow the exact refined structure provided. Ensure keys are in the specified order. Your entire JSON output should be directly extractable and parseable without human intervention.

Return your complete response, including your preliminary analysis/thinking in any format you prefer, followed by the **full** valid JSON inside `<final_json></final_json>` tags.
""".strip()

    # enc.decode(enc.encode("hello world"))
    tokens = enc.encode(story_article_md)

    # only keep the first million tokens
    tokens = tokens[:850_000]
    story_article_md = enc.decode(tokens)

    prompt = pre_prompt + "\n\n" + story_article_md + "\n\n" + post_prompt
    # print(prompt)

    answer, usage = call_llm(
        model="gemini-2.0-flash",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )

    text = answer

    if "```json" in text:
        text = text.split("```json")[1]
        text = text.strip()

    if "<final_json>" in text:
        text = text.split("<final_json>")[1]
        text = text.strip()

    if "</final_json>" in text:
        text = text.split("</final_json>")[0]
        text = text.strip()

    if text.endswith("```"):
        text = text.replace("```", "")
        text = text.strip()

    # text = repair_json(text)

    # assert "significance" in text

    return answer, usage

````


```python
from concurrent.futures import ThreadPoolExecutor, as_completed

cluster_analysis = []

# helper function to process a single cluster
def process_cluster(cluster):
    title = cluster.title
    articles_ids = cluster.articles
    return final_process_story(title=title, articles_ids=articles_ids)

# process clusters in parallel using a thread pool
with ThreadPoolExecutor() as executor:
    # submit all tasks and store futures
    futures = [executor.submit(process_cluster, cluster)
              for cluster in cleaned_clusters]

    # collect results as they complete using tqdm for progress
    for future in tqdm(as_completed(futures), total=len(futures)):
        cluster_analysis.append(future.result())
````

````python
from json_repair import repair_json

final_json_to_process = []

for i in range(len(cluster_analysis)):
    cluster = cluster_analysis[i]
    text = cluster[0]

    if "```json" in text:
        text = text.split("```json")[1]
        text = text.strip()

    if "<final_json>" in text:
        text = text.split("<final_json>")[1]
        text = text.strip()

    if "</final_json>" in text:
        text = text.split("</final_json>")[0]
        text = text.strip()

    if text.endswith("```"):
        text = text.replace("```", "")
        text = text.strip()

    text = repair_json(text)

    try:
        text_parsed = json.loads(text)

        if text_parsed["status"] == "incomplete":
            continue
        else:
            final_json_to_process.append(text_parsed)
    except:
        print(text)
        raise Exception("no final json")

# "assessment": "string: Critical/High/Moderate/Low",
# sort assessment by "Critical" first, then "High", then "Moderate", then "Low"

final_json_to_process = sorted(
    final_json_to_process, key=lambda x: x["significance"]["assessment"], reverse=True
)

# final_json_to_process = sorted(
#     final_json_to_process, key=lambda x: x["significance"]["score"], reverse=True
# )

print(len(cluster_analysis))
print(len(final_json_to_process))
````

```python
article_ids_used = []

for el in final_json_to_process:
    if "keySources" not in el:
        print("No keySources")
        continue

    for source in el['keySources']['provided_articles_sources']:
        for article_id in source['articles']:
            article_ids_used.append(article_id)

article_ids_used = list(set(article_ids_used))
used_events = []
used_sources = []
for article_id in article_ids_used:
    found_event = next((event for event in events if event.id == article_id), None)
    if found_event:
        link = found_event.url
        # print(link)

        # get just domain name
        domain = link.split("//")[1].split("/")[0]
        if domain not in used_sources:
            used_sources.append(domain)

        used_events.append(found_event)
```

```python
import json # Assuming json is needed if loading from file elsewhere

def json_to_markdown_refined(data):
    """
    Converts refined JSON analysis data into structured markdown suitable
    as input for a final briefing generation model.

    Args:
        data (dict): The JSON analysis data following the refined schema.

    Returns:
        str: Formatted markdown string.
    """
    if not data or data.get("status") != "complete":
        return "# Analysis Incomplete\n\nReason: " + data.get("reason", "Unknown") + "\n"

    # --- Header ---
    # Use Executive Summary as the core headline content
    summary = data.get("executiveSummary", "No summary available.")
    status = data.get("storyStatus", "Status Unknown")
    markdown = f"# Key Development Summary: {summary}\n"
    markdown += f"**(Story Status: {status})**\n\n"

    # --- Key Timeline Events (Prioritized) ---
    if data.get("timeline"):
        markdown += "## Key Timeline Events (High Importance)\n"
        # Filter for 'High' importance events, limit to ~5 for brevity
        high_importance_events = [
            event for event in data["timeline"] if event.get("importance") == "High"
        ]
        # If few high importance, maybe include Medium? For now, just High.
        limit = 5
        for event in high_importance_events[:limit]:
            markdown += f"*   **{event.get('date', 'N/A')}:** {event.get('description', 'N/A')}\n"
        if not high_importance_events:
            markdown += "*   *No high-importance events identified in timeline.*\n"
        markdown += "\n"

    # --- Overall Significance ---
    if data.get("significance"):
        markdown += "## Overall Significance\n"
        assessment = data["significance"].get('assessment', 'N/A')
        reasoning = data["significance"].get('reasoning', 'No reasoning provided.')
        markdown += f"*   **Assessment:** {assessment}\n"
        markdown += f"*   **Reasoning:** {reasoning}\n\n"

    # --- Core Factual Basis ---
    if data.get("undisputedKeyFacts"):
        markdown += "## Core Factual Basis (Corroborated)\n"
        limit = 5
        for fact in data["undisputedKeyFacts"][:limit]:
            markdown += f"*   {fact}\n"
        if len(data["undisputedKeyFacts"]) > limit:
            markdown += f"*   *(Additional facts available)*\n"
        markdown += "\n"

    # --- Key Contradictions / Contested Issues ---
    if data.get("keySources", {}).get("contradictions"):
        markdown += "## Key Contradictions / Contested Issues\n"
        limit = 3
        contradictions = data["keySources"]["contradictions"]
        for contradiction in contradictions[:limit]:
            issue = contradiction.get('issue', 'Unspecified Issue')
            markdown += f"*   **Issue:** {issue}\n"
            # Optionally list the sources/claims briefly if needed, but issue might suffice
            # for claim in contradiction.get('conflictingClaims', [])[:2]: # Show first 2 claims?
            #    source = claim.get('source', 'Unknown Source')
            #    claim_text = claim.get('claim', 'N/A')
            #    markdown += f"    *   {source}: Claims '{claim_text[:50]}...' \n"
        if not contradictions:
             markdown += "*   *No major contradictions identified.*\n"
        if len(contradictions) > limit:
            markdown += f"*   *(Additional contested issues identified)*\n"
        markdown += "\n"

    # --- Key Entities Involved ---
    if data.get("keyEntities", {}).get("list"):
        markdown += "## Key Entities Involved\n"
        limit = 4
        for entity in data["keyEntities"]["list"][:limit]:
            markdown += f"*   **{entity.get('name', 'N/A')} ({entity.get('type', 'N/A')}):** {entity.get('involvement', 'N/A')}\n"
        if len(data["keyEntities"]["list"]) > limit:
            markdown += f"*   *(Additional entities involved)*\n"
        markdown += "\n"

    # --- Critical Information Gaps ---
    if data.get("informationGaps"):
        markdown += "## Critical Information Gaps\n"
        limit = 4
        for gap in data["informationGaps"][:limit]:
            markdown += f"*   {gap}\n"
        if len(data["informationGaps"]) > limit:
            markdown += f"*   *(Additional gaps identified)*\n"
        markdown += "\n"

    # --- Assessment Summary (Signal & Reliability) ---
    markdown += "## Assessment Summary\n"
    if data.get("signalStrength"):
        assessment = data["signalStrength"].get('assessment', 'N/A')
        reasoning = data["signalStrength"].get('reasoning', 'No reasoning provided.')
        markdown += f"*   **Signal Strength:** {assessment}\n"
        # Summarize reasoning briefly if desired, or rely on the assessment
        # markdown += f"*   **Basis:** {reasoning[:150]}...\n"
    else:
        markdown += "*   Signal Strength: Not Assessed\n"

    # Add a note about source reliability variance
    markdown += "*   **Note:** Analysis based on sources of varying reliability (see full JSON for details). Claims from low-reliability sources require caution.\n"

    return markdown

# Example Usage (assuming 'refined_output_d' holds Model D's refined JSON output)
# markdown_output = json_to_markdown_refined(refined_output_d)
# print(markdown_output)

stories_markdown = ""
for i in range(len(final_json_to_process)):
    cluster = final_json_to_process[i]
    stories_markdown += "\n---\n\n"+ json_to_markdown_refined(cluster)
stories_markdown = stories_markdown[4:].strip()
print(stories_markdown)
```

# Final brief prompts

```python
import os
import requests

# with headers
latest_report = requests.get(
        "https://meridian-production.alceos.workers.dev/last-report",
        headers={
            "Authorization": f"Bearer {os.environ.get('MERIDIAN_SECRET_KEY')}"
        }
    )
latest_report = latest_report.json()
latest_report = f"""
## Previous Day's Coverage Context ({latest_report['createdAt'].split('T')[0]})

### {latest_report['title']}

{latest_report['tldr']}
"""
print(latest_report)
```

```python

def get_brief_prompt(curated_news: str):
    prompt = f"""
hey, i have a bunch of news reports (in random order) derived from detailed analyses of news clusters from the last 30h. could you give me my personalized daily intelligence brief? aim for something comprehensive yet engaging, roughly a 20-30 minute read.

my interests are: significant world news (geopolitics, politics, finance, economics), us news, france news (i'm french/live in france), china news (especially policy, economy, tech - seeking insights often missed in western media), and technology/science (ai/llms, biomed, space, real breakthroughs). also include a section for noteworthy items that don't fit neatly elsewhere.

some context: i built a system that collects/analyzes/compiles news because i was tired of mainstream news that either overwhelms with useless info or misses what actually matters. you're really good at information analysis/writing/etc so i figure by just asking you this i'd get something even better than what presidents get - a focused brief that tells me what's happening, why it matters, and what connections exist that others miss. i value **informed, analytical takes** – even if i don't agree with them, they're intellectually stimulating. i want analysis grounded in the facts provided, free from generic hedging or forced political correctness.

your job: go through all the curated news data i've gathered below. analyze **everything** first to identify what *actually* matters before writing. look for:
- actual significance (not just noise/volume)
- hidden patterns and connections between stories
- important developments flying under the radar
- how separate events might be related
- genuinely interesting or impactful stories

**--- CONTEXT FROM PREVIOUS DAY (IF AVAILABLE) ---**
*   You *may* receive a section at the beginning of the curated data titled `## Previous Day's Coverage Context (YYYY-MM-DD)`.
*   This section provides a highly condensed list of major stories covered yesterday, using the format: `[Story Identifier] | [Last Status] | [Key Entities] | [Core Issue Snippet]`.
*   **How to Use This Context:** Use this list **only** to understand which topics are ongoing and their last known status/theme. This helps ensure continuity and avoid repeating information already covered.
*   **Focus on Today:** Your primary task is to synthesize and analyze **today's developments** based on the main `<curated_news_data>`. When discussing a story listed in the previous context, focus on **what is new or has changed today**. Briefly reference the past context *only if essential* for understanding the update (e.g., "Following yesterday's agreement...", "The situation escalated further today when...").
*   **Do NOT simply rewrite or extensively quote the Previous Day's Coverage Context.** Treat it as background memory.
**--- END CONTEXT INSTRUCTIONS ---**

here's the curated data (each section represents an analyzed news cluster; you might need to synthesize across sections):

{latest_report}

<curated_news_data>

{curated_news}

</curated_news_data>

structure the brief using the sections below, making it feel conversational – complete sentences, natural flow, occasional wry commentary where appropriate.
<final_brief>
## what matters now
cover the *up to* 7-8 most significant stories with real insight. for each:
<u>**title that captures the essence**</u>
weave together what happened, why it matters (significance, implications), key context, and your analytical take in natural, flowing paragraphs.
separate paragraphs with linebreaks for readability, but ensure smooth transitions.
blend facts and analysis naturally. **if there isn't much significant development or analysis for a story, keep it brief – don't force length.** prioritize depth and insight where warranted.
use **bold** for key specifics (names, places, numbers, orgs), *italics* for important context or secondary details.
offer your **analytical take**: based on the provided facts and context, what are the likely motivations, potential second-order effects, overlooked angles, or inconsistencies? ground this analysis in the data.

## france focus
(i'm french/live in france)
significant french developments: policy details, key players, economic data, political shifts.

## global landscape
### power & politics
key geopolitical moves, focusing on outcomes and strategic implications, including subtle shifts.

### china monitor
(seeking insights often missed in western media - skip if nothing significant)
meaningful policy shifts, leadership dynamics, economic indicators (with numbers if available), tech developments, social trends.

### economic currents
market movements signaling underlying trends, impactful policy decisions, trade/resource developments (with data), potential economic risks or opportunities.

## tech & science developments
(focus on ai/llms, space, biomed, real breakthroughs - skip if only minor product news)
actual breakthroughs, notable ai/llm advancements, significant space news, key scientific progress. separate signal from noise.

## noteworthy & under-reported
(combine under-reported significance and carte blanche)
important stories flying under the radar, emerging patterns with specific indicators, slow-burning developments, or other interesting items you think i should see (up to 5 items max).

## positive developments
(skip if nothing genuinely positive/significant, don't force it)
actual progress with measurable outcomes, effective solutions, verifiable improvements.
</final_brief>

use the:
```

<u>**title that captures the essence**</u>
paragraph

paragraph

...

```
for all sections.

make sure everything inside the <final_brief></final_brief> tags is the actual brief content itself. any/all "hey, here is the brief" or "hope you enjoyed today's brief" should either not be included or be before/after the <final_brief></final_brief> tags.

**final instructions:**
*   always enclose the brief inside <final_brief></final_brief> tags.
*   use lowercase by default like i do. complete sentences please.
*   this is for my eyes only - be direct and analytical.
*   **source reliability:** the input data is derived from analyses that assessed source reliability. use this implicit understanding – give more weight to information from reliable sources and treat claims originating solely from known low-reliability/propaganda sources with appropriate caution in your analysis and 'take'. explicitly mentioning source reliability isn't necessary unless a major contradiction hinges on it.
*   **writing style:** aim for the tone of an extremely well-informed, analytical friend with a dry wit and access to incredible information processing. be insightful, engaging, and respect my time. make complex topics clear without oversimplifying. integrate facts, significance, and your take naturally.
*   **leverage your strengths:** process all the info, spot cross-domain patterns, draw on relevant background knowledge (history, economics, etc.), explain clearly, and provide that grounded-yet-insightful analytical layer.

give me the brief i couldn't get before ai - one that combines human-like insight with superhuman information processing.
""".strip()
    return prompt


# curated_news_data = ""
# for el in ok_now_were_good:
#     curated_news_data += el.text
#     curated_news_data += "\n\n---\n\n"
# curated_news_data = curated_news_data.strip()
# if curated_news_data.endswith("---"):
#     curated_news_data = curated_news_data[:-4]
# curated_news_data = curated_news_data.strip()

systemPrompt = """
Adopt the persona of an exceptionally well-informed, highly analytical, and slightly irreverent intelligence briefer. Imagine you have near-instant access to and processing power for vast amounts of global information, combined with a sharp, insightful perspective and a dry wit. You're communicating directly and informally with a smart, curious individual who values grounded analysis but dislikes corporate speak, hedging, and forced neutrality.

**Your core stylistic goals are:**

1.  **Tone:** Conversational, direct, and engaging. Use lowercase naturally, as if speaking or writing informally to a trusted peer. Avoid stiff formality, bureaucratic language, or excessive caution. Be chill, but maintain intellectual rigor.
2.  **Analytical Voice:** Prioritize insightful analysis over mere summarization. Go beyond stating facts to explain *why* they matter, connect disparate events, identify underlying patterns, assess motivations, and explore potential implications (second-order effects). Offer a clear, grounded "take" on developments. Don't be afraid to call out inconsistencies or highlight underappreciated angles, always backing it up with the logic derived from the provided information.
3.  **Wit & Personality:** Embrace a dry, clever wit. Humor, sarcasm, or irony should arise *naturally* from the situation or the absurdity of events. Pointing out the obvious when it's funny is fine. **Crucially: Do not force humor, be cringe, or undermine the gravity of serious topics like human suffering.** Wit should enhance insight, not detract from it.
4.  **Language:** Use clear, concise language. Vary sentence structure for natural flow. Occasional relevant slang or shorthand is acceptable if it fits the informal tone naturally, but prioritize clarity. Ensure analysis is sharp and commentary is insightful, not just filler.

**Think of yourself as:** The user's personal "Q" (from James Bond) combined with a sharp geopolitical analyst – someone with unparalleled information access who can cut through the noise, connect the dots, and deliver the essential insights with a bit of personality and zero tolerance for BS.

**Relationship to Main Prompt:** This system prompt defines *how* you should wrte and analyze. Follow the specific content structure, formatting, and topic instructions provided in the main user prompt separately. Your analysis and 'take' should always be grounded in the information provided in the main prompt's `<curated_news_data>` section.

Your ultimate goal is to deliver the kind of insightful, personalized, and engaging intelligence brief that wasn't possible before AI – combining superhuman data processing with a distinct, analytical, and trustworthy (even if slightly cynical) voice.
""".strip()

brief_prompt = get_brief_prompt(stories_markdown)
brief_model = "gemini-2.5-pro-exp-03-25"
# print(brief_prompt)
brief_response = call_llm(
    model=brief_model,
    messages=[
        {"role": "system", "content": systemPrompt},
        {"role": "user", "content": brief_prompt},
    ],
    temperature=0.7,
)
```

```python
from google.genai.types import FinishReason


final_brief_text = brief_response[0]
assert "<final_brief>" in final_brief_text
final_brief_text = final_brief_text.split("<final_brief>")[1]

assert "</final_brief>" in final_brief_text
final_brief_text = final_brief_text.split("</final_brief>")[0]

final_brief_text = final_brief_text.strip()
```

````python
import os
from openai import OpenAI
from dotenv import load_dotenv
import base64
import os
from google import genai
from google.genai import types


load_dotenv()
client = genai.Client(
    api_key=os.environ.get("GOOGLE_API_KEY"),
)


brief_title_prompt = f"""
<brief>
{final_brief_text}
</brief>

create a title for the brief. construct it using the main topics. it should be short/punchy/not clickbaity etc. make sure to not use "short text: longer text here for some reason" i HATE it, under no circumstance should there be colons in the title. make sure it's not too vague/generic either bc there might be many stories. maybe don't focus on like restituting what happened in the title, just do like the major entities/actors/things that happened. like "[person A], [thing 1], [org B] & [person O]" etc. try not to use verbs. state topics instead of stating topics + adding "shakes world order". always use lowercase.

return exclusively a JSON object with the following format:
```json
{{
    "title": "string"
}}
````

""".strip()

brief_title_response = call_llm(
model="gemini-2.0-flash",
messages=[
{"role": "user", "content": brief_title_prompt}
],
temperature=0.0,
)

````


```python
brief_title = brief_title_response[0]
if brief_title.startswith("```json"):
    brief_title = brief_title.split("```json")[1]
if brief_title.endswith("```"):
    brief_title = brief_title.split("```")[0]
brief_title = brief_title.strip()
brief_title = json.loads(brief_title)['title']
````

```python
tldr_prompt = f"""

You are an information processing agent tasked with creating a highly condensed 'memory state' or 'context brief' from a detailed intelligence briefing. Your output will be used by another AI model tomorrow to understand what topics were covered today, ensuring continuity without requiring it to re-read the full brief.

**Your Task:**

Read the full intelligence brief provided below within the `<final_brief>` tags. Identify each distinct major story or narrative thread discussed. For **each** identified story, extract the necessary information and format it precisely according to the specified structure.

**Input:**

The input is the full text of the daily intelligence brief generated previously.

<final_brief>
# {brief_title}

{final_brief_text}
</final_brief>

**Required Output Format:**

Your entire output must consist **only** of a list of strings, one string per identified story, following this exact format:

`[Story Identifier] | [Inferred Status] | [Key Entities] | [Core Issue Snippet]`

**Explanation of Output Components:**

1.  **`[Story Identifier]`:** Create a concise, descriptive label for the story thread (max 4-5 words). Examples: `US-Venezuela: Deportations`, `Gaza: Ceasefire Collapse`, `UK: Economy Update`, `AI: Energy Consumption`. Use keywords representing the main actors and topic.
2.  **`[Inferred Status]`:** Based *only* on the tone and content of the discussion *within the provided brief*, infer the story's current state. Use one of: `New`, `Developing`, `Escalating`, `De-escalating`, `Resolved`, `Ongoing`, `Static`.
3.  **`[Key Entities]`:** List the 3-5 most central entities (people, organizations, countries) mentioned *in the context of this specific story* within the brief. Use comma-separated names. Example: `Trump, Maduro, US, Venezuela, El Salvador`.
4.  **`[Core Issue Snippet]`:** Summarize the absolute essence of *this story's main point or development as covered in the brief* in **5-10 words maximum**. This requires extreme conciseness. Example: `Deportations resume via Honduras amid legal challenges`, `Ceasefire over, hospital strike, offensive planned`, `Talks falter, missile strike during meeting`.

**Instructions & Constraints:**

*   **Process Entire Brief:** Read and analyze the *whole* brief to identify all distinct major stories. Stories under `<u>**title**</u>` headings are primary candidates, but also consider distinct, significant themes from other sections (e.g., a recurring topic in 'Global Landscape').
*   **One Line Per Story:** Each identified story must correspond to exactly one line in the output, following the specified format.
*   **Strict Conciseness:** Adhere strictly to the format and the word limit for the `[Core Issue Snippet]`. This is critical.
*   **Focus on Coverage:** The goal is to capture *what was discussed*, not the full nuance or analysis.
*   **Inference for Status:** You must *infer* the status based on the brief's content, as it's not explicitly stated per story in the input brief text.
*   **No Extra Text:** Do **NOT** include any headers, explanations, introductions, or conclusions in your output. Output *only* the list of formatted strings.

Generate the condensed context brief based *only* on the provided `<final_brief>` text.
""".strip()

tldr_response = call_llm(
    model="gemini-2.0-flash",
    messages=[
        {"role": "user", "content": tldr_prompt}
    ],
    temperature=0.0,
)
```

````python
tldr = tldr_response[0]
if tldr.startswith("```"):
    tldr = tldr.split("```")[1]
if tldr.endswith("```"):
    tldr = tldr.split("```")[0]
tldr = tldr.strip()
print(tldr)
````

# Publish

```python
print("========== STATS ==========")
print(f"Total articles: {len(events)}")
print(f"Total sources: {len(sources)}")
print(f"Total used articles: {len(used_events)}")
print(f"Total used sources: {len(used_sources)}")
print(f"Model used: {brief_model}")
print("========== STATS ==========")
```

```python
print(f"# {brief_title}\n")
print(final_brief_text)
```

```python
from datetime import datetime
import requests

body = {
    "title": brief_title,
    "content": final_brief_text,
    "totalArticles": len(events),
    "totalSources": len(sources),
    "usedArticles": len(used_events),
    "usedSources": len(used_sources),
    "tldr": tldr,
    "model_author": brief_model,
    "createdAt": datetime.now().isoformat(),
    "clustering_params": best_params,
}

endpoint = "https://meridian-production.alceos.workers.dev/report"

response = requests.post(
    endpoint,
    json=body,
    headers={"Authorization": f"Bearer {os.environ.get('MERIDIAN_SECRET_KEY')}"},
)
print(response.json())
```
