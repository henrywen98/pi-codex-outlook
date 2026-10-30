"""Opt-in integration test. Reads profile and calendar metadata; never writes."""
import asyncio
import json
import sys
from pathlib import Path


async def main():
    bridge = Path(__file__).resolve().parents[1] / "extensions" / "bridge.py"
    process = await asyncio.create_subprocess_exec(
        sys.executable, str(bridge), stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE, limit=16 * 1024 * 1024,
    )
    counter = 0

    async def call(method, params):
        nonlocal counter
        counter += 1
        process.stdin.write((json.dumps({"jsonrpc": "2.0", "id": counter,
                                        "method": method, "params": params}) + "\n").encode())
        await process.stdin.drain()
        raw = await asyncio.wait_for(process.stdout.readline(), 120)
        if not raw:
            raise RuntimeError("Adapter closed before returning a response")
        response = json.loads(raw)
        if response.get("id") != counter or "error" in response:
            raise RuntimeError("Invalid MCP response or protocol error")
        result = response["result"]
        if result.get("isError"):
            raise RuntimeError("Outlook read failed. Check Codex login and reconnect.")
        return result

    try:
        await call("initialize", {"protocolVersion": "2025-11-25", "capabilities": {},
                                  "clientInfo": {"name": "pi-codex-outlook-smoke", "version": "0.1.0"}})
        tools = (await call("tools/list", {}))["tools"]
        names = {tool["name"] for tool in tools}
        assert names and all(name.startswith(("email_", "calendar_")) for name in names)
        print(f"Discovered {len(tools)} Outlook tools")
        for name in ("email_get_profile", "calendar_list_calendars"):
            assert name in names, f"Missing {name}"
            result = await call("tools/call", {"name": name, "arguments": {}})
            assert result.get("structuredContent") is not None
            print(f"{name}: OK (personal data omitted)")
    finally:
        process.stdin.close()
        try:
            await asyncio.wait_for(process.wait(), 10)
        except TimeoutError:
            process.terminate()
            await process.wait()
    assert process.returncode == 0, f"Adapter exited with {process.returncode}"
    print("Clean shutdown: OK")


if __name__ == "__main__":
    asyncio.run(main())
