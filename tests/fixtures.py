"""Test-only LLM responses. Production has no preset fallback."""
from azurai.director import Brief


def brief(idea="a red perfume bottle", title="Concept A"):
    return Brief(idea=idea, title=title, subject=idea, action="standing still",
                 scene="a quiet city street", composition="centered subject", shot="wide shot",
                 angle="eye level", lens="35mm", lighting="warm sunrise light",
                 palette="blue and amber", mood="hopeful", style="cinematic photography",
                 details="natural textures")


def concepts(idea="a red perfume bottle"):
    return [brief(idea, title).model_dump() for title in ("Concept A", "Concept B", "Concept C")]
