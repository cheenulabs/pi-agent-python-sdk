/** Offline scenarios use Pi's public faux-provider and extension APIs. */
import {
  createFauxCore,
  fauxAssistantMessage,
  fauxThinking,
  fauxText,
  fauxToolCall,
  type AssistantMessage,
} from "@earendil-works/pi-ai";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { existsSync, readFileSync, unlinkSync } from "node:fs";
import { dirname, join } from "node:path";

interface Step {
  text?: string;
  thinking?: string;
  tool?: string;
  arguments?: Record<string, unknown>;
  stopReason?: AssistantMessage["stopReason"];
  error?: string;
  wait?: string;
}

export default function (pi: ExtensionAPI) {
  const faux = createFauxCore({
    provider: "python-fixture",
    api: "python-fixture-api",
    tokenSize: { min: 3, max: 3 },
    models: [
      { id: "fixture", name: "Offline Fixture", reasoning: true },
      { id: "fixture-other", name: "Other Offline Fixture", reasoning: true },
    ],
  });
  let responseFile: string | undefined;
  pi.on("session_start", (_event, ctx) => {
    const sessionFile = ctx.sessionManager.getSessionFile();
    responseFile = sessionFile ? join(dirname(sessionFile), "fixture-responses.json") : undefined;
  });
  pi.registerProvider("python-fixture", {
    baseUrl: "http://localhost:0",
    apiKey: "synthetic-test-value",
    api: faux.api,
    models: faux.models,
    streamSimple: (model, context, options) => {
      if (responseFile && existsSync(responseFile)) {
        const steps = JSON.parse(readFileSync(responseFile, "utf8")) as Step[];
        unlinkSync(responseFile);
        setResponses(steps);
      }
      return faux.streamSimple(model, context, options);
    },
  });

  // Explicit gates avoid relying on sleeps to race cancellation or queueing.
  const gates = new Map<string, () => void>();
  const wait = (name: string, signal?: AbortSignal) =>
    new Promise<void>((resolve) => {
      if (signal?.aborted) return resolve();
      const done = () => {
        gates.delete(name);
        signal?.removeEventListener("abort", done);
        resolve();
      };
      gates.set(name, done);
      signal?.addEventListener("abort", done, { once: true });
    });

  function setResponses(steps: Step[]) {
      if (!Array.isArray(steps)) throw new Error("Expected an array of fixture steps");
      faux.setResponses(steps.map((step) => async (_context, options) => {
        if (step.wait) await wait(step.wait, options?.signal);
        if (options?.signal?.aborted) {
          return fauxAssistantMessage("", { stopReason: "aborted" });
        }
        const content = [];
        if (step.thinking !== undefined) content.push(fauxThinking(step.thinking));
        if (step.text !== undefined) content.push(fauxText(step.text));
        if (step.tool) {
          content.push(fauxToolCall(step.tool, step.arguments ?? {}, { id: "fixture-tool-call" }));
        }
        return fauxAssistantMessage(content, {
          stopReason: step.stopReason ?? (step.tool ? "toolUse" : "stop"),
          ...(step.error === undefined ? {} : { errorMessage: step.error }),
        });
      }));
  }
  pi.registerCommand("fixture-script", {
    description: "Replace the queued offline assistant responses with a JSON array",
    handler: async (args) => { setResponses(JSON.parse(args)); },
  });
  pi.registerCommand("fixture-release", {
    description: "Release a named provider, tool, or compaction gate",
    handler: async (name) => { gates.get(name)?.(); },
  });
  pi.registerCommand("fixture-gates", {
    description: "Notify the currently waiting gate names",
    handler: async (_args, ctx) => { ctx.ui.notify(JSON.stringify([...gates.keys()])); },
  });
  pi.registerTool({
    name: "fixture_echo",
    label: "Fixture echo",
    description: "Return synthetic text without touching files or the network",
    parameters: Type.Object({ text: Type.String(), wait: Type.Optional(Type.String()) }),
    async execute(_id, args, signal, onUpdate) {
      onUpdate?.({ content: [{ type: "text", text: "fixture tool update" }], details: {} });
      if (args.wait) await wait(args.wait, signal);
      return { content: [{ type: "text", text: args.text }], details: { fixture: true } };
    },
  });
  let delayed = false;
  pi.on("input", (event) => {
    if (event.text === "fixture delayed") {
      delayed = true;
      return { action: "handled" };
    }
    if (event.text === "fixture handled") return { action: "handled" };
  });
  pi.registerCommand("fixture-release-delayed", {
    description: "Start work previously consumed by the delayed input fixture",
    handler: async () => {
      if (delayed) {
        delayed = false;
        await pi.sendUserMessage("synthetic delayed input");
      }
    },
  });
  pi.registerCommand("fixture-error", {
    description: "Emit a synthetic extension error",
    handler: async () => { throw new Error("synthetic fixture error"); },
  });
  pi.registerCommand("fixture-ui", {
    description: "Exercise one dialog (select, confirm, input, editor) or all display methods",
    handler: async (method, ctx) => {
      let result: string | boolean | undefined;
      switch (method) {
        case "select": result = await ctx.ui.select("Fixture select", ["one", "two"]); break;
        case "confirm": result = await ctx.ui.confirm("Fixture confirm", "Continue?"); break;
        case "input": result = await ctx.ui.input("Fixture input", "placeholder"); break;
        case "editor": result = await ctx.ui.editor("Fixture editor", "prefill"); break;
        case "display":
          ctx.ui.setStatus("fixture", "ready");
          ctx.ui.setWidget("fixture", ["fixture widget"]);
          ctx.ui.setTitle("Fixture title");
          ctx.ui.setEditorText("fixture editor text");
          ctx.ui.notify("fixture notification");
          return;
        default: throw new Error(`Unknown fixture UI method: ${method}`);
      }
      ctx.ui.notify(JSON.stringify({ result: result ?? null }));
    },
  });

  let dialogDuringTurn = false;
  pi.on("before_agent_start", async (event, ctx) => {
    dialogDuringTurn = event.prompt === "fixture timeout during";
    if (event.prompt === "fixture timeout before") {
      await ctx.ui.confirm("Fixture deadline", "Continue?", { timeout: 25 });
    }
    if (event.prompt === "fixture timeout input") {
      await ctx.ui.input("Fixture deadline", "Type here", { timeout: 25 });
    }
  });
  pi.on("turn_start", async (_event, ctx) => {
    if (dialogDuringTurn) {
      await ctx.ui.confirm("Fixture deadline", "Continue?", { timeout: 25 });
    }
  });

  let veto = false;
  let compactGate: string | undefined;
  let nativeCompaction = false;
  pi.registerCommand("fixture-new-session-and-run", {
    description: "Change sessions through the command context, then start an agent run",
    handler: async (_args, ctx) => {
      await ctx.newSession({
        withSession: async (replacement) => {
          // Replacement invalidates the old pi/context and registers fresh fixtures.
          await replacement.sendUserMessage(
            '/fixture-script [{"text":"answer from new session"}]',
            { expandPromptTemplates: true },
          );
          await replacement.sendUserMessage("synthetic extension question");
        },
      });
    },
  });
  pi.registerCommand("fixture-native-compaction", {
    description: "Enable or disable native summarization using queued faux responses",
    handler: async (args) => { nativeCompaction = args === "on"; },
  });
  pi.registerCommand("fixture-veto", {
    description: "Toggle session new/switch/fork veto with on or off",
    handler: async (args) => { veto = args === "on"; },
  });
  pi.on("session_before_switch", () => veto ? { cancel: true } : undefined);
  pi.on("session_before_fork", () => veto ? { cancel: true } : undefined);
  pi.registerCommand("fixture-compact-gate", {
    description: "Wait at the next compaction until a named gate is released",
    handler: async (name) => { compactGate = name || undefined; },
  });
  pi.on("session_before_compact", async (event) => {
    if (compactGate) {
      const name = compactGate;
      compactGate = undefined;
      await wait(name, event.signal);
    }
    if (event.signal.aborted) return { cancel: true };
    if (nativeCompaction) return;
    return {
      compaction: {
        summary: "Synthetic offline compaction summary",
        firstKeptEntryId: event.preparation.firstKeptEntryId,
        tokensBefore: event.preparation.tokensBefore,
        details: { fixture: true },
      },
    };
  });
  pi.registerCommand("fixture-entry", {
    description: "Append a synthetic custom entry",
    handler: async () => { pi.appendEntry("fixture", { value: "synthetic" }); },
  });
}
