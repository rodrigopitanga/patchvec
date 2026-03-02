# (C) 2026 Rodrigo Rodrigues da Silva <rodrigo@flowlexi.com>
# SPDX-License-Identifier: AGPL-3.0-or-later


def test_api_invalid_csv_options_returns_code(client):
    client.post("/collections/acme/csvbad")
    files = {"file": ("bad.csv", b"a,b\n1,2\n", "text/csv")}
    r = client.post(
        "/collections/acme/csvbad/documents",
        files=files,
        params={
            "csv_has_header": "no",
            "csv_meta_cols": "b",
        },
    )
    # csv_has_header=no plus named columns triggers invalid_csv_options
    assert r.status_code == 400
    data = r.json()
    assert data["ok"] is False
    assert data["code"] == "invalid_csv_options"
