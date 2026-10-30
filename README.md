# pi-codex-outlook

**Your Outlook email and calendar, inside [Pi](https://pi.dev/).**

Already use Outlook in Codex? Bring that connection into Pi without setting up a separate Microsoft login in Pi.

- **Keep working in Pi.** Ask about your Outlook email and calendars from your agent session.
- **Reuse your existing connection.** Codex manages authentication; this package does not copy tokens into Pi.
- **Call tools directly.** No Codex model turn is needed to run the Outlook tools.

> Requires Codex CLI with working Outlook Email and Calendar Apps connections. Installing Codex alone is not enough.
>
> Non-official, experimental integration. Linux tested; macOS success reported by a user. Windows unverified.

## Quick start

### 1. Check Outlook in Codex

Make sure Codex can already read your Outlook profile and calendars. If needed, [connect the Apps first](#connect-outlook-in-codex-first).

### 2. Install in Pi

```bash
pi install git:github.com/henrywen98/pi-codex-outlook@v0.1.0
```

Review the source before installation: Pi packages execute local code with your user's permissions.

### 3. Reload and try a read-only task

Run `/reload` in Pi, or start a new session. Then ask:

```text
List my Outlook calendars.
```

Next, try an email lookup:

```text
Find the latest email about the quarterly report.
```

Use `/mcp` to check that `codex-outlook` is connected. No `mcp.json` entry is needed.

**Stuck?** See [Troubleshooting](#troubleshooting) or [open an issue](https://github.com/henrywen98/pi-codex-outlook/issues). Include versions and a redacted error, not mailbox content or tokens.

## Is this for you?

This package is for Pi users who already have working Outlook Apps connections in Codex. It is not a standalone Microsoft login client.

| Requirement | Details |
| --- | --- |
| Pi | Built-in MCP support and `registerMcpServer`. Tested with Pi 1.4.0. |
| Codex CLI | Active login and connected Outlook Email and Calendar Apps. Tested with app-server 0.166.0. |
| Python | Python 3.11 or newer, available as `python3` on PATH. |
| Platform | Linux tested directly. A user reported successful use on a MacBook. Windows unverified. |
| Node.js | 22.19.0 or newer for Pi's Node-based installation. |

The adapter uses only the Python standard library. It does not install a Microsoft MCP server or grant Microsoft permissions.

**Write tools are included.** Some tools send messages or meeting notifications immediately. See [Writes and permissions](#writes-and-permissions) before using them.

## Connect Outlook in Codex first

1. Open Codex with the account you want to use.
2. Install or enable the Outlook Email and Outlook Calendar Apps/plugins available to that account.
3. Complete their Microsoft authorization flow.
4. Verify that Codex can read your Outlook profile and calendars.
5. Start or reload Pi.

Codex's regular `codex mcp list` output is not sufficient to check its Apps connections. During development, Outlook appeared through the Apps/plugin path instead.

The adapter inherits your Codex configuration and environment. Codex can connect its other configured servers, but this adapter exposes only Outlook Apps tools.

## Tools in Pi

Tools use these prefixes:

```text
mcp__codex_outlook__email_*
mcp__codex_outlook__calendar_*
```

Tools use `codemode` exposure by default. Pi can also discover them through `tool_search`.

For a read-only check in codemode:

```javascript
const result = await tools.mcp__codex_outlook__calendar_list_calendars({});
if (result.isError) throw new Error("Outlook read failed");
text(result.structuredContent);
```

Use calendar IDs returned by `calendar_list_calendars`. Do not copy IDs from another account.

### Writes and permissions

This package exposes both read and write tools. It is not a read-only adapter.

The adapter preserves the tool annotations supplied by Codex. Those annotations describe behavior; they are not an approval gate. Your Pi setup and instructions control user approval.

Some tools send email or meeting notifications immediately. Ask the agent to create a draft when you want to review a message first.

After a timeout, cancellation, or disconnect, a remote write may still complete. Check the result before retrying. The adapter never automatically replays a tool call.

## How it works

```text
Pi extension
  └─ registers codex-outlook as a local stdio MCP server
      └─ Python adapter
          └─ codex app-server --stdio
              └─ existing Outlook Email / Calendar Apps connections
```

The adapter:

1. Initializes Codex app-server with `experimentalApi` enabled.
2. Creates an ephemeral thread without starting a model turn.
3. Discovers tools with `mcpServerStatus/list`.
4. Selects only `microsoft_outlook_email.*` and `microsoft_outlook_calendar.*` tools.
5. Calls them with `mcpServer/tool/call`.

It preserves argument schemas, output schemas, annotations, structured content, and error results. It also adds structured output as text for clients that would otherwise show only `Action completed.`

Authentication stays with Codex. The adapter does not copy tokens into Pi configuration or write a token cache. Pi and Codex can retain their usual tool and session records.

An ephemeral thread does not make remote writes temporary. Outlook calls still use remote services and remain subject to account policies and limits.

## Why reuse Codex?

After exploring direct Microsoft 365 connection options, reusing an existing Codex Apps connection was the route verified in practice.

The adapter read account information and calendar metadata. It also sent a test email that reached a separate personal mailbox.

This does not establish that other connection options cannot work. The benefit is reusing a working connection instead of configuring another one in Pi.

## Configuration

The extension registers the adapter when Pi loads it. Codex documents the MCP RPC methods, but this Outlook Apps reuse path has no verified long-term compatibility guarantee.

By default, the adapter starts `codex` from PATH. To choose another executable, set this variable before starting Pi:

```bash
export PI_OUTLOOK_CODEX_BIN=/absolute/path/to/codex
```

The extension launches `python3` from PATH. Use an environment where that command resolves to Python 3.11 or newer.

Each adapter process uses one Codex app-server subprocess and one ephemeral thread. Reloading or closing Pi releases the adapter and its subprocess.

## Development and distribution

For local development:

```bash
git clone https://github.com/henrywen98/pi-codex-outlook.git
pi install ./pi-codex-outlook
```

Git installation works today; an npm publication is not required. A pinned Git tag does not move when the repository changes.

If you installed an earlier standalone copy, remove that copy from Pi's extensions directory. Do not load both copies.

Run local unit tests without Microsoft credentials:

```bash
npm test
```

Run an optional integration check against your existing Codex login:

```bash
npm run test:smoke
```

The integration check reads profile and calendar metadata. It never sends email or changes a calendar. It prints status only, without personal result data.

Check the package contents before release:

```bash
npm pack --dry-run
```

CI runs unit tests and the package check. CI does not use your Codex login or contact Microsoft.

### Verified scope

- Unit tests cover routing, structured output, error preservation, shared startup cancellation, response ordering, ID collisions, and closed connections.
- A real Pi runtime discovered the adapter tools.
- Profile reads and calendar listing passed through the adapter.
- One email send and a search for that email succeeded. The recipient confirmed delivery.
- A user reported successful use on a MacBook: with Codex already available, the package worked after installation without extra adapter configuration.

The macOS result is user-reported. Exact macOS, Pi, and Codex versions and individual tool coverage were not recorded. A working Outlook Apps connection in Codex is still required.

Tool counts depend on the account and Codex version. Discovery does not prove that every tool works. Calendar writes, attachments, long-running sessions, and login-expiry recovery have not been validated.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| `codex-outlook` is missing from `/mcp` | Check `pi list`, then run `/reload`. Ensure built-in MCP support is enabled. |
| The shell command `pi mcp list` does not show the adapter | Use `/mcp` inside Pi. Shell MCP commands do not load extensions. |
| `No Outlook Apps tools found` | Check the Outlook Apps/plugins and their connections in Codex. |
| A command is missing | Check that `codex` and `python3` are available in Pi's PATH. |
| Login or authorization fails | Restore the connection in Codex, then reconnect `codex-outlook` in Pi. |
| Codex connection closes | Reconnect the MCP server. Check any write with an unknown outcome before retrying. |
| An interactive request is rejected | Complete the required interaction in Codex. The adapter does not handle interactive server requests. |
| A Codex update breaks the adapter | Report the Pi and Codex versions with a redacted error. Do not include tokens or mailbox data. |

To uninstall a tagged Git installation:

```bash
pi remove git:github.com/henrywen98/pi-codex-outlook@v0.1.0
```

Then run `/reload` or start a new Pi session.

## References

- [Pi packages](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/packages.md)
- [Pi extensions](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/extensions.md)
- [Pi MCP support](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/mcp.md)
- [Codex app-server](https://developers.openai.com/codex/app-server/)

## License

MIT. See [LICENSE](LICENSE).
