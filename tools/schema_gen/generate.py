#!/usr/bin/env python3
"""
SHACL → JSON Schema generator for TinyLibrary ContentBank.

Reads all .ttl files under a shapes directory, extracts sh:NodeShape
definitions annotated with tl: API annotations, and emits JSON Schema
documents for create, update, and response (read) operations per type.

Usage:
    python generate.py --shapes ../../shapes --out ../../generated/schemas

Output (per discovered sh:NodeShape with tl:typeSlug):
    {typeSlug}_create.json    Input schema for POST (create)
    {typeSlug}_update.json    Input schema for PATCH (update, mutable fields only)
    {typeSlug}_response.json  Output schema (all readable fields)
    {typeSlug}_list_params.json  Query parameters for list/filter operations
"""

import json
import argparse
from pathlib import Path
from rdflib import Graph, Namespace, URIRef, Literal, BNode
from rdflib.namespace import RDF, RDFS, XSD, OWL, SH

# TinyLibrary namespaces
TL = Namespace("https://tinylibrary.io/ns#")

# XSD → JSON Schema type mapping
XSD_TYPE_MAP = {
    str(XSD.string):   {"type": "string"},
    str(XSD.integer):  {"type": "integer"},
    str(XSD.int):      {"type": "integer"},
    str(XSD.long):     {"type": "integer"},
    str(XSD.decimal):  {"type": "number"},
    str(XSD.float):    {"type": "number"},
    str(XSD.double):   {"type": "number"},
    str(XSD.boolean):  {"type": "boolean"},
    str(XSD.dateTime): {"type": "string", "format": "date-time"},
    str(XSD.date):     {"type": "string", "format": "date"},
}


def load_shapes(shapes_dir: Path) -> Graph:
    """Load all .ttl files under shapes_dir into a single rdflib Graph."""
    g = Graph()
    g.bind("tl", TL)
    g.bind("sh", SH)
    ttl_files = list(shapes_dir.rglob("*.ttl"))
    if not ttl_files:
        raise FileNotFoundError(f"No .ttl files found under {shapes_dir}")
    for ttl_file in sorted(ttl_files):
        g.parse(str(ttl_file), format="turtle")
    print(f"Loaded {len(ttl_files)} shape files ({len(g)} triples)")
    return g


def get_str(g: Graph, subject, predicate, default=None):
    """Return first string value of predicate on subject, or default."""
    val = g.value(subject, predicate)
    if val is None:
        return default
    return str(val)


def get_bool(g: Graph, subject, predicate, default=False):
    val = g.value(subject, predicate)
    if val is None:
        return default
    return str(val).lower() == "true"


def resolve_property_schema(g: Graph, prop_shape) -> dict:
    """
    Convert a sh:PropertyShape blank node to a JSON Schema property fragment.
    Returns a dict with keys: schema, access, mutable, filterable, sortable,
    description, example, required, max_count.
    """
    path = g.value(prop_shape, SH.path)
    if path is None:
        return None

    path_str = str(path)
    prop_name = path_str.split("#")[-1].split("/")[-1]

    # --- API annotations ---
    access     = get_str(g, prop_shape, TL.apiAccess, "readwrite")
    mutable    = get_bool(g, prop_shape, TL.apiMutable, True)
    filterable = get_bool(g, prop_shape, TL.apiListFilterable, False)
    sortable   = get_bool(g, prop_shape, TL.apiSortable, False)
    description = get_str(g, prop_shape, TL.apiDescription) or \
                  get_str(g, prop_shape, RDFS.comment)
    example    = get_str(g, prop_shape, TL.apiExample)

    # --- Cardinality ---
    min_count = g.value(prop_shape, SH.minCount)
    max_count = g.value(prop_shape, SH.maxCount)
    required  = int(str(min_count)) >= 1 if min_count is not None else False
    is_array  = max_count is None or int(str(max_count)) > 1

    # --- Type resolution ---
    datatype = g.value(prop_shape, SH.datatype)
    node_kind = g.value(prop_shape, SH.nodeKind)
    sh_class  = g.value(prop_shape, SH["class"])
    has_value = g.value(prop_shape, SH.hasValue)
    sh_in     = list(g.objects(prop_shape, SH["in"]))

    schema = {}

    if has_value is not None:
        # Constant value — const in JSON Schema
        schema = {"const": str(has_value)}

    elif datatype is not None:
        base = XSD_TYPE_MAP.get(str(datatype), {"type": "string"})
        schema = dict(base)
        # Constraints
        min_incl = g.value(prop_shape, SH.minInclusive)
        if min_incl is not None:
            schema["minimum"] = float(str(min_incl)) if "." in str(min_incl) else int(str(min_incl))
        pattern = g.value(prop_shape, SH.pattern)
        if pattern is not None:
            schema["pattern"] = str(pattern)
        # sh:in → enum (sh:in uses RDF list; iterate via g.items())
        in_list_node = g.value(prop_shape, SH["in"])
        if in_list_node is not None:
            schema["enum"] = [str(v) for v in g.items(in_list_node)]

    elif sh_class is not None or node_kind is not None:
        # IRI reference — represent as string URI in JSON Schema
        schema = {"type": "string", "format": "uri"}

    elif list(g.objects(prop_shape, SH["or"])):
        # sh:or → anyOf
        or_schemas = []
        for or_node in g.objects(prop_shape, SH["or"]):
            # Collect items in the RDF list
            items = list(g.items(or_node))
            for item in items:
                or_schemas.append({"type": "string", "format": "uri"})
        schema = {"anyOf": or_schemas} if or_schemas else {"type": "string"}

    else:
        schema = {"type": "string"}

    # Wrap in array if multi-valued
    if is_array and max_count is None:
        schema = {"type": "array", "items": schema}

    if description:
        schema["description"] = description
    if example:
        try:
            schema["examples"] = [json.loads(example)]
        except Exception:
            schema["examples"] = [example]

    return {
        "name": prop_name,
        "schema": schema,
        "access": access,
        "mutable": mutable,
        "filterable": filterable,
        "sortable": sortable,
        "required": required,
        "is_array": is_array,
    }


