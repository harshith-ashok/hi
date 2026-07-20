"""Web: a search-and-summarize persona built with a LangGraph ReAct agent."""

import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from langchain.agents import create_agent
from langchain_core.tools import tool
from langchain_ollama import ChatOllama

SEARCH_URL = "https://en.wikipedia.org/w/api.php"
SUMMARY_URL = "https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
TIMEOUT_SECONDS = 10

model = ChatOllama(
    model="gpt-oss:120b-cloud",
    temperature=0,
)


@tool
def search_wikipedia(query: str) -> str:
    """Look up a query on Wikipedia and return a summary of the best-matching article.

    Args:
        query: The topic or question to search for, e.g. "virtual memory".
    """
    params = urllib.parse.urlencode(
        {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "format": "json",
        }
    )
    search_request = urllib.request.Request(
        f"{SEARCH_URL}?{params}",
        headers={"User-Agent": "hi-web-persona/1.0"},
    )
    try:
        with urllib.request.urlopen(search_request, timeout=TIMEOUT_SECONDS) as response:
            search_data = json.loads(response.read())
    except urllib.error.HTTPError as e:
        return f"Wikipedia search failed: HTTP {e.code} {e.reason}."
    except urllib.error.URLError as e:
        return f"Wikipedia search failed: {e.reason}."
    except TimeoutError:
        return "Wikipedia search timed out."
    except (json.JSONDecodeError, OSError) as e:
        return f"Wikipedia search failed: {e}."

    results = search_data.get("query", {}).get("search", [])
    if not results:
        return f"No Wikipedia article found for '{query}'."

    title = results[0]["title"]
    summary_request = urllib.request.Request(
        SUMMARY_URL.format(title=urllib.parse.quote(title)),
        headers={"User-Agent": "hi-web-persona/1.0"},
    )
    try:
        with urllib.request.urlopen(summary_request, timeout=TIMEOUT_SECONDS) as response:
            summary_data = json.loads(response.read())
    except urllib.error.HTTPError as e:
        return f"Found article '{title}' but failed to fetch its summary: HTTP {e.code} {e.reason}."
    except urllib.error.URLError as e:
        return f"Found article '{title}' but failed to fetch its summary: {e.reason}."
    except TimeoutError:
        return f"Found article '{title}' but fetching its summary timed out."
    except (json.JSONDecodeError, OSError) as e:
        return f"Found article '{title}' but failed to fetch its summary: {e}."

    extract = summary_data.get("extract")
    if not extract:
        return f"Found article '{title}' but it has no summary available."
    return f"{title}: {extract}"


PROMPT_PATH = Path(__file__).parent / "web_prompt.md"

agent = create_agent(
    model=model,
    tools=[search_wikipedia],
    system_prompt=PROMPT_PATH.read_text(),
)
