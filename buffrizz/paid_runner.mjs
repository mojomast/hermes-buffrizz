#!/usr/bin/env node
// Official paid Codebuff SDK runner. Not used for Freebuff free mode.
// Reads the API key from a 0600 --key-file and deletes that file immediately.
import { readFileSync, unlinkSync } from "node:fs";

function opt(name) {
  const i = process.argv.indexOf(name);
  return i >= 0 ? process.argv[i + 1] : undefined;
}

const keyFile = opt("--key-file");
const cwd = opt("--cwd");
const promptFile = opt("--prompt-file");
const maxSteps = Number(opt("--max-steps") || 20);

function fail(code, message) {
  process.stderr.write(JSON.stringify({ ok: false, code, message }) + "\n");
  process.exit(2);
}

if (!keyFile || !cwd || !promptFile) {
  fail("invalid_request", "key-file, cwd and prompt-file are required");
}

let apiKey = "";
try {
  apiKey = readFileSync(keyFile, "utf8").trim();
} catch (err) {
  fail("key_unreadable", "could not read key file");
} finally {
  try {
    unlinkSync(keyFile);
  } catch {
    /* already gone */
  }
}
if (!apiKey) {
  fail("key_missing", "key file was empty");
}

let prompt = "";
try {
  prompt = readFileSync(promptFile, "utf8");
} catch (err) {
  fail("prompt_unreadable", "could not read prompt file");
}

let CodebuffClient;
try {
  ({ CodebuffClient } = await import("@codebuff/sdk"));
} catch (err) {
  fail("sdk_missing", "Cannot find package '@codebuff/sdk'");
}

const client = new CodebuffClient({ apiKey, cwd });
try {
  const result = await client.run({
    agent: "base",
    prompt,
    maxAgentSteps: maxSteps,
    handleEvent: (event) => {
      const type = event && event.type ? String(event.type) : "event";
      process.stdout.write(JSON.stringify({ event: type }) + "\n");
    },
  });
  const outputType = result && result.output ? typeof result.output : "unknown";
  process.stdout.write(JSON.stringify({ ok: true, done: true, output_type: outputType }) + "\n");
} catch (err) {
  const message = err && err.message ? String(err.message) : "sdk run failed";
  fail("sdk_error", message);
}
