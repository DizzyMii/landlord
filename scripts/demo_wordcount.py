"""Drive a small Landlord orchestration to build a wordcount CLI.

Bypasses the MCP transport layer (since this session's MCP tools were unloaded
when we bounced the server) but exercises the exact same in-process code path:
LandlordServer -> Landlord.decompose -> approve -> launch -> tenants -> judge
-> artifacts. Streams events to stdout so you can follow along.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

from landlord.mcp_server import build_default_server


PROMPT = (
    "Build a tiny CLI tool called 'wordcount' that takes a file path and prints "
    "three numbers: the number of lines, words, and characters in that file. "
    "Create the files at the absolute paths "
    "'C:/Users/KadeHeglin/Downloads/Projects/wordcount/wordcount.py' "
    "and 'C:/Users/KadeHeglin/Downloads/Projects/wordcount/test_wordcount.py'. "
    "Implementation: argparse with one positional argument (file path); "
    "print three lines like 'lines: N', 'words: N', 'chars: N'. Test: one "
    "pytest test that creates a tempfile with known content and asserts the "
    "subprocess output matches expectations. "
    "IMPORTANT: When emitting checkpoint outputs, include the FULL CONTENTS "
    "of any files you wrote (not just the paths) so the validator can "
    "semantically verify them. Run 'python -m pytest "
    "C:/Users/KadeHeglin/Downloads/Projects/wordcount/test_wordcount.py -v' "
    "after writing the files; report stdout in the test_verified checkpoint."
)


def _print_event(event: dict) -> None:
    ts = time.strftime("%H:%M:%S", time.localtime(event["ts"]))
    t = event.get("type", "?")
    role = event.get("role", "")
    cp = event.get("checkpoint", "")
    reason = event.get("reason", "")
    extra = ""
    if cp:
        extra = f" {cp}"
    if reason:
        extra += f" — {reason[:120]}"
    print(f"  {ts}  {t:22s}  {role:14s}{extra}", flush=True)


async def main() -> int:
    server = build_default_server()
    print("=" * 70, flush=True)
    print("Decomposing prompt...", flush=True)
    started = await server.start_orchestration(prompt=PROMPT)
    job_id = started["job_id"]
    output_dir = started["output_dir"]
    print(f"job_id:    {job_id}", flush=True)
    print(f"output:    {output_dir}", flush=True)
    print(f"plan:      {[c['role'] for c in started['plan']]}", flush=True)
    print("-" * 70, flush=True)

    print("Approving plan and launching tenants...", flush=True)
    await server.approve_plan(job_id=job_id)
    print("-" * 70, flush=True)

    events_path = Path(output_dir) / "events.jsonl"
    seen = 0
    while True:
        if events_path.exists():
            lines = events_path.read_text(encoding="utf-8").splitlines()
            for line in lines[seen:]:
                try:
                    _print_event(json.loads(line))
                except json.JSONDecodeError:
                    pass
            seen = len(lines)
        status = await server.get_status(job_id=job_id)
        if status["status"] in ("complete", "partial", "cancelled"):
            break
        await asyncio.sleep(1)

    print("-" * 70, flush=True)
    print(f"Final status: {status['status']}", flush=True)
    arts = await server.get_artifacts(job_id=job_id)
    print(f"Artifacts: {json.dumps(arts['artifacts'], indent=2, default=str)}", flush=True)
    return 0 if status["status"] == "complete" else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
