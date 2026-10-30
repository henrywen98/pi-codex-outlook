import asyncio
import unittest
import json
from types import SimpleNamespace
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "extensions"))
from bridge import Codex, RpcError, PREFIXES


class FakeCodex(Codex):
    def __init__(self):
        super().__init__()
        self.thread_id = "test-thread"
        self.tools = {"email_get_profile": ("microsoft_outlook_email.get_profile", {})}
        self.calls = []
        self.response = {"content": [{"type": "text", "text": "Action completed."}],
                         "structuredContent": {"name": "Test"}, "isError": False}

    async def request(self, method, params):
        self.calls.append((method, params))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class BridgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_exact_routing_and_structured_text(self):
        backend = FakeCodex()
        result = await backend.call("email_get_profile", {})
        self.assertEqual(backend.calls, [("mcpServer/tool/call", {
            "threadId": "test-thread", "server": "codex_apps",
            "tool": "microsoft_outlook_email.get_profile", "arguments": {}})])
        self.assertEqual(result["structuredContent"], {"name": "Test"})
        self.assertIn('"Test"', result["content"][-1]["text"])
        self.assertEqual(len(backend.response["content"]), 1)

    async def test_non_outlook_blocked(self):
        backend = FakeCodex()
        with self.assertRaises(RpcError):
            await backend.call("slack_send_message", {})
        self.assertEqual(backend.calls, [])

    async def test_no_retry_after_failure(self):
        backend = FakeCodex()
        backend.response = RpcError("unknown outcome")
        with self.assertRaises(RpcError):
            await backend.call("email_get_profile", {})
        self.assertEqual(len(backend.calls), 1)

    async def test_error_result_preserved(self):
        backend = FakeCodex()
        backend.response = {"content": [{"type": "text", "text": "denied"}], "isError": True}
        self.assertTrue((await backend.call("email_get_profile", {}))["isError"])

    async def test_metadata_forwarded(self):
        backend = FakeCodex()
        await backend.call("email_get_profile", {}, {"progressToken": 123})
        self.assertEqual(backend.calls[0][1]["_meta"], {"progressToken": 123})

    async def test_parallel_calls_route_independently(self):
        backend = FakeCodex()
        await asyncio.gather(*(backend.call("email_get_profile", {"index": i}) for i in range(10)))
        self.assertEqual(len(backend.calls), 10)
        self.assertEqual({p["arguments"]["index"] for _, p in backend.calls}, set(range(10)))

    async def test_cancel_first_start_waiter_does_not_cancel_shared_start(self):
        class StartingCodex(Codex):
            def __init__(self):
                super().__init__()
                self.entered = asyncio.Event()
                self.release = asyncio.Event()
                self.starts = 0

            async def initialize(self):
                self.starts += 1
                self.entered.set()
                await self.release.wait()
                self.thread_id = "ready"

        backend = StartingCodex()
        first = asyncio.create_task(backend.start())
        await backend.entered.wait()
        second = asyncio.create_task(backend.start())
        first.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await first
        backend.release.set()
        await second
        self.assertEqual(backend.thread_id, "ready")
        self.assertEqual(backend.starts, 1)
        await backend.close()

    async def test_bidirectional_id_collision_and_out_of_order_responses(self):
        backend = Codex()
        stdout = asyncio.StreamReader()
        backend.process = SimpleNamespace(stdout=stdout)
        sent = []

        async def send(message):
            sent.append(message)

        backend.send = send
        reader = asyncio.create_task(backend.read_responses())
        first = asyncio.create_task(backend.request("one", {}))
        second = asyncio.create_task(backend.request("two", {}))
        await asyncio.sleep(0)
        for message in [
            {"id": 1, "method": "approval", "params": {}},
            {"id": 2, "result": {"value": "second"}},
            {"id": 1, "result": {"value": "first"}},
        ]:
            stdout.feed_data((json.dumps(message) + "\n").encode())
        self.assertEqual(await first, {"value": "first"})
        self.assertEqual(await second, {"value": "second"})
        self.assertEqual(sent[-1]["error"]["code"], -32601)
        stdout.feed_eof()
        await reader
        with self.assertRaisesRegex(RpcError, "reconnect"):
            await backend.request("after-eof", {})
        self.assertEqual(len(sent), 3)
        with self.assertRaisesRegex(RpcError, "reconnect"):
            await backend.start()

    async def test_close_cancels_pending_startup(self):
        class StartingCodex(Codex):
            async def initialize(self):
                await asyncio.Event().wait()

        backend = StartingCodex()
        waiter = asyncio.create_task(backend.start())
        await asyncio.sleep(0)
        await backend.close()
        with self.assertRaises(asyncio.CancelledError):
            await waiter
        self.assertTrue(backend.startup.done())

    def test_only_two_outlook_prefixes(self):
        self.assertEqual(set(PREFIXES), {"microsoft_outlook_email.", "microsoft_outlook_calendar."})


if __name__ == "__main__":
    unittest.main()
