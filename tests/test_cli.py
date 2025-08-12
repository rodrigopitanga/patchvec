
from pave import cli as pvcli
from conftest import DummyStore

def test_cli_flow(tmp_path):
    pvcli.store = DummyStore()
    main = pvcli.main_cli
    main(["create-collection", "acme", "invoices"])
    sample = tmp_path / "s.txt"
    sample.write_text("one two three")
    main(["upload", "acme", "invoices", str(sample), "--docid", "D1", "--metadata", '{"k":"v"}'])
    main(["search", "acme", "invoices", "two", "-k", "3"])
    main(["delete-collection", "acme", "invoices"])
