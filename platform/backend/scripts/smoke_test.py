"""End-to-end smoke test against a running instance (default
http://localhost:8000). Exercises the path the plan's Verification
section calls for: identity tree -> permission narrowing -> funding
trickle-down -> client scope enforcement -> the WhatsApp message pipeline
-> ledger/audit evidence. Exits non-zero on any failure.

    python -m scripts.smoke_test
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
import uuid

import httpx

BASE_URL = os.getenv("SMOKE_TEST_BASE_URL", "http://localhost:8000")
PASSWORD = "SmokeTestPassword123!"
EXISTING_ADMIN_EMAIL = os.getenv("SMOKE_TEST_ADMIN_EMAIL")
EXISTING_ADMIN_PASSWORD = os.getenv("SMOKE_TEST_ADMIN_PASSWORD")


class Check:
    def __init__(self):
        self.failures: list[str] = []

    def ok(self, label: str, condition: bool, detail: str = ""):
        mark = "PASS" if condition else "FAIL"
        print(f"[{mark}] {label}" + (f" — {detail}" if detail and not condition else ""))
        if not condition:
            self.failures.append(label)


async def main() -> None:
    check = Check()
    run_id = uuid.uuid4().hex[:8]
    admin_email = f"smoke-admin-{run_id}@example.org"

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
        # --- health ---
        resp = await client.get("/api/health")
        check.ok("health endpoint responds", resp.status_code == 200)

        # --- staff bootstrap-or-login ---
        # Bootstrap only succeeds once per database. On a fresh database
        # this creates the smoke test's own superadmin; on an already-
        # bootstrapped one (the normal case in dev), fall back to logging
        # in with SMOKE_TEST_ADMIN_EMAIL / SMOKE_TEST_ADMIN_PASSWORD.
        resp = await client.post(
            "/api/auth/staff/bootstrap",
            json={"email": admin_email, "password": PASSWORD, "full_name": "Smoke Test Admin"},
        )
        if resp.status_code == 403:
            if not (EXISTING_ADMIN_EMAIL and EXISTING_ADMIN_PASSWORD):
                print("[SKIP] Bootstrap already used on this database. Set SMOKE_TEST_ADMIN_EMAIL and")
                print("       SMOKE_TEST_ADMIN_PASSWORD to an existing superadmin to run against it.")
                sys.exit(1)
            resp = await client.post(
                "/api/auth/staff/login", json={"email": EXISTING_ADMIN_EMAIL, "password": EXISTING_ADMIN_PASSWORD}
            )
            check.ok("staff login (existing superadmin)", resp.status_code == 200, resp.text)
        else:
            check.ok("staff bootstrap", resp.status_code == 201, resp.text)
        token = resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # --- identity tree ---
        root = await client.post("/api/profiles/identities", json={"name": f"Root-{run_id}", "id_type": "group"}, headers=headers)
        check.ok("create root identity", root.status_code == 201, root.text)
        root_id = root.json()["id"]

        child = await client.post(
            "/api/profiles/identities", json={"name": f"Child-{run_id}", "id_type": "group", "parent_id": root_id}, headers=headers
        )
        check.ok("create child identity", child.status_code == 201)
        child_id = child.json()["id"]

        member = await client.post(
            "/api/profiles/identities", json={"name": f"Member-{run_id}", "id_type": "member", "parent_id": child_id}, headers=headers
        )
        check.ok("create member (leaf) identity", member.status_code == 201)
        member_id = member.json()["id"]

        illegal = await client.post(
            "/api/profiles/identities", json={"name": "Illegal", "id_type": "member", "parent_id": member_id}, headers=headers
        )
        check.ok("member cannot have children", illegal.status_code == 400)

        # --- permission narrowing ---
        await client.put(f"/api/profiles/identities/{root_id}/permission", json={"own_connected": True, "own_credit_cap": 100}, headers=headers)
        narrow = await client.put(f"/api/profiles/identities/{child_id}/permission", json={"own_credit_cap": 500}, headers=headers)
        check.ok("narrowing self-clamps (child cap stays <= parent)", narrow.json()["effective_credit_cap"] == "100.000000", narrow.text)

        # --- funding trickle-down ---
        await client.post(f"/api/profiles/identities/{root_id}/fund", json={"amount": 100}, headers=headers)
        transfer = await client.post(f"/api/profiles/identities/{root_id}/transfer", json={"to_identity_id": child_id, "amount": 40}, headers=headers)
        check.ok("trickle-down transfer succeeds", transfer.status_code == 204, transfer.text)
        child_balance = (await client.get(f"/api/profiles/identities/{child_id}/account", headers=headers)).json()["balance"]
        check.ok("child balance reflects transfer", child_balance == "40.000000", child_balance)

        upward = await client.post(f"/api/profiles/identities/{child_id}/transfer", json={"to_identity_id": root_id, "amount": 1}, headers=headers)
        check.ok("upward transfer rejected", upward.status_code == 400)

        # --- client scope enforcement ---
        client_email = f"smoke-client-{run_id}@example.org"
        created_client = await client.post(
            f"/api/profiles/identities/{child_id}/client-account",
            json={"email": client_email, "password": PASSWORD, "full_name": "Smoke Client"},
            headers=headers,
        )
        check.ok("create client account", created_client.status_code == 201, created_client.text)

        client_login = await client.post("/api/profiles/client/login", json={"email": client_email, "password": PASSWORD})
        check.ok("client login", client_login.status_code == 200)
        client_token = client_login.json()["access_token"]
        client_headers = {"Authorization": f"Bearer {client_token}"}

        own_scope = await client.get(f"/api/profiles/client/identities/{member_id}", headers=client_headers)
        check.ok("client reaches own descendant", own_scope.status_code == 200)

        ancestor_scope = await client.get(f"/api/profiles/client/identities/{root_id}", headers=client_headers)
        check.ok("client blocked from ancestor (critical security check)", ancestor_scope.status_code == 403)

        # --- WhatsApp message pipeline ---
        phone = f"+91{int(time.time()) % 10_000_000_000}"
        link = await client.post("/api/meeting-room/whatsapp-links", json={"phone_number": phone, "identity_id": member_id}, headers=headers)
        check.ok("link WhatsApp number", link.status_code == 201, link.text)

        await client.put(f"/api/profiles/identities/{child_id}/permission", json={"own_auto_respond": True}, headers=headers)
        await client.post(
            "/api/meeting-room/archive",
            json={"title": "Smoke test info", "content": {"text": "This is approved auto-reply content."}, "approved_for_auto_reply": True},
            headers=headers,
        )

        inbound = await client.post("/api/meeting-room/webhook", json={"from": phone, "text": "test message", "id": f"smoke-{run_id}"})
        results = inbound.json().get("results", [])
        check.ok("inbound message processed (not bounced)", bool(results) and results[0]["status"] == "processed", str(results))

        bounced = await client.post("/api/meeting-room/webhook", json={"from": "+910000000001", "text": "hi", "id": f"smoke-bounce-{run_id}"})
        bounced_results = bounced.json().get("results", [])
        check.ok("unlinked number bounces", bool(bounced_results) and bounced_results[0]["status"] == "bounced")

        member_balance = (await client.get(f"/api/profiles/identities/{member_id}/account", headers=headers)).json()["balance"]
        check.ok("member's own balance untouched by free base service", member_balance == "0.000000", member_balance)

    print()
    if check.failures:
        print(f"{len(check.failures)} check(s) FAILED: {', '.join(check.failures)}")
        sys.exit(1)
    print("All smoke test checks passed.")


if __name__ == "__main__":
    asyncio.run(main())
