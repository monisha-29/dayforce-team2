"""End-to-end vertical-slice check (Person 5).

Takes one exception through the whole pipeline against a RUNNING backend:

    list exceptions -> pick one -> generate proposal -> check validators
    -> approve -> confirm status, audit trail and the stored punches changed

Usage (backend must be running on port 8000):
    python scripts\\e2e_check.py
    python scripts\\e2e_check.py --type meal_break
    python scripts\\e2e_check.py --base-url http://localhost:8000 --db timecard.db

Exit code 0 = vertical slice works, 1 = something failed.
"""
import argparse
import sqlite3
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
GREEN, RED, YELLOW, END = "\033[92m", "\033[91m", "\033[93m", "\033[0m"


def ok(msg: str) -> None:
    print(f"{GREEN}PASS{END}  {msg}")


def info(msg: str) -> None:
    print(f"      {msg}")


def fail(msg: str) -> "None":
    print(f"{RED}FAIL{END}  {msg}")
    sys.exit(1)


def find_db(explicit: str | None) -> Path | None:
    candidates = [Path(explicit)] if explicit else [
        ROOT / "timecard.db", ROOT / "backend" / "timecard.db", Path("timecard.db")
    ]
    return next((p for p in candidates if p.is_file()), None)


def punches_for(db: Path | None, emp: str, date: str) -> list[tuple]:
    if db is None:
        return []
    con = sqlite3.connect(db)
    try:
        return con.execute(
            "SELECT punch_type, timestamp, source FROM punches "
            "WHERE employee_id = ? AND date(timestamp) = ? ORDER BY timestamp",
            (emp, date),
        ).fetchall()
    finally:
        con.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--type", default=None, help="e.g. missed_punch, overtime, meal_break, schedule_conflict")
    ap.add_argument("--db", default=None, help="path to timecard.db (optional, enables the punch check)")
    ap.add_argument("--tries", type=int, default=10, help="how many exceptions to try if proposals get blocked")
    args = ap.parse_args()

    api = args.base_url.rstrip("/") + "/api/v1"
    db = find_db(args.db)
    # LLM calls on CPU can be slow, so allow a long timeout
    client = httpx.Client(timeout=300)

    # 0. health
    try:
        r = client.get(args.base_url.rstrip("/") + "/health")
        r.raise_for_status()
    except Exception as e:  # noqa: BLE001
        fail(f"Backend not reachable at {args.base_url} ({e}). Start uvicorn first.")
    ok("Backend is up (/health)")

    # 1. list exceptions
    params = {"status": "pending_review"}
    if args.type:
        params["type"] = args.type
    r = client.get(f"{api}/exceptions", params=params)
    r.raise_for_status()
    queue = r.json()
    if not queue:
        fail("No pending exceptions in the queue. Run: python scripts\\load_dataset.py")
    ok(f"Queue returned {len(queue)} pending exception(s)")

    approved = None
    for exc in queue[: args.tries]:
        eid, emp, date = exc["id"], exc["employee"]["id"], exc["date"]
        print(f"\n--- Trying {eid}  {exc['type']}  {emp}  {date} ---")

        # 2. detail
        r = client.get(f"{api}/exceptions/{eid}")
        r.raise_for_status()
        ok("Exception detail loaded")
        info(f"original timecard: {exc['original']}")

        before = punches_for(db, emp, date)

        # 3. proposal (runs retrieval -> LLM -> validator -> retry/fallback)
        r = client.post(f"{api}/exceptions/{eid}/proposal")
        if r.status_code == 409:
            info(f"{YELLOW}skip{END}: {r.json().get('detail')}")
            continue
        if r.status_code != 200:
            fail(f"Proposal endpoint returned {r.status_code}: {r.text[:300]}")
        prop = r.json()
        ok(f"Proposal generated ({prop['id']})")
        info(f"clause: {prop['policyClauseId']}  | recommendation: {prop['recommendation']}")
        info(f"proposed timecard: {prop['proposed']}")

        # 4. validators
        validators = prop.get("validators", [])
        if len(validators) != 5:
            fail(f"Expected 5 validator checks, got {len(validators)}")
        for v in validators:
            mark = "ok " if v["passed"] else "BAD"
            info(f"[{mark}] {v['name']}" + (f" - {v['reason']}" if v.get("reason") else ""))
        ok("All 5 validator checks reported")

        if prop["blocked"]:
            info(f"{YELLOW}Proposal is BLOCKED by validation, so approving must be refused.{END}")
            r = client.post(f"{api}/proposals/{prop['id']}/decision", json={"decision": "approve"})
            if r.status_code != 422:
                fail(f"Blocked proposal should be refused with 422, got {r.status_code}")
            ok("Blocked proposal correctly refused (safety net works)")
            after = punches_for(db, emp, date)
            if before != after:
                fail("Punches changed even though the proposal was blocked!")
            ok("Timecard untouched for blocked proposal")
            continue

        # Safety: nothing must change before approval
        if punches_for(db, emp, date) != before:
            fail("Punches changed BEFORE approval, which breaks the 'human approves' rule")
        ok("Timecard unchanged before approval")

        # 5. approve
        r = client.post(f"{api}/proposals/{prop['id']}/decision", json={"decision": "approve", "reason": "e2e check"})
        if r.status_code != 200:
            fail(f"Approve returned {r.status_code}: {r.text[:300]}")
        dec = r.json()
        if dec["newStatus"] != "Approved":
            fail(f"Expected status Approved, got {dec['newStatus']}")
        ok(f"Approved (trace {dec['traceId']})")

        # 6. verify exception status
        r = client.get(f"{api}/exceptions/{eid}")
        r.raise_for_status()
        if r.json()["status"] != "Approved":
            fail(f"Exception status is {r.json()['status']}, expected Approved")
        ok("Exception status = Approved")

        # 7. verify audit trail
        r = client.get(f"{api}/exceptions/{eid}/audit")
        r.raise_for_status()
        actions = [e["action"] for e in r.json()]
        info("audit: " + " -> ".join(actions))
        if "Manager approved" not in actions or "Timecard updated" not in actions:
            fail("Audit trail is missing 'Manager approved' or 'Timecard updated'")
        ok("Audit trail has approval + timecard update")

        # 8. verify stored punches actually changed
        after = punches_for(db, emp, date)
        if db is None:
            info(f"{YELLOW}timecard.db not found, skipped the stored-punch check (use --db){END}")
        else:
            info(f"punches before: {before}")
            info(f"punches after:  {after}")
            times_before = [(p[0], p[1]) for p in before]
            times_after = [(p[0], p[1]) for p in after]
            if times_before != times_after:
                ok("Punch times changed after approval (timecard corrected)")
            elif any(p[2] == "manager_approved_proposal" for p in after):
                ok("Approval wrote to the timecard (source = manager_approved_proposal)")
                info(f"{YELLOW}Punch times are identical: this proposal kept the same times "
                     f"(typical for overtime or fallback-escalated cases). Try --type missed_punch "
                     f"to see times actually change.{END}")
            else:
                fail("Approval did not touch the stored punches")

        approved = eid
        break

    if approved is None:
        fail("No exception made it all the way through (all were blocked or skipped).")

    print(f"\n{GREEN}VERTICAL SLICE OK{END}: {approved} went detect -> propose -> validate -> approve -> timecard updated")


if __name__ == "__main__":
    main()
