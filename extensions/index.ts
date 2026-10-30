import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { fileURLToPath } from "node:url";

export default function (pi: ExtensionAPI) {
  pi.registerMcpServer("codex-outlook", {
    command: "python3",
    args: [fileURLToPath(new URL("./bridge.py", import.meta.url))],
    exposure: "codemode",
    timeout: 120,
    description: "Outlook email and calendar through the existing Codex Apps login. Calls tools directly, without a Codex model turn.",
  });
}
