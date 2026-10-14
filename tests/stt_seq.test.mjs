// Pure STT ordering/alias helpers, extracted from runner/templates/index.html (no build step).
// Run: node --test tests/stt_seq.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const html = readFileSync(new URL('../runner/templates/index.html', import.meta.url), 'utf8');
const src = html.split('// stt-pure:start')[1].split('// stt-pure:end')[0];
const { _sttNextSeq, _sttClassify, _sttMergePending, _sttCanonKey } = new Function(
  `${src}; return { _sttNextSeq, _sttClassify, _sttMergePending, _sttCanonKey };`)();

const LOCAL = 'agenticos.draft.reply.linear.local-1';
const REAL = 'agenticos.draft.reply.linear.uuid-1';
const aliases = { 'local-1': 'uuid-1' };

test('seq is monotonic even if the clock goes backwards', () => {
  const a = _sttNextSeq(0, 1000);
  const b = _sttNextSeq(a, 999);
  assert.ok(b > a);
});

test('canonical key maps local-id owner and storage keys to the Linear id', () => {
  assert.equal(_sttCanonKey(LOCAL, aliases), REAL);
  assert.equal(_sttCanonKey('agenticos.stt.pending.' + LOCAL, aliases), 'agenticos.stt.pending.' + REAL);
  assert.equal(_sttCanonKey('agenticos.draft.new_issue.description', aliases), 'agenticos.draft.new_issue.description');
});

test('sessions and cancels under both aliases merge correctly', () => {
  // local alias: recording at seq 10; real alias: cancel at 20, then a new recording at 30
  const cancel = Math.max(0 /* local cancel */, 20 /* real cancel */);
  const latest = Math.max(10, 30);
  assert.equal(_sttClassify(10, cancel, latest), 'cancelled');  // cancel under the other alias wins
  assert.equal(_sttClassify(30, cancel, latest), 'current');
  assert.equal(_sttClassify(25, cancel, latest), 'superseded');
});

test('a new recording after reload ranks above persisted pending rows', () => {
  const persisted = [{ sid: 'a', seq: _sttNextSeq(0, 1000) }];
  const next = _sttNextSeq(persisted[0].seq, 1000);  // lastSeq persisted, same clock
  assert.equal(_sttClassify(next, 0, next), 'current');
  assert.deepEqual(_sttMergePending(persisted, [{ sid: 'b', seq: next }]).map(r => r.sid), ['b', 'a']);
});

test('pending merge keeps both results in reverse completion order, dedupes by sid', () => {
  const older = { sid: 's1', seq: 1 };
  const newer = { sid: 's2', seq: 2 };
  assert.deepEqual(_sttMergePending([newer], [older]).map(r => r.sid), ['s2', 's1']);
  assert.equal(_sttMergePending([older], [older]).length, 1);
});
