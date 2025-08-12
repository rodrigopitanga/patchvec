# (C) 2025 Rodrigo Rodrigues da Silva <rodrigopitanga@posteo.net>
# SPDX-License-Identifier: GPL-3.0-or-later

# (C) 2025 Rodrigo Rodrigues da Silva <rodrigopitanga@posteo.net>
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations
import argparse, json, uuid, pathlib
from .stores.factory import get_store
from .service import (
    create_collection as svc_create_collection,
    delete_collection as svc_delete_collection,
    ingest_document as svc_ingest_document,
    do_search as svc_do_search,
)
from .config import CFG

store = get_store(CFG)

def _read(path: str) -> bytes:
    return pathlib.Path(path).read_bytes()

def cmd_create(args):
    out = svc_create_collection(store, args.tenant, args.collection)
    print(json.dumps(out, ensure_ascii=False))

def cmd_upload(args):
    baseid = args.docid or str(uuid.uuid4())
    meta = json.loads(args.metadata) if args.metadata else {}
    content = _read(args.file)
    out = svc_ingest_document(
        store, args.tenant, args.collection, args.file, content,
        baseid if args.docid else None, meta
    )
    print(json.dumps(out, ensure_ascii=False))

def cmd_search(args):
    filters = json.loads(args.filters) if args.filters else None
    out = svc_do_search(store, args.tenant, args.collection, args.query, args.k, filters=filters)
    print(json.dumps(out, ensure_ascii=False))

def cmd_delete(args):
    out = svc_delete_collection(store, args.tenant, args.collection)
    print(json.dumps(out, ensure_ascii=False))

def main_cli(argv=None):
    p = argparse.ArgumentParser(prog="pavecli")
    sub = p.add_subparsers(dest="cmd", required=True)

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

    args = p.parse_args(argv)
    return args.func(args)

if __name__ == "__main__":
    raise SystemExit(main_cli())
