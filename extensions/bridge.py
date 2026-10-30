"""Stdlib-only MCP stdio adapter for the installed Codex Outlook Apps."""
import asyncio
import contextlib
import json
import os
import signal
import sys

PREFIXES = {
    "microsoft_outlook_email.": "email_",
    "microsoft_outlook_calendar.": "calendar_",
}


class RpcError(Exception):
    pass


class Codex:
    def __init__(self):
        self.process = None
        self.pending = {}
        self.serial = 0
        self.reader = None
        self.thread_id = None
        self.tools = {}
        self.lock = asyncio.Lock()
        self.startup = None
        self.closed_error = None

    async def read_responses(self):
        try:
            while line := await self.process.stdout.readline():
                message = json.loads(line)
                if "method" in message:
                    if "id" in message:
                        # Request IDs are independent in each direction.
                        await self.send({"id": message["id"], "error": {
                            "code": -32601, "message": "Interactive requests are not supported by this adapter"}})
                    continue
                future = self.pending.get(message.get("id"))
                if future is not None and not future.done():
                    future.set_result(message)
        except Exception:
            # Do not log protocol contents or credentials.
            pass
        finally:
            self.closed_error = "Codex connection closed; reconnect the MCP server. Do not retry writes without checking their outcome."
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(RpcError(self.closed_error))

    async def send(self, message):
        self.process.stdin.write((json.dumps(message) + "\n").encode())
        await self.process.stdin.drain()

    async def request(self, method, params):
        if self.closed_error:
            raise RpcError(self.closed_error)
        self.serial += 1
        request_id = self.serial
        future = asyncio.get_running_loop().create_future()
        self.pending[request_id] = future
        try:
            await self.send({"id": request_id, "method": method, "params": params})
            try:
                response = await asyncio.wait_for(future, timeout=100)
            except TimeoutError:
                raise RpcError("Codex request timed out. The outcome may be unknown; do not automatically retry writes.") from None
            if "error" in response:
                raise RpcError(str(response["error"].get("message", "Codex request failed")))
            return response["result"]
        finally:
            self.pending.pop(request_id, None)

    async def start(self):
        if self.closed_error:
            raise RpcError(self.closed_error)
        if self.thread_id:
            return
        if self.startup is None:
            self.startup = asyncio.create_task(self.bootstrap())
            # Retrieve exceptions even when all request waiters were cancelled.
            self.startup.add_done_callback(lambda task: None if task.cancelled() else task.exception())
        await asyncio.shield(self.startup)

    async def bootstrap(self):
        try:
            await self.initialize()
        except BaseException:
            await self.close()
            raise

    async def initialize(self):
        async with self.lock:
            if self.thread_id:
                return
            if self.process:
                raise RpcError("Codex startup failed; reconnect the MCP server")
            self.process = await asyncio.create_subprocess_exec(
                os.environ.get("PI_OUTLOOK_CODEX_BIN", "codex"), "app-server", "--stdio",
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL, limit=16 * 1024 * 1024,
            )
            self.reader = asyncio.create_task(self.read_responses())
            await self.request("initialize", {
                "clientInfo": {"name": "pi-codex-outlook", "version": "0.1.0"},
                "capabilities": {"experimentalApi": True},
            })
            await self.send({"method": "initialized"})
            result = await self.request("thread/start", {"ephemeral": True, "cwd": os.path.expanduser("~")})
            thread_id = result["thread"]["id"]
            cursor = None
            discovered = {}
            while True:
                params = {"threadId": thread_id, "limit": 100}
                if cursor:
                    params["cursor"] = cursor
                page = await self.request("mcpServerStatus/list", params)
                for server in page.get("data", []):
                    if server.get("name") != "codex_apps":
                        continue
                    for tool in server.get("tools", {}).values():
                        original = tool["name"]
                        for prefix, alias in PREFIXES.items():
                            if original.startswith(prefix):
                                name = alias + original[len(prefix):]
                                if name in discovered:
                                    raise RpcError("Duplicate Outlook tool name")
                                public = {key: tool[key] for key in (
                                    "description", "inputSchema", "outputSchema", "annotations", "title"
                                ) if key in tool and tool[key] is not None}
                                public["name"] = name
                                discovered[name] = (original, public)
                cursor = page.get("nextCursor")
                if not cursor:
                    break
            if not discovered:
                raise RpcError("No Outlook Apps tools found. Check the Outlook plugins and login in Codex.")
            self.tools = discovered
            self.thread_id = thread_id

    async def call(self, name, arguments, meta=None):
        await self.start()
        if name not in self.tools:
            raise RpcError("Unknown or non-Outlook tool")
        params = {"threadId": self.thread_id, "server": "codex_apps",
                  "tool": self.tools[name][0], "arguments": arguments}
        if meta is not None:
            params["_meta"] = meta
        # Exactly one call. Never replay writes after timeout, cancellation, or failure.
        result = await self.request("mcpServer/tool/call", params)
        # Codex often returns only 'Action completed.' as text. Preserve structured
        # data, and expose it to MCP clients that only render text content.
        if "structuredContent" in result:
            result = dict(result)
            result["content"] = list(result.get("content", [])) + [{
                "type": "text", "text": json.dumps(result["structuredContent"], ensure_ascii=False)}]
        return result

    async def close(self):
        self.closed_error = "Codex connection closed; reconnect the MCP server. Do not retry writes without checking their outcome."
        if self.startup and self.startup is not asyncio.current_task() and not self.startup.done():
            self.startup.cancel()
            await asyncio.gather(self.startup, return_exceptions=True)
        if self.process:
            if self.process.returncode is None:
                self.process.terminate()
                try:
                    await asyncio.wait_for(self.process.wait(), 3)
                except TimeoutError:
                    self.process.kill()
                    await self.process.wait()
            if self.reader:
                await asyncio.gather(self.reader, return_exceptions=True)


