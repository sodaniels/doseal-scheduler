# app/utils/doseal/ensure_index.py
from pymongo import IndexModel
from pymongo.errors import OperationFailure

def _norm_keys(keys):
    """
    Normalize index 'key' specs into a canonical tuple, handling:
      • [("a", 1), ("b", -1)]
      • [{"a": 1}, {"b": -1}]
      • [("a", "text")] / [("a", "hashed")]
      • Any odd shapes -> string fallback
    """
    out = []
    seq = list(keys)
    for pair in seq:
        if isinstance(pair, (tuple, list)) and len(pair) == 2:
            k, v = pair
        elif isinstance(pair, dict) and len(pair) == 1:
            k, v = next(iter(pair.items()))
        else:
            out.append(str(pair))
            continue
        if isinstance(v, (int, float)):
            v = int(v)
        else:
            v = str(v)
        out.append((str(k), v))
    return tuple(out)

def _same_options(existing: dict, desired_doc: dict) -> bool:
    # Compare a few important options (extend if you use more)
    return (
        bool(existing.get("unique", False)) == bool(desired_doc.get("unique", False)) and
        existing.get("expireAfterSeconds")   == desired_doc.get("expireAfterSeconds") and
        bool(existing.get("sparse", False))  == bool(desired_doc.get("sparse", False)) and
        (existing.get("partialFilterExpression") or {}) == (desired_doc.get("partialFilterExpression") or {})
    )

def ensure_index(col, model: IndexModel):
    """
    Reconcile an index on `col` safely and idempotently:

    1) If an index with the same key pattern already exists:
       - If options AND (provided) name match -> do nothing.
       - Else drop that existing index and recreate with desired spec/name.

    2) If no index with same keys exists -> create it.

    3) If creation still fails with IndexOptionsConflict (code 85),
       defensively drop *all* indexes that match the same key pattern (any name),
       then retry creation once.
    """
    desired = model.document
    desired_keys  = _norm_keys(desired["key"])
    desired_name  = desired.get("name")  # may be None

    # Use list_indexes() (richer than index_information())
    existing = list(col.list_indexes())

    # First pass: find an index with *same key pattern*
    matched = None
    for idx in existing:
        if idx["name"] == "_id_":
            continue
        if _norm_keys(idx["key"]) == desired_keys:
            matched = idx
            break

    # Case A: an index with same keys exists
    if matched is not None:
        same_opts  = _same_options(matched, desired)
        name_ok    = (desired_name is None) or (matched["name"] == desired_name)

        if same_opts and name_ok:
            # Already good enough
            return

        # Drop the mismatched one (options/name differ), then recreate
        col.drop_index(matched["name"])
        try:
            col.create_indexes([model])
            return
        except OperationFailure as e:
            # Fallback: if conflict persists, drop-by-keys-all and recreate
            if getattr(e, "code", None) == 85:
                for idx in col.list_indexes():
                    if idx["name"] == "_id_":
                        continue
                    if _norm_keys(idx["key"]) == desired_keys:
                        try:
                            col.drop_index(idx["name"])
                        except Exception:
                            pass
                col.create_indexes([model])
                return
            raise

    # Case B: no index with these keys yet -> create
    try:
        col.create_indexes([model])
    except OperationFailure as e:
        if getattr(e, "code", None) == 85:
            # Another process created a conflicting name/options just now.
            # Drop any with same key pattern and retry once.
            for idx in col.list_indexes():
                if idx["name"] == "_id_":
                    continue
                if _norm_keys(idx["key"]) == desired_keys:
                    try:
                        col.drop_index(idx["name"])
                    except Exception:
                        pass
            col.create_indexes([model])
        else:
            raise
