// Every page script parses the way the browser loads it: as a module. One syntax error stops a whole
// page (a broken string in caregiver.js once kept the caregiver page from opening), and a plain
// `node --check` of the file didn't catch it.
import { test } from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { readdirSync, readFileSync } from "node:fs";

const dir = new URL("../../static/", import.meta.url);

for (const name of readdirSync(dir).filter((f) => f.endsWith(".js"))) {
  test(`${name} parses as a module`, () => {
    const run = spawnSync(process.execPath, ["--input-type=module", "--check"],
      { input: readFileSync(new URL(name, dir)), encoding: "utf8" });
    assert.equal(run.status, 0, run.stderr);
  });
}
