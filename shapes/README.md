# ContentBank SHACL Shapes

SHACL is the single source of truth for the ContentBank data model. API schemas (JSON Schema / OpenAPI) are generated from these shapes.

## Structure

```
shapes/
  core/
    core.ttl              ← Base classes: Object, Agent, Node, BlobAttachment, Scope
  capability/
    calendar/
      shapes.ttl          ← CalendarEvent, RecurrenceRule, Reminder
    inventory/
      shapes.ttl          ← InventoryItem, InventoryCollection, Location
```

## Namespace

| Prefix  | URI |
|---------|-----|
| `tl:`   | `https://tinylibrary.io/ns#` |
| `tlcal:` | `https://tinylibrary.io/capability/calendar#` |
| `tlinv:` | `https://tinylibrary.io/capability/inventory#` |

## Object Identity

All ContentBank Objects use the ID scheme:

```
urn:cb:{typeSlug}:{uuid}
```

- `typeSlug` enables prefix-scan filtering by type
- `uuid` is stable across the object's lifetime (content changes do not change the ID)
- `tl:contentHash` on `tl:Object` tracks current state for replication verification

## Scope

Four scope levels, ordered from least to most restrictive:

| Scope | Order |
|-------|-------|
| `tl:Community` | 0 |
| `tl:Group` | 1 |
| `tl:Family` | 2 |
| `tl:Individual` | 3 |

**Scope transitivity rule:** An Object MUST NOT reference another Object with a more restrictive scope. Enforced via `tl:ScopeTransitivityConstraint` (SPARQL-based SHACL constraint) on every write.

## Blob Attachments

Objects may have zero or more `tl:BlobAttachment` nodes. Each attachment carries:
- `tl:cid` — IPFS CIDv1 (base32, `bafy` prefix)
- `tl:mimeType` — MIME type of the binary
- `tl:blobRole` — role of this blob (`tl:primary`, `tl:thumbnail`, `tl:raw`, `tl:transcript`, `tl:preview`)
- `tl:byteSize` — optional byte count
- `tl:contentHash` — optional SHA-256 for out-of-band verification

## Capability Extension Pattern

Each Capability defines its types as `rdfs:subClassOf tl:Object`. Capability shapes:
1. Enforce a specific `tl:typeSlug` value
2. Add Capability-specific properties via `sh:property`
3. May reference cross-Capability objects via `tl:Object` (scope transitivity still applies)

Core fields inherited by all Capability types: `tl:id`, `tl:typeSlug`, `tl:owner`, `tl:scope`, `tl:createdAt`, `tl:updatedAt`, `tl:sourceNode`, `tl:contentHash`, `tl:blob`, `tl:capabilityMetadata`.

## Adding a New Capability

1. Create `shapes/capability/{name}/shapes.ttl`
2. Define a new namespace prefix (e.g. `tlcal:`, `tlinv:`)
3. Declare your types as `rdfs:subClassOf tl:Object`
4. Enforce `tl:typeSlug` with `sh:hasValue`
5. Do not redefine core properties — extend them
