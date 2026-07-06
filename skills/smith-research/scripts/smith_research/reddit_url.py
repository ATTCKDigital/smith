# Adapted (copied, not imported) from armory services/trend-intelligence/trend_intelligence/validation/reddit_url.py.
# Vendored into smith-research per user instruction: no runtime coupling to armory.
"""Reddit URL canonicalization and classification for the subreddit sources feature.

Canonical form: https://www.reddit.com/r/<name>
  - Always https, always www., no trailing slash, no query string, no fragment.
  - Subreddit name casing is preserved as supplied by the user.
  - Subreddit name rules (Reddit's published spec): 3-21 chars, starts with a
    letter, remainder alphanumeric + underscore.

Only bare subreddit URLs are accepted by feature 091. Post URLs, user profiles,
search pages, sort variants, multireddits, and non-Reddit hosts are all rejected
with a descriptive reason string so the UI can display per-line error messages.
"""

import re
from urllib.parse import urlparse, urlunparse

# Accepted hosts (after normalization www. is always present)
_REDDIT_HOSTS = {"reddit.com", "www.reddit.com"}

# Subreddit name: starts with letter, then 2–20 more alphanumeric/underscore chars.
# Total length 3–21, matching Reddit's published rule.
_SUBREDDIT_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{2,20}$")

# Sort-variant suffixes that appear as the next path segment after the sub name.
_SORT_VARIANTS = {"new", "top", "hot", "rising", "controversial"}


class ClassifyError(ValueError):
    """Raised when a URL cannot be classified as a valid subreddit URL."""


def _normalize_url(raw: str) -> str | None:
    """Return a normalized URL string, or None if the input is unparseable.

    Normalization steps (applied in order):
      1. Strip leading/trailing whitespace.
      2. Upgrade http:// to https://.
      3. Parse with urlparse; bail if scheme or netloc is missing.
      4. Insert www. if the host is bare reddit.com.
      5. Lowercase the host (hosts are case-insensitive per RFC 3986).
      6. Strip query string and fragment.
      7. Strip trailing slash from the path.
    """
    raw = raw.strip()
    if not raw:
        return None

    # Upgrade insecure scheme before parsing so urlparse sees the right netloc.
    if raw.startswith("http://"):
        raw = "https://" + raw[len("http://") :]

    parsed = urlparse(raw)

    if parsed.scheme != "https" or not parsed.netloc:
        return None

    host = parsed.netloc.lower()

    # Insert www. for bare reddit.com so the canonical form is always www.
    if host == "reddit.com":
        host = "www.reddit.com"

    if host not in _REDDIT_HOSTS:
        return None

    # Strip trailing slash from path, query, and fragment.
    path = parsed.path.rstrip("/")

    return urlunparse(("https", host, path, "", "", ""))


def _classify_path(path: str) -> tuple[str, str]:
    """Return (kind, subreddit_name) or raise ClassifyError.

    kind is always 'subreddit' for a successful classification.
    The subreddit_name preserves the original casing from the URL.
    """
    # Split path into non-empty segments.
    segments = [s for s in path.split("/") if s]

    # Must start with 'r'
    if not segments or segments[0] != "r":
        if segments and segments[0] in ("user", "u"):
            raise ClassifyError("user profile URL — not a subreddit")
        if segments and segments[0] == "search":
            raise ClassifyError("search URL — not a subreddit")
        raise ClassifyError("unrecognized Reddit URL shape")

    if len(segments) < 2:
        raise ClassifyError("unrecognized Reddit URL shape")

    sub_name_raw = segments[1]

    # Multireddit check: /r/foo+bar
    if "+" in sub_name_raw:
        raise ClassifyError("multireddit URL — only single-subreddit URLs are accepted")

    # Validate subreddit name charset and length.
    if not _SUBREDDIT_NAME_RE.match(sub_name_raw):
        raise ClassifyError(
            f"invalid subreddit name '{sub_name_raw}' — "
            "must be 3–21 characters, start with a letter, and contain only "
            "letters, digits, and underscores"
        )

    if len(segments) == 2:
        # Bare subreddit URL: /r/<name>
        return "subreddit", sub_name_raw

    third = segments[2].lower()

    if third == "comments":
        if len(segments) >= 4:
            # /r/<name>/comments/<post_id>/...
            raise ClassifyError(
                "post URL — only subreddit URLs are accepted in this section"
            )
        raise ClassifyError("unrecognized Reddit URL shape")

    if third in _SORT_VARIANTS:
        raise ClassifyError(
            f"subreddit sort variant (/{third}) — only the bare subreddit URL is accepted; "
            "sort order is applied at fetch time, not stored"
        )

    raise ClassifyError("unrecognized Reddit URL shape")


def canonicalize_subreddit_url(raw: str) -> str:
    """Return the canonical subreddit URL for *raw*, or raise ClassifyError.

    The canonical form is https://www.reddit.com/r/<name> (no trailing slash,
    no query, no fragment, subreddit name casing preserved).

    Raises ClassifyError with a human-readable reason for any input that is not
    a valid subreddit URL, including post URLs, user profiles, sort variants,
    multireddits, and non-Reddit hosts.
    """
    normalized = _normalize_url(raw)
    if normalized is None:
        parsed = urlparse(raw.strip())
        host = parsed.netloc.lower() if parsed.netloc else ""
        if host and host not in _REDDIT_HOSTS and not host.endswith("reddit.com"):
            raise ClassifyError("not a Reddit URL")
        raise ClassifyError("malformed URL — could not parse as a valid https URL")

    parsed = urlparse(normalized)
    host = parsed.netloc

    # Reject subdomains like old.reddit.com, np.reddit.com — only www. accepted.
    if host != "www.reddit.com":
        raise ClassifyError(
            f"unsupported Reddit subdomain '{host}' — only www.reddit.com is accepted"
        )

    _classify_path(parsed.path)  # raises ClassifyError if not a valid subreddit path

    return normalized


def parse_reddit_url(raw: str) -> dict:
    """Parse a raw Reddit URL into a row-shaped dict, or raise ClassifyError.

    Returns:
        {
            "source_type": "subreddit",
            "subreddit_name": str,      # original casing preserved
            "post_id": None,
            "normalized_url": str,      # canonical https://www.reddit.com/r/<name>
        }

    Raises ClassifyError for any URL that is not a valid subreddit URL.
    """
    normalized = _normalize_url(raw)
    if normalized is None:
        parsed = urlparse(raw.strip())
        host = parsed.netloc.lower() if parsed.netloc else ""
        if host and host not in _REDDIT_HOSTS and not host.endswith("reddit.com"):
            raise ClassifyError("not a Reddit URL")
        raise ClassifyError("malformed URL — could not parse as a valid https URL")

    parsed = urlparse(normalized)

    if parsed.netloc != "www.reddit.com":
        raise ClassifyError(
            f"unsupported Reddit subdomain '{parsed.netloc}' — only www.reddit.com is accepted"
        )

    kind, sub_name = _classify_path(parsed.path)

    return {
        "source_type": kind,
        "subreddit_name": sub_name,
        "post_id": None,
        "normalized_url": normalized,
    }
