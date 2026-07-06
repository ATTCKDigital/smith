# Adapted (copied, not imported) from armory services/website-indexer/website_indexer/classifier.py.
# Vendored into smith-research per user instruction: no runtime coupling to armory.
# GENERALIZED from the attck.com-specific armory version: the original hardcoded
# attck.com URL slugs (/work → case_study, /planofattck → process, etc.). This
# version keeps the same signature and return domain but classifies on GENERIC
# path patterns so it works for any target site.
"""Content-type classifier for arbitrary website URLs.

Maps URL paths to a content_type string used as a Qdrant payload field. Pure
function — no I/O, no external dependencies.

Classification rules (evaluated in order; first path segment matched as substring):
  blog / news / article / post          → "blog"
  case-stud / work / portfolio / customer → "case_study"
  pricing / plans / cost                 → "pricing"
  about / team / company / leadership    → "about"
  contact                                → "contact"
  product / service / solution / feature → "service"
  empty path                             → "other"
  everything else                        → "other"
"""

from urllib.parse import urlparse

# Ordered list of (needles, content_type). Evaluated top to bottom; the first
# group with any needle appearing in the first path segment wins. Order matters:
# more specific categories precede the generic "service" bucket.
_PATTERNS: list[tuple[tuple[str, ...], str]] = [
    (("blog", "news", "article", "post"), "blog"),
    (("case-stud", "work", "portfolio", "customer"), "case_study"),
    (("pricing", "plans", "cost"), "pricing"),
    (("about", "team", "company", "leadership"), "about"),
    (("contact",), "contact"),
    (("product", "service", "solution", "feature"), "service"),
]


def classify_content_type(url: str) -> str:
    """Return the content_type string for the given page URL.

    Args:
        url: Absolute or relative URL string.

    Returns:
        One of: "blog", "case_study", "service", "process", "about",
        "pricing", "contact", "other".
    """
    path = urlparse(url).path.strip("/")
    segments = [s for s in path.split("/") if s]

    # Root URL or empty path
    if not segments:
        return "other"

    first = segments[0].lower()

    for needles, content_type in _PATTERNS:
        if any(needle in first for needle in needles):
            return content_type

    return "other"
