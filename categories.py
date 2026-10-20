"""
Work categories.

The left side is what people (or the AI) write; the right side is the label
HRStop's task dropdown actually offers. The filler tries the aliases in order
and falls back to DEFAULT_CATEGORY when nothing matches.

Confirmed against the live dropdown (select.ddlProjectTask) via inspect_form.py.
"""

SITE_CATEGORIES = [
    "Development", "Analysis & Design", "Testing", "Support", "Internal Meeting",
    "Upskilling", "Client Meeting", "Recruiting", "Performance Assessment", "Shadowing",
]

DEFAULT_CATEGORY = "Analysis & Design"

CATEGORY_ALIASES = {
    "Internal Meeting": ["Internal Meeting"],
    "Client Meeting":   ["Client Meeting"],
    "Analysis":         ["Analysis & Design"],
    "Designing":        ["Analysis & Design"],
    "Design":           ["Analysis & Design"],
    "Development":      ["Development"],
    "Testing":          ["Testing"],
    "Support":          ["Support"],
    "Learning":         ["Upskilling"],         # courses/training land here, not a fallback
    "Documentation":    ["Analysis & Design"],  # no dedicated category on this site
}

# What the AI is allowed to pick from: friendly names first, then any other site label.
AI_CATEGORIES = list(CATEGORY_ALIASES) + [c for c in SITE_CATEGORIES if c not in CATEGORY_ALIASES]
