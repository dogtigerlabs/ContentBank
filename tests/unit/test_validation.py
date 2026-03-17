"""
Unit tests for SHACL validation.
"""

import pytest
from pathlib import Path
from rdflib import Graph, Namespace, Literal, URIRef
from rdflib.namespace import RDF, XSD

from contentbank.core.validation import validate_object

TL = Namespace("https://tinylibrary.io/ns#")
SHAPES_DIR = str(Path(__file__).parent.parent.parent / "shapes")


AGENT_ID = URIRef("urn:cb:agent:550e8400-e29b-41d4-a716-446655440000")


def make_minimal_object(object_id: str, type_cls: URIRef, type_slug: str) -> Graph:
    """
    Build a minimal valid tl:Object graph for testing.
    Includes type declarations for all referenced nodes — required because
    sh:class constraints check the data graph, not just the shapes graph.
    """
    g = Graph()
    g.bind("tl", TL)

    # Declare tl:Individual singleton scope
    g.add((TL.Individual, RDF.type, TL.Scope))
    g.add((TL.Individual, TL.scopeOrder, Literal(3, datatype=XSD.integer)))

    # Declare a minimal valid tl:Agent (required because sh:class validates
    # all nodes of that type in the data graph)
    g.add((AGENT_ID, RDF.type, TL.Agent))
    g.add((AGENT_ID, TL.id, Literal(str(AGENT_ID), datatype=XSD.string)))
    g.add((AGENT_ID, TL.displayName, Literal("Test Agent", datatype=XSD.string)))
    g.add((AGENT_ID, TL.publicKey, Literal("dGVzdC1wdWJsaWMta2V5", datatype=XSD.string)))
    g.add((AGENT_ID, TL.createdAt, Literal("2026-03-16T00:00:00Z", datatype=XSD.dateTime)))

    obj = URIRef(object_id)
    g.add((obj, RDF.type, type_cls))
    g.add((obj, TL.id, Literal(object_id, datatype=XSD.string)))
    g.add((obj, TL.typeSlug, Literal(type_slug, datatype=XSD.string)))
    g.add((obj, TL.owner, AGENT_ID))
    g.add((obj, TL.scope, TL.Individual))
    g.add((obj, TL.createdAt, Literal("2026-03-16T00:00:00Z", datatype=XSD.dateTime)))
    g.add((obj, TL.updatedAt, Literal("2026-03-16T00:00:00Z", datatype=XSD.dateTime)))
    return g


def test_shapes_load():
    """Shapes directory loads without error."""
    from contentbank.core.validation import load_shapes
    g = load_shapes(SHAPES_DIR)
    assert len(g) > 0


def test_valid_object_passes():
    """A minimal valid object passes SHACL validation."""
    g = make_minimal_object(
        "urn:cb:photograph:550e8400-e29b-41d4-a716-446655440000",
        TL.Object,
        "photograph",
    )
    valid, violations = validate_object(g, SHAPES_DIR)
    assert valid, f"Expected valid, got violations: {violations}"


def test_missing_owner_fails():
    """An object without tl:owner fails SHACL validation."""
    g = make_minimal_object(
        "urn:cb:photograph:550e8400-e29b-41d4-a716-446655440001",
        TL.Object,
        "photograph",
    )
    obj = URIRef("urn:cb:photograph:550e8400-e29b-41d4-a716-446655440001")
    g.remove((obj, TL.owner, None))
    valid, violations = validate_object(g, SHAPES_DIR)
    assert not valid
    assert any("owner" in v.lower() for v in violations)


def test_invalid_id_format_fails():
    """An object with a malformed ID fails SHACL validation."""
    g = make_minimal_object(
        "urn:cb:photograph:550e8400-e29b-41d4-a716-446655440002",
        TL.Object,
        "photograph",
    )
    obj = URIRef("urn:cb:photograph:550e8400-e29b-41d4-a716-446655440002")
    g.remove((obj, TL.id, None))
    g.add((obj, TL.id, Literal("not-a-valid-id", datatype=XSD.string)))
    valid, violations = validate_object(g, SHAPES_DIR)
    assert not valid
