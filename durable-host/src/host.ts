import { readFileSync } from "node:fs";
import { createInterface } from "node:readline";
import { join } from "node:path";
import type { ModelRuntime } from "@earendil-works/pi-coding-agent";
import { BACKGROUND_CONTEXT as ctx } from "@earendil-works/chord/context";
import type { Models } from "@earendil-works/pi-ai";
import { createModels } from "@earendil-works/pi-ai/models";
import { builtinModels } from "@earendil-works/pi-ai/providers/all";
import {
  fauxAssistantMessage,
  fauxProvider,
  fauxText,
  fauxToolCall,
} from "@earendil-works/pi-ai/providers/faux";
import {
  Harness,
  MemoryStorage,
  createRegistry,
} from "@earendil-works/pi-durable";
import type {
  AgentChange,
  ConversationId,
  ConversationWatch,
  HarnessSettings,
  JsonObject,
  Storage,
  SubmissionId,
} from "@earendil-works/pi-durable";
import { NodeExecutionEnv } from "@earendil-works/pi-durable/env/node";
import { openNodeSqliteStorage } from "@earendil-works/pi-durable/storage/sqlite/node";
import { CodingTools } from "@earendil-works/pi-durable/tools";
import { nextWatchUpdate } from "./watch-window.ts";

type ObjectRecord = Record<string, unknown>;
type Request = ObjectRecord & { id: string; type: string };
let state: "not_open" | "opening" | "open" | "closing" = "not_open";
let harness: Harness | undefined;
let modelRuntime: ModelRuntime | undefined;
let maxRecordBytes = 16777216;
type WatchState = { handle?: ConversationWatch; lastSentId?: number };
const watches = new Map<string, WatchState>();
const version: string = JSON.parse(
  readFileSync(
    new URL(import.meta.resolve("@earendil-works/pi-durable/package.json")),
    "utf8",
  ),
).version;

// EPIPE is expected when the parent disappears. Other stream errors remain fatal.
for (const stream of [process.stdout, process.stderr]) {
  stream.on("error", (error: NodeJS.ErrnoException) => {
    if (error.code !== "EPIPE") process.exit(1);
  });
}

function exit(code: number): void {
  state = "closing";
  process.stdout.end(() => process.exit(code));
}

function failure(request: Request, code: string, error: string): ObjectRecord {
  return {
    type: "response",
    id: request.id,
    command: request.type,
    success: false,
    error,
    code,
  };
}

function write(record: ObjectRecord): void {
  if (state === "closing") return;
  let line = JSON.stringify(record);
  if (Buffer.byteLength(line, "utf8") > maxRecordBytes) {
    if (record.type === "durable_watch") {
      line = JSON.stringify({ ...record, entries: [], live: null, gap: true });
    } else if (record.type === "response") {
      line = JSON.stringify({
        type: "response",
        id: record.id,
        command: record.command,
        success: false,
        error: "Response exceeds maxRecordBytes",
        code: "too_large",
      });
    } else {
      return; // Oversized diagnostics carry no required data.
    }
    if (Buffer.byteLength(line, "utf8") > maxRecordBytes) return exit(1);
  }
  process.stdout.write(line + "\n");
}

function reject(code: string, message: string): never {
  throw Object.assign(new Error(message), { name: code });
}
function object(value: unknown): ObjectRecord {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    reject("bad_params", "Expected an object");
  }
  return value as ObjectRecord;
}
function string(value: unknown): string {
  if (typeof value !== "string") reject("bad_params", "Expected a string");
  return value;
}
function integer(value: unknown): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value))
    reject("bad_params", "Expected an integer");
  return value;
}
function positive(value: unknown): number {
  if (typeof value !== "number" || !Number.isFinite(value) || value <= 0)
    reject("bad_params", "Expected a positive number");
  return value;
}
function optionalStrings(value: ObjectRecord, keys: string[]): void {
  for (const key of keys) if (value[key] !== undefined) string(value[key]);
}

