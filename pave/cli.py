# (C) 2025, 2026 Rodrigo Rodrigues da Silva <rodrigo@flowlexi.com>
# SPDX-License-Identifier: AGPL-3.0-or-later

from __future__ import annotations
import argparse, json, uuid, pathlib
from datetime import datetime, timezone
from pave.stores.factory import get_store
from pave.service import (
    create_collection as svc_create_collection,
    dump_archive as svc_dump_archive,
    restore_archive as svc_restore_archive,
    delete_collection as svc_delete_collection,
    rename_collection as svc_rename_collection,
    delete_document as svc_delete_document,
    ingest_document as svc_ingest_document,
    list_tenants as svc_list_tenants,
    list_collections as svc_list_collections,
    search as svc_search,
    ServiceError,
)
from pave.config import get_cfg, reload_cfg
from pave import metrics

store = get_store(get_cfg())

def _dump(out, pretty: bool = True):
    if pretty:
        print(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(json.dumps(out, ensure_ascii=False))

def _read(path: str) -> bytes:
    return pathlib.Path(path).read_bytes()

def cmd_create(args):
    out = svc_create_collection(store, args.tenant, args.collection)
    _dump(out, pretty=not args.compact)

def cmd_ingest(args):
    baseid = args.docid or str(uuid.uuid4())
    meta = json.loads(args.metadata) if args.metadata else {}
    content = _read(args.file)

    # CSV controls (optional)
    csv_opts = None
    if args.csv_has_header or args.csv_meta_cols or args.csv_include_cols:
        csv_opts = {
            "has_header": args.csv_has_header or "auto", # "auto" | "yes" | "no"
            "meta_cols": args.csv_meta_cols or "",       # "name1,name2" or "1,3"
            "include_cols": args.csv_include_cols or "", # "nameA,2,5"
        }

    out = svc_ingest_document(
        store, args.tenant, args.collection, args.file, content,
        baseid if args.docid else None, meta, csv_options=csv_opts
    )
    _dump(out, pretty=not args.compact)

def cmd_search(args):
    filters = json.loads(args.filters) if args.filters else None
    out = svc_search(store, args.tenant, args.collection, args.query, args.k,
                     filters=filters)
    _dump(out, pretty=not args.compact)

def cmd_delete(args):
    out = svc_delete_collection(store, args.tenant, args.collection)
    _dump(out, pretty=not args.compact)

def cmd_rename(args):
    out = svc_rename_collection(store, args.tenant, args.old_name, args.new_name)
    _dump(out, pretty=not args.compact)

def cmd_delete_document(args):
    out = svc_delete_document(store, args.tenant, args.collection, args.docid)
    _dump(out, pretty=not args.compact)

def cmd_dump_archive(args):
    cfg = get_cfg()
    data_dir = cfg.get("data_dir")
    if not data_dir:
        raise SystemExit("data directory is not configured")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = args.output or f"patchvec-data-{stamp}.zip"
    archive_path, _ = svc_dump_archive(store, data_dir, output)
    out = {
        "ok": True,
        "archive": archive_path,
        "source": str(data_dir),
    }
    _dump(out, pretty=not args.compact)

def cmd_restore_archive(args):
    cfg = get_cfg()
    data_dir = cfg.get("data_dir")
    if not data_dir:
        raise SystemExit("data directory is not configured")

    content = _read(args.file)
    out = svc_restore_archive(store, data_dir, content)
    _dump(out, pretty=not args.compact)

def cmd_reset_metrics(args):
    cfg = get_cfg()
    data_dir = cfg.get("data_dir")
    if data_dir:
        metrics.set_data_dir(data_dir)
    out = metrics.reset()
    _dump(out, pretty=not args.compact)

def cmd_list_tenants(args):
    cfg = get_cfg()
    data_dir = cfg.get("data_dir")
    if not data_dir:
        raise SystemExit("data directory is not configured")
    out = svc_list_tenants(store, data_dir)
    _dump(out, pretty=not args.compact)

def cmd_list_collections(args):
    out = svc_list_collections(store, args.tenant)
    _dump(out, pretty=not args.compact)

def main_cli(argv=None):
    p = argparse.ArgumentParser(prog="pavecli")
    p.add_argument(
        "--compact",
        action="store_true",
        help="Emit compact JSON for scripting",
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    #if p.config: reload_cfg(p.config)

    p_create = sub.add_parser("create-collection")
    p_create.add_argument("tenant")
    p_create.add_argument("collection")
    p_create.set_defaults(func=cmd_create)

    p_ingest = sub.add_parser("ingest")
    p_ingest.add_argument("tenant")
    p_ingest.add_argument("collection")
    p_ingest.add_argument("file")
    p_ingest.add_argument("--docid")
    p_ingest.add_argument("--metadata")

    # --- CSV controls ---
    p_ingest.add_argument("--csv-has-header", choices=["auto", "yes", "no"],
                          help="CSV header handling: auto (sniff), yes, or no")
    p_ingest.add_argument(
        "--csv-meta-cols",
        help="CSV columns for metadata only (not indexed). "
             "Names or 1-based indices, comma-separated")
    p_ingest.add_argument(
        "--csv-include-cols",
        help="CSV columns to index. Names or 1-based indices, "
             "comma-separated. Defaults to all non-meta columns")

    p_ingest.set_defaults(func=cmd_ingest)

    p_search = sub.add_parser("search")
    p_search.add_argument("tenant")
    p_search.add_argument("collection")
    p_search.add_argument("query")
    p_search.add_argument("-k", type=int, default=5)
    p_search.add_argument("--filters", help='JSON object, e.g. {"docid":"DOC-1"}')
    p_search.set_defaults(func=cmd_search)

    p_delete = sub.add_parser("delete-collection")
    p_delete.add_argument("tenant")
    p_delete.add_argument("collection")
    p_delete.set_defaults(func=cmd_delete)

    p_rename = sub.add_parser("rename-collection")
    p_rename.add_argument("tenant")
    p_rename.add_argument("old_name")
    p_rename.add_argument("new_name")
    p_rename.set_defaults(func=cmd_rename)

    p_delete_doc = sub.add_parser("delete-document")
    p_delete_doc.add_argument("tenant")
    p_delete_doc.add_argument("collection")
    p_delete_doc.add_argument("docid")
    p_delete_doc.set_defaults(func=cmd_delete_document)

    p_dump = sub.add_parser("dump-archive")
    p_dump.add_argument("--output", help="Destination ZIP file path")
    p_dump.set_defaults(func=cmd_dump_archive)

    p_restore = sub.add_parser("restore-archive")
    p_restore.add_argument("file")
    p_restore.set_defaults(func=cmd_restore_archive)

    p_reset_metrics = sub.add_parser("reset-metrics")
    p_reset_metrics.set_defaults(func=cmd_reset_metrics)

    p_list_tenants = sub.add_parser("list-tenants")
    p_list_tenants.set_defaults(func=cmd_list_tenants)

    p_list_collections = sub.add_parser("list-collections")
    p_list_collections.add_argument("tenant")
    p_list_collections.set_defaults(func=cmd_list_collections)

    args = p.parse_args(argv)
    try:
        return args.func(args)
    except ServiceError as exc:
        out = {"ok": False, "code": exc.code, "error": exc.message}
        _dump(out, pretty=not args.compact)
        return 1

if __name__ == "__main__":
    raise SystemExit(main_cli())
