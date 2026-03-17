"""
SHACL validation for ContentBank object writes.

All writes pass through validate_object() before reaching storage.
Validation loads shapes once at startup and caches the combined graph.
"""

from pathlib import Path
from functools import lru_cache
import logging

from rdflib import Graph
from pyshacl import validate

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def load_shapes(shapes_dir: str) -> Graph:
    """
    Load all .ttl files under shapes_dir into a combined shapes graph.
    Cached — shapes are loaded once at startup.
    """
    g = Graph()
    shapes_path = Path(shapes_dir)
    ttl_files = sorted(shapes_path.rglob("*.ttl"))
    if not ttl_files:
        raise FileNotFoundError(f"No .ttl files found under {shapes_dir}")
    for ttl_file in ttl_files:
        g.parse(str(ttl_file), format="turtle")
    logger.info(f"Loaded {len(ttl_files)} shape files ({len(g)} triples)")
    return g


def validate_object(data_graph: Graph, shapes_dir: str) -> tuple[bool, list[str]]:
    """
    Validate an RDF data graph against the ContentBank SHACL shapes.

    Args:
        data_graph: rdflib Graph containing the object(s) to validate
        shapes_dir: path to shapes directory (used to load/cache shapes)

    Returns:
        (valid: bool, violations: list[str])
        violations is empty when valid is True.
    """
    shapes_graph = load_shapes(shapes_dir)

    conforms, results_graph, results_text = validate(
        data_graph,
        shacl_graph=shapes_graph,
        inference="rdfs",
        abort_on_first=False,
        allow_infos=False,
        allow_warnings=False,
    )

    if conforms:
        return True, []

    # Extract violation messages from results graph
    violations = []
    for line in results_text.splitlines():
        line = line.strip()
        if line and not line.startswith("Validation Report") and not line.startswith("---"):
            violations.append(line)

    return False, violations
