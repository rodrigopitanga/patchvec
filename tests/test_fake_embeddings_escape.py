# (C) 2025 Rodrigo Rodrigues da Silva <rodrigopitanga@posteo.net>
# SPDX-License-Identifier: GPL-3.0-or-later

"""Test that FakeEmbeddings correctly handles escaped single quotes in filter values."""

from utils import FakeEmbeddings


def test_fake_embeddings_escaped_single_quote():
    """Test that filter values with escaped single quotes are correctly unescaped."""
    fake = FakeEmbeddings({})
    
    # Index a document with a single quote in metadata
    # The metadata is stored in the payload dict
    docs = [
        ("doc1", {"text": "test content", "author": "O'Brien"}, '{"author": "O\'Brien"}'),
        ("doc2", {"text": "another test", "author": "Smith"}, '{"author": "Smith"}'),
    ]
    fake.index(docs)
    
    # Search with a filter that includes an escaped single quote (as it would appear in SQL)
    # The SQL sanitizer in txtai_store.py escapes ' as ''
    sql = "SELECT * FROM txtai WHERE similar('test') AND [author] = 'O''Brien'"
    results = fake.search(sql)
    
    # Should find doc1 but not doc2
    assert len(results) == 1
    assert results[0]["id"] == "doc1"
    assert results[0]["text"] == "test content"


def test_fake_embeddings_no_escape_needed():
    """Test that filter values without single quotes still work correctly."""
    fake = FakeEmbeddings({})
    
    # Index documents without single quotes
    docs = [
        ("doc1", {"text": "test content", "author": "Smith"}, '{"author": "Smith"}'),
        ("doc2", {"text": "another test", "author": "Jones"}, '{"author": "Jones"}'),
    ]
    fake.index(docs)
    
    # Search with a normal filter
    sql = "SELECT * FROM txtai WHERE similar('test') AND [author] = 'Smith'"
    results = fake.search(sql)
    
    # Should find doc1
    assert len(results) == 1
    assert results[0]["id"] == "doc1"


def test_fake_embeddings_multiple_escaped_quotes():
    """Test that multiple escaped single quotes in a value are handled correctly."""
    fake = FakeEmbeddings({})
    
    # Index a document with multiple single quotes in metadata
    docs = [
        ("doc1", {"text": "test content", "title": "It's a boy's life"}, '{"title": "It\'s a boy\'s life"}'),
        ("doc2", {"text": "another test", "title": "Simple title"}, '{"title": "Simple title"}'),
    ]
    fake.index(docs)
    
    # Search with a filter that has multiple escaped single quotes
    sql = "SELECT * FROM txtai WHERE similar('test') AND [title] = 'It''s a boy''s life'"
    results = fake.search(sql)
    
    # Should find doc1
    assert len(results) == 1
    assert results[0]["id"] == "doc1"