async def serve():
    codex = Codex()
    tasks = set()
    active = {}
    output_lock = asyncio.Lock()

    async def emit(message):
        async with output_lock:
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", **message}, ensure_ascii=False) + "\n")
            sys.stdout.flush()

    async def handle(message):
        request_id = message.get("id")
        method = message.get("method")
        params = message.get("params") or {}
        if request_id is None:
            if method == "notifications/cancelled":
                task = active.get(params.get("requestId"))
                if task:
                    task.cancel()
            return
        try:
            if method == "initialize":
                version = params.get("protocolVersion", "2024-11-05")
                result = {"protocolVersion": version, "capabilities": {"tools": {}},
                          "serverInfo": {"name": "codex-outlook", "version": "0.1.0"},
                          "instructions": "Outlook tools reuse Codex Apps authentication. No Codex model is invoked. Never retry a write with an unknown outcome."}
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                await codex.start()
                result = {"tools": [entry[1] for entry in codex.tools.values()]}
            elif method == "tools/call":
                result = await codex.call(params.get("name"), params.get("arguments", {}), params.get("_meta"))
            else:
                await emit({"id": request_id, "error": {"code": -32601, "message": "Method not supported"}})
                return
            await emit({"id": request_id, "result": result})
        except asyncio.CancelledError:
            # Cancelling the wait does not prove the remote action was cancelled.
            await emit({"id": request_id, "error": {"code": -32800, "message": "Wait cancelled; a remote action may still complete. Do not automatically retry writes."}})
        except Exception as error:
            if method == "tools/call":
                await emit({"id": request_id, "result": {"isError": True,
                    "content": [{"type": "text", "text": str(error)}]}})
            else:
                await emit({"id": request_id, "error": {"code": -32603, "message": str(error)}})

    reader = asyncio.StreamReader(limit=16 * 1024 * 1024)
    protocol = asyncio.StreamReaderProtocol(reader)
    transport, _ = await asyncio.get_running_loop().connect_read_pipe(lambda: protocol, sys.stdin.buffer)
    try:
        while line := await reader.readline():
            try:
                message = json.loads(line)
                if not isinstance(message, dict):
                    raise ValueError("Expected an object")
            except (ValueError, json.JSONDecodeError):
                await emit({"id": None, "error": {"code": -32700, "message": "Invalid JSON-RPC message"}})
                continue
            task = asyncio.create_task(handle(message))
            tasks.add(task)
            if "id" in message:
                active[message["id"]] = task
            def done(t, request_id=message.get("id")):
                tasks.discard(t)
                if active.get(request_id) is t:
                    active.pop(request_id, None)
            task.add_done_callback(done)
    finally:
        transport.close()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await codex.close()


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    main = loop.create_task(serve())
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, main.cancel)
    with contextlib.suppress(asyncio.CancelledError, KeyboardInterrupt):
        loop.run_until_complete(main)
    loop.close()
