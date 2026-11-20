/** Record the effective system prompt so tests can assert what reaches the model. */
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { writeFileSync } from "node:fs";

export default function (pi: ExtensionAPI) {
  pi.on("before_agent_start", (event) => {
    const target = process.env.PI_FIXTURE_PROMPT_CAPTURE;
    if (target) writeFileSync(target, event.systemPrompt);
  });
}
