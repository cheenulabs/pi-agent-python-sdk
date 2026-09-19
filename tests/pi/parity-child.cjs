// Synthetic RPC peer shared by the pinned TS client and both Python facades.
const fs = require('node:fs');
const readline = require('node:readline');
const fixture = require('../fixtures/rpc_parity.json');
if (process.argv.includes('--version')) {
  console.log(require('./package.json').devDependencies['@earendil-works/pi-coding-agent']);
  process.exit(0);
}
const emit = record => fs.writeSync(1, JSON.stringify(record) + '\n');
readline.createInterface({input: process.stdin}).on('line', line => {
  const request = JSON.parse(line);
  const {id, ...fields} = request;
  const response = {type: 'response', id, command: request.type, success: true};
  if (request.type === 'prompt' && request.message === 'emit-corpus') {
    // One unpaced write, with acknowledgement after all events and settlement.
    fs.writeSync(1, [...fixture.events, response].map(r => JSON.stringify(r) + '\n').join(''));
    return;
  }
  emit({type: 'fixture_request', request: fields});
  if (Object.hasOwn(fixture.responses, request.type)) response.data = fixture.responses[request.type];
  if (process.argv.includes('--null-cycles') && ['cycle_model', 'cycle_thinking_level'].includes(request.type)) response.data = null;
  emit(response);
});