function settings(value: unknown): HarnessSettings | undefined {
  if (value === undefined) return undefined;
  const result = object(value);
  for (const key of ["retry", "progress"]) {
    if (result[key] === undefined) continue;
    const policy = object(result[key]);
    for (const [field, item] of Object.entries(policy)) {
      if (key === "retry" && field === "enabled") {
        if (typeof item !== "boolean")
          reject("bad_params", "retry.enabled must be boolean");
      } else if (
        [
          "maxRetries",
          "baseDelayMs",
          "maxAgentDelayMs",
          "partialIntervalMs",
          "outputIntervalMs",
          "persistWithinMs",
        ].includes(field)
      ) {
        if (typeof item !== "number" || !Number.isFinite(item) || item < 0)
          reject("bad_params", "Invalid policy number");
        if (field === "maxRetries") integer(item);
      }
    }
  }
  // Pass only the supported settings groups, without changing their contents.
  return {
    retry: result.retry as HarnessSettings["retry"],
    progress: result.progress as HarnessSettings["progress"],
  };
}

async function open(request: Request): Promise<ObjectRecord> {
  if (state !== "not_open")
    reject("already_open", "Harness is already opening or open");
  const storageSpec = object(request.storage);
  if (storageSpec.kind !== "memory" && storageSpec.kind !== "sqlite")
    reject("bad_params", "Unknown storage kind");
  if (storageSpec.kind === "sqlite") string(storageSpec.path);
  if (
    request.codingTools !== undefined &&
    typeof request.codingTools !== "boolean"
  )
    reject("bad_params", "codingTools must be boolean");
  if (request.models !== undefined && request.models !== "pi" && request.models !== "builtin")
    reject("bad_params", "models must be pi or builtin");
  optionalStrings(request, ["piAgentDir"]);
  const policies = settings(request.settings);
  const limit =
    request.maxRecordBytes === undefined
      ? 16777216
      : positive(integer(request.maxRecordBytes));
  if (request.fauxTokensPerSecond !== undefined)
    positive(request.fauxTokensPerSecond);
  const fauxModels = createModels();
  let models: Models = fauxModels;
  if (request.faux !== undefined) {
    if (!Array.isArray(request.faux))
      reject("bad_params", "faux must be an array");
    const responses = request.faux.map((step, index) => {
      if (typeof step === "string")
        return fauxAssistantMessage([fauxText(step)]);
      const call = object(step);
      return fauxAssistantMessage(
        [
          fauxToolCall(string(call.tool), object(call.args) as JsonObject, {
            id: `faux-${index}`,
          }),
        ],
        { stopReason: "toolUse" },
      );
    });
    const faux = fauxProvider({
      tokensPerSecond: request.fauxTokensPerSecond as number | undefined,
    });
    faux.setResponses(responses);
    fauxModels.setProvider(faux.provider);
  }
  const registry = createRegistry();
  if (request.codingTools !== false) registry.install(CodingTools);
  state = "opening";
  let storage: Storage | undefined;
  let opened: Harness | undefined;
  let runtime: ModelRuntime | undefined;
  try {
    if (request.faux === undefined) {
      if (request.models === "builtin") models = builtinModels();
      else {
        const { ModelRuntime } = await import("@earendil-works/pi-coding-agent");
        if (isClosing()) {
          exit(0);
          return {};
        }
        const directory = request.piAgentDir as string | undefined;
        runtime = await ModelRuntime.create(directory === undefined ? undefined : {
          authPath: join(directory, "auth.json"),
          modelsPath: join(directory, "models.json"),
        });
        models = runtime;
      }
    }
    if (isClosing()) {
      await runtime?.settleCredentialWrites();
      exit(0);
      return {};
    }
    storage =
      storageSpec.kind === "memory"
        ? new MemoryStorage()
        : await openNodeSqliteStorage(storageSpec.path as string);
    opened = await Harness.open(
      storage,
      {
        models,
        registry,
        settings: policies,
        env: (target) =>
          new NodeExecutionEnv({ cwd: target.cwd ?? process.cwd() }),
        onReport: (report) => {
          const error =
            report.error instanceof Error
              ? report.error
              : new Error(String(report.error));
          write({
            type: "durable_report",
            report: {
              ...report,
              error: { name: error.name, message: error.message },
            },
          });
        },
      },
      ctx,
    );
    // EOF can arrive while storage/Harness.open is in flight. Never publish that
    // harness or resume work after shutdown; its local owner closes it instead.
    if (isClosing()) {
      await opened.close(ctx);
      await runtime?.settleCredentialWrites();
      exit(0);
      return {};
    }
    opened.resume();
    maxRecordBytes = limit;
    harness = opened;
    modelRuntime = runtime;
    state = "open";
    return {};
  } catch (error) {
    try {
      try {
        if (opened) await opened.close(ctx);
        else if (storage) await storage.close(ctx);
      } finally {
        await runtime?.settleCredentialWrites();
      }
    } catch {
      // Preserve the original open error even if best-effort cleanup fails.
    } finally {
      if (isClosing()) exit(0);
      else state = "not_open";
    }
    throw error;
  }
}
function isClosing(): boolean {
  return state === "closing";
}