def generate_schemas_for_shape(g: Graph, shape_node, type_slug: str) -> dict:
    """
    Generate create, update, response, and list_params schemas for a NodeShape.
    Returns dict keyed by operation name.
    """
    operations_str = get_str(g, shape_node, TL.apiOperations,
                             "create,get,update,delete,list")
    operations = [op.strip() for op in operations_str.split(",")]
    paginates = get_bool(g, shape_node, TL.apiPaginates, True)

    props = []
    for prop_shape in g.objects(shape_node, SH.property):
        p = resolve_property_schema(g, prop_shape)
        if p:
            props.append(p)

    # --- Response schema (all readable fields) ---
    response_props = {}
    response_required = []
    for p in props:
        if p["access"] in ("read", "readwrite"):
            response_props[p["name"]] = p["schema"]
            if p["required"]:
                response_required.append(p["name"])

    response_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": f"{type_slug} (response)",
        "type": "object",
        "properties": response_props,
    }
    if response_required:
        response_schema["required"] = response_required

    # --- Create schema (write + readwrite fields, excluding read-only) ---
    # Deduplicate by property name — Capability shapes may redeclare a property
    # from the base ObjectShape (e.g. typeSlug with sh:hasValue). The most
    # specific declaration (last seen) wins; read-access always wins over write.
    create_props_raw: dict[str, dict] = {}
    for p in props:
        name = p["name"]
        if p["access"] == "read":
            # read-only always excludes from create
            create_props_raw[name] = None
        elif name not in create_props_raw or create_props_raw[name] is not None:
            create_props_raw[name] = p

    create_props = {}
    create_required = []
    for name, p in create_props_raw.items():
        if p is None:
            continue
        # Skip const values (server-derived)
        if "const" in p["schema"] or (
            p["schema"].get("type") == "array" and
            "const" in p["schema"].get("items", {})
        ):
            continue
        create_props[name] = p["schema"]
        if p["required"]:
            create_required.append(name)

    create_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": f"{type_slug} (create)",
        "type": "object",
        "properties": create_props,
    }
    if create_required:
        create_schema["required"] = create_required

    # --- Update schema (mutable write + readwrite fields, all optional) ---
    update_props = {}
    for p in props:
        if p["access"] in ("write", "readwrite") and p["mutable"]:
            update_props[p["name"]] = p["schema"]

    update_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": f"{type_slug} (update)",
        "type": "object",
        "properties": update_props,
        "minProperties": 1,
    }

    # --- List params schema ---
    list_props = {
        "limit": {"type": "integer", "minimum": 1, "maximum": 500,
                  "default": 50, "description": "Maximum results to return."},
    }
    if paginates:
        list_props["cursor"] = {"type": "string",
                                "description": "Pagination cursor from previous response."}
    list_props["sort"] = {
        "type": "string",
        "description": "Sort field. Prefix with '-' for descending.",
    }

    # Add filterable fields as optional query params
    for p in props:
        if p["filterable"]:
            list_props[p["name"]] = dict(p["schema"])
            list_props[p["name"]]["description"] = \
                f"Filter by {p['name']}. " + \
                list_props[p["name"]].get("description", "")

    list_params_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": f"{type_slug} (list params)",
        "type": "object",
        "properties": list_props,
    }

    result = {}
    if "get" in operations or "create" in operations or "update" in operations:
        result["response"] = response_schema
    if "create" in operations:
        result["create"] = create_schema
    if "update" in operations:
        result["update"] = update_schema
    if "list" in operations:
        result["list_params"] = list_params_schema

    return result


def discover_shapes(g: Graph) -> list:
    """
    Find all sh:NodeShape nodes that have a tl:typeSlug sh:hasValue annotation.
    Returns list of (shape_node, type_slug) tuples.
    """
    results = []
    for shape_node in g.subjects(RDF.type, SH.NodeShape):
        for prop_shape in g.objects(shape_node, SH.property):
            path = g.value(prop_shape, SH.path)
            if str(path) == str(TL.typeSlug):
                has_value = g.value(prop_shape, SH.hasValue)
                if has_value:
                    results.append((shape_node, str(has_value)))
    return results


def main():
    parser = argparse.ArgumentParser(
        description="Generate JSON Schema from TinyLibrary SHACL shapes.")
    parser.add_argument("--shapes", type=Path,
                        default=Path(__file__).parent.parent.parent / "shapes",
                        help="Path to shapes directory (default: ../../shapes)")
    parser.add_argument("--out", type=Path,
                        default=Path(__file__).parent.parent.parent / "generated" / "schemas",
                        help="Output directory for generated schemas")
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)

    g = load_shapes(args.shapes)
    shapes = discover_shapes(g)

    if not shapes:
        print("No annotated NodeShapes found (need tl:typeSlug sh:hasValue).")
        return

    print(f"Found {len(shapes)} shapes: {[s for _, s in shapes]}")

    for shape_node, type_slug in shapes:
        schemas = generate_schemas_for_shape(g, shape_node, type_slug)
        for operation, schema in schemas.items():
            out_file = args.out / f"{type_slug}_{operation}.json"
            out_file.write_text(json.dumps(schema, indent=2))
            print(f"  Wrote {out_file.name}")

    print(f"\nDone. {sum(len(s) for _, s in [(n, generate_schemas_for_shape(g, n, sl)) for n, sl in shapes])} schemas generated.")


if __name__ == "__main__":
    main()
