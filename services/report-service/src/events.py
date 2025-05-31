import requests
import os
from datetime import date
from pydantic import BaseModel, field_validator
from typing import Optional, List
import pandas as pd
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, field_validator
from dotenv import load_dotenv

load_dotenv()


class Source(BaseModel):
    id: int
    name: str


class Event(BaseModel):
    id: int
    sourceId: int
    url: str
    title: str
    publishDate: datetime
    contentFileKey: str
    primary_location: str
    completeness: str
    content_quality: str
    event_summary_points: Optional[List[str]] = None
    thematic_keywords: Optional[List[str]] = None
    topic_tags: Optional[List[str]] = None
    key_entities: Optional[List[str]] = None
    content_focus: Optional[List[str]] = None
    embedding: Optional[List[float]] = None
    createdAt: datetime

    @field_validator("publishDate", "createdAt", mode="before")
    @classmethod
    def parse_date(cls, value):
        if value is None:
            return None

        # Handle ISO format with timezone info
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            # For older Python versions or non-standard formats
            # you might need dateutil
            from dateutil import parser
            return parser.parse(value)


def get_events(date: str = None, start_date: str = None, end_date: str = None):
    url = f"https://meridian-backend-production.pmckelvy1.workers.dev/events"

    # Build query parameters
    params = {}
    if date:
        params['date'] = date
    elif start_date and end_date:
        params['startDate'] = start_date
        params['endDate'] = end_date

    print(f"Fetching events from {url} with params: {params}")
    response = requests.get(
        url,
        params=params,
        headers={"Authorization": f"Bearer {os.environ.get('API_TOKEN')}"},
    )
    data = response.json()
    sources = [Source(**source) for source in data["sources"]]
    events = [Event(**event) for event in data["events"]]

    return sources, events