function watchUpdate(watchId: string, watch: WatchState, snapshot: boolean): void {
  if (!watch.handle || watches.get(watchId) !== watch) return;
  const view = watch.handle.value;
  const update = nextWatchUpdate(watch.lastSentId, view.entries);
  if (view.entries.length) watch.lastSentId = view.entries.at(-1)!.id;
  // Advance even when write replaces the payload with a gap event.
  write({
    type: "durable_watch", watchId, ...update,
    live: view.docs["pi.live"] ?? null, snapshot,
  });
}

async function command(request: Request): Promise<ObjectRecord | (() => void)> {
  if (request.type === "hello")
    return { protocol: 0, piDurable: version, pid: process.pid };
  if (request.type === "open") return open(request);
  if (state !== "open" || !harness) reject("not_open", "Harness is not open");
  switch (request.type) {
    case "watch": {
      const id = integer(request.conversationId) as ConversationId;
      const watchId = string(request.watchId);
      if (watches.has(watchId)) reject("bad_params", "Duplicate watchId");
      const watch: WatchState = {};
      watches.set(watchId, watch); // Reserve before any await; concurrent IDs cannot collide.
      try {
        const conversation = await harness.conversation(id, ctx);
        if (!conversation) reject("not_found", "Conversation not found");
        const handle = await conversation.watch(ctx);
        watch.handle = handle;
        if (isClosing() || watches.get(watchId) !== watch) {
          await handle.stop();
          return {};
        }
        // The dispatcher writes the ACK before calling this continuation.
        return () => {
          watchUpdate(watchId, watch, true);
          handle.start(async (call) => {
            if (call.kind === "value") watchUpdate(watchId, watch, false);
          });
          void handle.closed.then((end) => {
            if (watches.get(watchId) !== watch) return;
            watches.delete(watchId);
            write({ type: "durable_watch_end", watchId, kind: end.kind });
          }).catch(() => exit(1));
        };
      } catch (error) {
        if (watches.get(watchId) === watch) watches.delete(watchId);
        throw error;
      }
    }
    case "unwatch": {
      const watchId = string(request.watchId);
      const watch = watches.get(watchId);
      watches.delete(watchId);
      await watch?.handle?.stop();
      return {};
    }
    case "root": {
      let agent: AgentChange | undefined;
      if (request.agent !== undefined) {
        const options = object(request.agent);
        optionalStrings(options, ["cwd", "thinkingLevel"]);
        let model: AgentChange["model"];
        if (options.model !== undefined) {
          const value = object(options.model);
          model = {
            provider: string(value.provider),
            modelId: string(value.modelId),
          };
        }
        agent = {
          model,
          cwd: options.cwd as string | undefined,
          thinkingLevel: options.thinkingLevel as AgentChange["thinkingLevel"],
        };
      }
      return { conversationId: (await harness.root(ctx, { agent })).id };
    }
    case "wait": {
      const submission = await harness.submission(
        integer(request.submissionId) as SubmissionId,
        ctx,
      );
      if (!submission) reject("not_found", "Submission not found");
      return { submission: await submission.wait(ctx) };
    }
    case "submit":
    case "entries":
    case "abort": {
      const id = integer(request.conversationId) as ConversationId;
      // Validate all parameters before querying upstream.
      if (request.type === "submit") {
        string(request.content);
        if (string(request.requestId).length === 0)
          reject("bad_params", "requestId must not be empty");
        if (
          request.whenBusy !== undefined &&
          !["followUp", "steer", "reject"].includes(request.whenBusy as string)
        )
          reject("bad_params", "Invalid whenBusy");
      }
      const limit =
        request.type === "entries"
          ? request.limit === undefined
            ? 50
            : positive(integer(request.limit))
          : 50;
      const conversation = await harness.conversation(id, ctx);
      if (!conversation) reject("not_found", "Conversation not found");
      if (request.type === "submit") {
        const submission = await conversation.submit(
          {
            type: "input",
            content: request.content as string,
            requestId: request.requestId as string,
            whenBusy: request.whenBusy as
              | "followUp"
              | "steer"
              | "reject"
              | undefined,
          },
          ctx,
        );
        return { submissionId: submission.id };
      }
      if (request.type === "entries")
        return {
          entries: [
            ...(await conversation.entries({}, limit, undefined, ctx)).items,
          ].reverse(),
        };
      await conversation.abort(ctx);
      return {};
    }
    default:
      return reject("unknown_command", "Unknown command");
  }
}

