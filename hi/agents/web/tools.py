"""Web lookup tools (Wikipedia text, a picture of something), shared by the web and term agents."""

import json
import re
import urllib.error
import urllib.parse
import urllib.request

from langchain_core.tools import tool

SEARCH_URL = "https://en.wikipedia.org/w/api.php"
SUMMARY_URL = "https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
TIMEOUT_SECONDS = 10


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


IMAGE_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
MAX_IMAGE_BYTES = 8_000_000


def _get(url: str) -> tuple[bytes, str]:
    request = urllib.request.Request(url, headers={"User-Agent": "hi-web-persona/1.0"})
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return response.read(MAX_IMAGE_BYTES), response.headers.get_content_type()


@tool
def find_image(query: str) -> str:
    """Find a picture of a person, place, animal or thing and show it in the UI.

    Args:
        query: What to show, by full name, e.g. "Shah Rukh Khan" (not an abbreviation).
    """
    from hi.vault import plots_dir

    try:
        title = json.loads(_get(f"{SEARCH_URL}?" + urllib.parse.urlencode(
            {"action": "query", "list": "search", "srsearch": query, "format": "json"}))[0])["query"]["search"][0]["title"]
        page = json.loads(_get(SUMMARY_URL.format(title=urllib.parse.quote(title)))[0])
        source = (page.get("thumbnail") or page.get("originalimage") or {}).get("source")
        if not source:
            return f"'{title}' on Wikipedia has no picture."
        data, kind = _get(re.sub(r"/\d+px-", "/500px-", source))
    except (IndexError, KeyError):
        return f"No Wikipedia article found for '{query}'."
    except (OSError, json.JSONDecodeError) as e:
        return f"Could not fetch a picture: {e}."
    if kind not in IMAGE_TYPES:
        return f"Found '{title}' but its picture is not an image file ({kind})."
    name = re.sub(r"[^\w-]+", "-", title.lower()).strip("-") + IMAGE_TYPES[kind]
    plots_dir().mkdir(parents=True, exist_ok=True)
    (plots_dir() / name).write_bytes(data)
    return f"Picture of {title} (from Wikipedia), shown in the UI: /plots/{name}"
