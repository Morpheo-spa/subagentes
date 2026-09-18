#!/usr/bin/env python3
"""Smoke test of a RUNNING Estampa deployment, end to end.

Drives the full life of a delivery note the way a customer would, and consults
it the way an inspector would: session and cookie rotation, DECA catalogue and
validation, native PDF generation with embedded QR, the public viewer and its
headers, uploads (duplicate, scan, non-PDF), the immutable revision chain,
listing, history and export, the print queue and a traced print job, viewer
permissions, the SSRF guard on storage endpoints, and logout revocation.

It needs a deployment with the demo tenant seeded (`make seed`) and the SSRF
guard ON (ALLOW_PRIVATE_STORAGE_ENDPOINTS=false, the production posture).
Every step asserts; the first failure stops the run and prints the response.

    python scripts/smoke.py https://estampa.example https://estampa.example
    python scripts/smoke.py http://127.0.0.1:8000 http://127.0.0.1:5173   # local

The second argument is the Origin the SPA would send; the API only accepts a
cookie refresh from its own PUBLIC_BASE_URL.
"""

from __future__ import annotations

import sys
import uuid

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
ORIGIN = sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:5173"
API = f"{BASE}/api/v1"
ADMIN = ("admin@estampa-demo.com", "estampa-demo-2026")
VIEWER = ("viewer@estampa-demo.com", "estampa-demo-2026")

DECA = {
    "cargador_nombre": "Cargas del Norte SL",
    "cargador_nif": "B12345674",
    "cargador_domicilio": "Polígono Sur 12, Zaragoza",
    "transportista_nombre": "Transportes Ebro SA",
    "transportista_nif": "A58818501",
    "origen": "Zaragoza",
    "destino": "Bilbao",
    "mercancia_naturaleza": "Bobinas de papel",
    "mercancia_peso": "18.5",
    "mercancia_peso_unidad": "t",
    "fecha_transporte": "2026-10-06",
    "matricula_vehiculo": "1234 KLM",
}

results: list[tuple[str, str]] = []


def step(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, "OK" if ok else "FAIL"))
    print(f"{'OK  ' if ok else 'FAIL'} {name}{(' :: ' + detail) if detail else ''}")
    if not ok:
        print("\n".join(f"{n:50} {s}" for n, s in results))
        sys.exit(1)