const input = createInterface({ input: process.stdin, crlfDelay: Infinity });
input.on("line", (line) => {
  if (isClosing()) return;
  let value: unknown;
  try {
    value = JSON.parse(line);
  } catch {
    write({
      type: "durable_protocol_error",
      code: "parse_error",
      message: "Invalid JSON",
    });
    return;
  }
  if (
    value === null ||
    typeof value !== "object" ||
    Array.isArray(value) ||
    typeof (value as ObjectRecord).id !== "string" ||
    typeof (value as ObjectRecord).type !== "string"
  ) {
    write({
      type: "durable_protocol_error",
      code: "bad_request",
      message: "Request needs string id and type",
    });
    return;
  }
  const request = value as Request;
  // Deliberately do not await: a long wait must not block control requests.
  void command(request)
    .then(
      (data) => {
        write({
          type: "response",
          id: request.id,
          command: request.type,
          success: true,
          data: typeof data === "function" ? {} : data,
        });
        if (!isClosing() && typeof data === "function") data();
      },
      (error: unknown) => {
        const failureError =
          error instanceof Error ? error : new Error(String(error));
        write(
          failure(
            request,
            failureError.name === "Error"
              ? "upstream_error"
              : failureError.name,
            failureError.message,
          ),
        );
      },
    )
    .catch(() => exit(1)); // Serialization/write failures must terminate deliberately.
});
input.on("close", () => {
  const wasOpening = state === "opening";
  state = "closing"; // Suppress all outstanding command completions and reports.
  if (wasOpening) return; // The open continuation owns cleanup in this case.
  void (async () => {
    try {
      const active = [...watches.values()];
      watches.clear();
      try {
        await Promise.all(active.map((watch) => watch.handle?.stop()));
        await harness?.close(ctx);
      } finally {
        await modelRuntime?.settleCredentialWrites();
      }
      exit(0);
    } catch {
      exit(1);
    }
  })();
});
