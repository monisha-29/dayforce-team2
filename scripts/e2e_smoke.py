"""Smoke test of a running stack: queue -> proposal -> (optional) approval -> audit.

Start the API first (see README), then:

    python scripts/e2e_smoke.py                       # propose only, changes nothing
    python scripts/e2e_smoke.py --approve             # also approve and verify the audit trail
    python scripts/e2e_smoke.py --id EXC-XXXX --api http://localhost:8000

Exit code 0 means every check passed. Proposals take 1 to 3 minutes with a local model on CPU.
"""

import argparse
import sys

import httpx


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--id", default=None, help="exception id (default: first pending missing punch)")
    ap.add_argument("--approve", action="store_true", help="approve the proposal if it is not blocked")
    ap.add_argument("--timeout", type=float, default=600.0)
    args = ap.parse_args()
    base = args.api.rstrip("/")
    failures: list[str] = []

    def check(ok: bool, label: str) -> None:
        print(f"  [{'ok' if ok else 'FAIL'}] {label}")
        if not ok:
            failures.append(label)

    with httpx.Client(timeout=args.timeout) as http:
        print("1. health")
        check(http.get(f"{base}/health").json().get("status") == "ok", "API is healthy")

        print("2. exception queue")
        items = http.get(f"{base}/api/v1/exceptions").json()
        check(len(items) > 0, f"{len(items)} exceptions listed")
        if not items:
            return 1
        target = next((e for e in items if e["id"] == args.id), None) if args.id else next(
            (e for e in items if e["type"] == "Missing Punch" and e["status"] == "Pending Review"),
            next((e for e in items if e["status"] == "Pending Review"), items[0]),
        )
        assert target is not None, f"exception {args.id} not found"
        eid = target["id"]
        print(f"   using {eid} ({target['type']}, {target['status']})")

        print("3. generate proposal (this calls the model)")
        resp = http.post(f"{base}/api/v1/exceptions/{eid}/proposal")
        check(resp.status_code == 200, f"proposal endpoint returned {resp.status_code}")
        if resp.status_code != 200:
            print(resp.text)
            return 1
        prop = resp.json()
        print(f"   proposed={prop['proposed']} blocked={prop['blocked']} clause={prop['policyClauseId']}")
        check(bool(prop["policyClauseId"]), "proposal cites a policy clause")
        check(
            prop["blocked"] or all(v["passed"] for v in prop["validators"]),
            "an approvable proposal passes every validator",
        )
        detail = http.get(f"{base}/api/v1/exceptions/{eid}").json()
        check(detail["original"] == target["original"], "generating a proposal left the timecard untouched")

        print("4. audit trail")
        audit = [e["action"] for e in http.get(f"{base}/api/v1/exceptions/{eid}/audit").json()]
        for step in ("Policy retrieved", "Validation completed"):
            check(step in audit, f"audit has '{step}'")
        check(
            "LLM response received" in audit or "LLM call failed" in audit,
            "audit records the model call or its failure",
        )

        if args.approve:
            print("5. manager approval")
            if prop["blocked"]:
                resp = http.post(f"{base}/api/v1/proposals/{prop['id']}/decision", json={"decision": "approve"})
                check(resp.status_code == 422, "a blocked proposal cannot be approved")
            else:
                resp = http.post(f"{base}/api/v1/proposals/{prop['id']}/decision", json={"decision": "approve"})
                check(resp.status_code == 200, f"approval accepted ({resp.status_code})")
                audit = [e["action"] for e in http.get(f"{base}/api/v1/exceptions/{eid}/audit").json()]
                check("Manager approved" in audit and "Timecard updated" in audit, "audit has the approval and the timecard update")
                status = http.get(f"{base}/api/v1/exceptions/{eid}").json()["status"]
                check(status == "Approved", f"exception is now {status}")

    print("\nPASS" if not failures else f"\nFAILED: {len(failures)} check(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