def main() -> None:
    with httpx.Client(
        base_url=API, headers={"Origin": ORIGIN, "Accept-Language": "es"}, timeout=30
    ) as c:
        # --- session ---------------------------------------------------------
        r = c.post("/auth/login", json={"email": ADMIN[0], "password": ADMIN[1]})
        step("login admin", r.status_code == 200, r.text[:200])
        body = r.json()
        step("refresh token absent from body", "refresh_token" not in body["tokens"])
        cookie = c.cookies.get("estampa_refresh")
        step("refresh cookie set", bool(cookie))
        access = body["tokens"]["access_token"]
        auth = {"Authorization": f"Bearer {access}"}

        r = c.get("/auth/me", headers=auth)
        step("GET /auth/me", r.status_code == 200, r.text[:200])
        me = r.json()
        step("admin has >1 site", len(me["sites"]) >= 2, str(len(me["sites"])))

        # --- DECA catalogue ----------------------------------------------------
        r = c.get("/deca/fields", headers=auth)
        step(
            "GET /deca/fields",
            r.status_code == 200 and len(r.json()["fields"]) >= 12,
            r.text[:120],
        )
        r = c.post(
            "/deca/validate",
            headers=auth,
            json={"deca": {**DECA, "cargador_nif": "B12345670"}},
        )
        step(
            "validate rejects a bad NIF",
            r.status_code == 200
            and any(
                e["code"] == "DECA_NIF_INVALID" for e in r.json().get("errors", [])
            ),
            r.text[:200],
        )

        # --- generate a native DeCA PDF ---------------------------------------
        r = c.post("/documents/generate", headers=auth, json={"deca": DECA})
        step("POST /documents/generate", r.status_code in (200, 201), r.text[:300])
        doc = r.json()
        doc_id = doc["id"]
        step(
            "generated doc is compliant",
            doc["compliance_status"] == "compliant",
            doc["compliance_status"],
        )
        step(
            "generated doc origin=generated",
            doc["origin"] == "generated",
            doc["origin"],
        )
        step(
            "QR embedded flag",
            doc.get("qr_embedded") is True,
            str(doc.get("qr_embedded")),
        )

        r = c.get(f"/documents/{doc_id}/file", headers=auth)
        step(
            "download generated PDF",
            r.status_code == 200 and r.content[:5] == b"%PDF-",
            str(r.status_code),
        )
        pdf_bytes = r.content
        r = c.get(f"/documents/{doc_id}/qr.png", headers=auth)
        step(
            "QR png",
            r.status_code == 200 and r.content[:8] == b"\x89PNG\r\n\x1a\n",
            str(r.status_code),
        )
        r = c.get(f"/documents/{doc_id}", headers=auth)
        step("GET /documents/{id}", r.status_code == 200, r.text[:200])
        public_url = r.json().get("public_url") or ""
        step("public_url present", public_url.startswith("http"), public_url)
        token = public_url.rstrip("/").split("/")[-1]

        # --- public viewer, no session ----------------------------------------
        with httpx.Client(base_url=BASE, timeout=30) as p:
            r = p.get(f"/v/{token}", headers={"Accept": "application/json"})
            step("public GET /v/{token}", r.status_code == 200, r.text[:200])
            step(
                "noindex header",
                r.headers.get("x-robots-tag", "").startswith("noindex"),
            )
            step("no-store header", "no-store" in r.headers.get("cache-control", ""))
            step("nosniff header", r.headers.get("x-content-type-options") == "nosniff")
            r = p.get(f"/v/{token}/file")
            step(
                "public PDF served inline",
                r.status_code == 200
                and r.content[:5] == b"%PDF-"
                and "inline" in r.headers.get("content-disposition", ""),
                r.headers.get("content-disposition", ""),
            )
            step(
                "public PDF has CSP",
                "default-src 'none'" in r.headers.get("content-security-policy", ""),
            )
            bogus = p.get(
                f"/v/{uuid.uuid4().hex}", headers={"Accept": "application/json"}
            )
            step("unknown token is 404", bogus.status_code == 404, bogus.text[:120])
            r = p.head(f"/v/{token}")
            step("HEAD /v/{token}", r.status_code == 200, str(r.status_code))

        # --- upload the generated PDF again as a customer PDF (native) --------
        files = [("files", ("albaran-ebro.pdf", pdf_bytes, "application/pdf"))]
        r = c.post("/documents/", headers=auth, files=files)
        step("POST /documents/ multipart", r.status_code in (200, 201), r.text[:300])
        items = r.json()["items"]
        step(
            "one item accepted",
            len(items) == 1 and items[0]["accepted"],
            str(items)[:200],
        )
        warnings = {w["code"] for w in items[0].get("warnings", [])}
        step(
            "duplicate detected as warning",
            "DUPLICATE_DOCUMENT" in warnings,
            str(warnings),
        )
        uploaded_id = items[0]["document"]["id"]

        # a scan: a PDF with no text layer must be archived but flagged
        scan = b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF"
        r = c.post(
            "/documents/",
            headers=auth,
            files=[("files", ("foto.pdf", scan, "application/pdf"))],
        )
        step("POST scan", r.status_code in (200, 201), r.text[:200])
        item = r.json()["items"][0]
        step(
            "scan is NOT_A_DECA",
            item["accepted"] and item["document"]["compliance_status"] == "not_a_deca",
            str(item["document"].get("compliance_status")),
        )

        # not a PDF at all
        r = c.post(
            "/documents/",
            headers=auth,
            files=[("files", ("x.pdf", b"hello", "application/pdf"))],
        )
        item = r.json()["items"][0]
        step(
            "non-PDF rejected per file",
            not item["accepted"] and item["error"]["code"] == "DOCUMENT_NOT_PDF",
            str(item.get("error")),
        )

        # --- revision chain ---------------------------------------------------
        r = c.post(
            f"/documents/{doc_id}/revisions",
            headers=auth,
            json={"deca": {**DECA, "matricula_vehiculo": "5678 NPQ"}},
        )
        step(
            "revision without reason refused", r.status_code in (400, 422), r.text[:120]
        )
        r = c.post(
            f"/documents/{doc_id}/revisions",
            headers=auth,
            json={
                "deca": {**DECA, "matricula_vehiculo": "5678 NPQ"},
                "change_reason": "Cambio de tractora",
            },
        )
        step("revision created", r.status_code in (200, 201), r.text[:200])
        rev = r.json()
        step(
            "revision=2 supersedes original",
            rev["revision"] == 2 and rev["supersedes_id"] == doc_id,
            str(rev.get("revision")),
        )
        r = c.get(f"/documents/{doc_id}", headers=auth)
        step(
            "original marked superseded",
            r.json()["compliance_status"] == "superseded",
            r.json()["compliance_status"],
        )
        with httpx.Client(base_url=BASE, timeout=30) as p:
            r = p.get(f"/v/{token}", headers={"Accept": "application/json"})
            step("old QR no longer serves", r.status_code == 404, str(r.status_code))

        # --- listing, history, export ----------------------------------------
        r = c.get("/documents/", headers=auth, params={"page": 1, "page_size": 10})
        step(
            "GET /documents/ paginated",
            r.status_code == 200
            and {"items", "total", "page", "page_size"} <= set(r.json()),
            r.text[:120],
        )
        r = c.get(f"/documents/{doc_id}/history", headers=auth)
        step(
            "history has revision + accesses",
            r.status_code == 200
            and len(r.json()["revisions"]) >= 1
            and len(r.json()["public_accesses"]) >= 1,
            r.text[:200],
        )
        r = c.get("/documents/export.csv", headers=auth)
        step(
            "export.csv",
            r.status_code == 200
            and "X-Export-Total" in r.headers
            and r.text.startswith(("id", "﻿id", "guid")),
            r.text[:80],
        )

        # --- printing ---------------------------------------------------------
        r = c.get("/printing/templates", headers=auth)
        step("templates", r.status_code == 200 and r.json()["items"], r.text[:120])
        template = r.json()["items"][0]["code"]
        r = c.post(
            "/printing/queue/",
            headers=auth,
            json={"document_ids": [rev["id"], uploaded_id], "copies": 2},
        )
        step("queue add", r.status_code in (200, 201), r.text[:200])
        r = c.get("/printing/queue/", headers=auth)
        step(
            "queue lists 2",
            r.status_code == 200 and r.json()["total"] == 2,
            r.text[:120],
        )
        r = c.post(
            "/printing/jobs/",
            headers=auth,
            json={
                "printer_name": "Zebra muelle 3",
                "layout": "sheet",
                "template_code": template,
                "start_position": 1,
            },
        )
        step("job created before printing", r.status_code in (200, 201), r.text[:200])
        job = r.json()
        r = c.get(f"/printing/jobs/{job['id']}/render", headers=auth)
        step(
            "job render html",
            r.status_code == 200 and "<html" in r.text.lower(),
            str(r.status_code),
        )
        r = c.post(
            f"/printing/jobs/{job['id']}/confirm", headers=auth, json={"success": True}
        )
        step(
            "job confirmed",
            r.status_code == 200 and r.json()["status"] == "printed",
            r.text[:120],
        )
        r = c.get(f"/documents/{uploaded_id}", headers=auth)
        step(
            "print_count incremented",
            r.json()["print_count"] >= 2,
            str(r.json()["print_count"]),
        )

        # --- permissions: viewer cannot upload ----------------------------------
        with httpx.Client(base_url=API, headers={"Origin": ORIGIN}, timeout=30) as v:
            r = v.post("/auth/login", json={"email": VIEWER[0], "password": VIEWER[1]})
            step("login viewer", r.status_code == 200, r.text[:120])
            vauth = {"Authorization": f"Bearer {r.json()['tokens']['access_token']}"}
            r = v.post("/documents/generate", headers=vauth, json={"deca": DECA})
            step(
                "viewer forbidden to generate",
                r.status_code == 403
                and r.json()["detail"]["code"] == "PERMISSION_DENIED",
                r.text[:120],
            )

        # --- storage SSRF guard through the real API ----------------------------
        r = c.post(
            "/storage/",
            headers=auth,
            json={
                "name": "evil",
                "kind": "s3",
                "config": {
                    "bucket": "x",
                    "endpoint_url": "http://169.254.169.254/latest/meta-data/",
                },
                "secrets": {"access_key_id": "a", "secret_access_key": "b"},
            },
        )
        step(
            "metadata endpoint refused",
            r.status_code == 400
            and r.json()["detail"]["code"] == "STORAGE_ENDPOINT_NOT_PUBLIC",
            r.text[:160],
        )

        # --- cookie refresh, cross-origin, rotation, logout ---------------------
        r = c.post("/auth/refresh")
        step("refresh via cookie", r.status_code == 200, r.text[:120])
        access2 = r.json()["tokens"]["access_token"]
        step("access token rotated", access2 != access)
        rotated_cookie = c.cookies.get("estampa_refresh")
        step("refresh cookie rotated", rotated_cookie and rotated_cookie != cookie)
        r = c.post(
            "/auth/refresh", headers={"Origin": "https://albaranes-gratis.example"}
        )
        step("cross-origin refresh refused", r.status_code == 403, r.text[:120])
        r = c.get("/auth/me", headers=auth)
        step(
            "old access token still valid until logout",
            r.status_code == 200,
            str(r.status_code),
        )
        r = c.post("/auth/logout", headers={"Authorization": f"Bearer {access2}"})
        step("logout", r.status_code == 200, r.text[:120])
        r = c.get("/auth/me", headers={"Authorization": f"Bearer {access2}"})
        step(
            "logged-out token rejected (blacklist in REAL redis)",
            r.status_code == 401,
            str(r.status_code),
        )
        r = c.post("/auth/refresh")
        step("refresh after logout rejected", r.status_code == 401, str(r.status_code))

    print("\nALL STEPS PASSED:", len(results))


if __name__ == "__main__":
    main()
