// Exercise the installed, pinned TS implementation without patching its methods.
import {RpcClient} from './node_modules/@earendil-works/pi-coding-agent/dist/modes/rpc/rpc-client.js';
import fs from 'node:fs';
import {fileURLToPath} from 'node:url';
const fixture = JSON.parse(fs.readFileSync(new URL('../fixtures/rpc_parity.json', import.meta.url)));
const cliPath = fileURLToPath(new URL('./parity-child.cjs', import.meta.url));
const results = [];
for (const nullable of [false, true]) {
  const pi = new RpcClient({cliPath, cwd: process.argv[2], args: nullable ? ['--null-cycles'] : []});
  try {
    await pi.start();
    const seen = [];
    const remove = pi.onEvent(event => seen.push(event));
    for (const test of fixture.cases.filter(test => !!test.nullable === nullable)) {
      seen.length = 0;
      const result = await pi[test.ts](...test.ts_args);
      results.push({method: test.py, commands: seen.map(event => event.request), result: result ?? null});
    }
    remove();
    if (!nullable) {
      const first = [], second = [];
      const offFirst = pi.onEvent(event => first.push(event));
      const offSecond = pi.onEvent(event => second.push(event));
      const events = await pi.promptAndWait('emit-corpus', undefined, 5000);
      offFirst(); offSecond();
      for (const records of [events, first, second]) {
        if (JSON.stringify(records) !== JSON.stringify(fixture.events)) throw new Error('TS event corpus differs');
      }
    }
  } finally { await pi.stop(); }
}
console.log(JSON.stringify(results));
