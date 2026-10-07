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


def postgres_store(testcase):
    """Isolate each integration test in a PostgreSQL schema."""
    import os
    import uuid
    from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode, quote
    import psycopg
    from psycopg import sql
    from azurai.auth import AccountStore
    url = os.environ.get("AZURAI_TEST_DATABASE_URL")
    if not url:
        testcase.skipTest("Set AZURAI_TEST_DATABASE_URL to run PostgreSQL integration tests")
    schema = "azurai_test_" + uuid.uuid4().hex
    with psycopg.connect(url, autocommit=True) as db:
        db.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    def cleanup():
        with psycopg.connect(url, autocommit=True) as db:
            db.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))
    testcase.addCleanup(cleanup)
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query))
    query["options"] = query.get("options", "") + " -csearch_path=" + schema + ",public"
    return AccountStore(urlunsplit(parts._replace(query=urlencode(query, quote_via=quote))))
