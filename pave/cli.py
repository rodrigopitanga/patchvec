# (C) 2025 Rodrigo Rodrigues da Silva <rodrigopitanga@posteo.net>
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations
import argparse, json, uuid, pathlib
from datetime import datetime, timezone
from pave.stores.factory import get_store
from pave.service import (
    create_collection as svc_create_collection,
    dump_datastore as svc_dump_datastore,
    delete_collection as svc_delete_collection,
    ingest_document as svc_ingest_document,
    do_search as svc_do_search,
)
from pave.config import get_cfg, reload_cfg

store = get_store(get_cfg())

def _read(path: str) -> bytes:
    return pathlib.Path(path).read_bytes()

def cmd_create(args):
    out = svc_create_collection(store, args.tenant, args.collection)
    print(json.dumps(out, ensure_ascii=False))

def cmd_upload(args):
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
    print(json.dumps(out, ensure_ascii=False))

def cmd_search(args):
    filters = json.loads(args.filters) if args.filters else None
    out = svc_do_search(store, args.tenant, args.collection, args.query, args.k, filters=filters)
    print(json.dumps(out, ensure_ascii=False))

def cmd_delete(args):
    out = svc_delete_collection(store, args.tenant, args.collection)
    print(json.dumps(out, ensure_ascii=False))

def cmd_dump_datastore(args):
    cfg = get_cfg()
    data_dir = cfg.get("data_dir")
    if not data_dir:
        raise SystemExit("data directory is not configured")

    output = args.output or f"patchvec-data-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.zip"
    archive_path, _ = svc_dump_datastore(store, data_dir, output)
    out = {
        "ok": True,
        "archive": archive_path,
        "source": str(data_dir),
    }
    print(json.dumps(out, ensure_ascii=False))

def main_cli(argv=None):
    p = argparse.ArgumentParser(prog="pavecli")
    sub = p.add_subparsers(dest="cmd", required=True)
    #if p.config: reload_cfg(p.config)

    p_create = sub.add_parser("create-collection")
    p_create.add_argument("tenant")
    p_create.add_argument("collection")
    p_create.set_defaults(func=cmd_create)

    p_upload = sub.add_parser("upload")
    p_upload.add_argument("tenant")
    p_upload.add_argument("collection")
    p_upload.add_argument("file")
    p_upload.add_argument("--docid")
    p_upload.add_argument("--metadata")

    # --- CSV controls ---
    p_upload.add_argument("--csv-has-header", choices=["auto", "yes", "no"],
                          help="CSV header handling: auto (sniff), yes, or no")
    p_upload.add_argument("--csv-meta-cols",
                          help="CSV columns to store as metadata only (exclude from text). Names or 1-based indices, comma-separated")
    p_upload.add_argument("--csv-include-cols",
                          help="CSV columns to include in indexed text. Names or 1-based indices, comma-separated. Defaults to all non-meta columns")

    p_upload.set_defaults(func=cmd_upload)

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

    p_dump = sub.add_parser("dump-datastore")
    p_dump.add_argument("--output", help="Destination ZIP file path")
    p_dump.set_defaults(func=cmd_dump_datastore)

    args = p.parse_args(argv)
    return args.func(args)

if __name__ == "__main__":
    raise SystemExit(main_cli())
