// Run with: node --test action/test
const test = require("node:test");
const assert = require("node:assert");
const fs = require("fs");
const os = require("os");
const path = require("path");
const comment = require("../comment.js");

function fakeGithub(existing = []) {
  const calls = { created: [], updated: [] };
  const github = {
    rest: {
      issues: {
        listComments: "listComments",
        createComment: async (args) => calls.created.push(args),
        updateComment: async (args) => calls.updated.push(args),
      },
    },
    paginate: async (method, args) => {
      assert.strictEqual(method, "listComments");
      assert.strictEqual(args.issue_number, 7);
      return existing;
    },
  };
  return { github, calls };
}

const context = { repo: { owner: "me", repo: "skills" }, issue: { number: 7 } };
const logs = [];
const core = { info: (m) => logs.push(m), warning: (m) => logs.push(`warn: ${m}`) };

function env(report = "## skillproof: `pdf`\n") {
  const file = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "st-")), "report.md");
  fs.writeFileSync(file, report);
  return { REPORT: file, SKILL_PATH: "skills/pdf" };
}

test("creates a comment with a marker when none exists", async () => {
  const { github, calls } = fakeGithub([{ id: 1, body: "unrelated" }]);
  await comment({ github, context, core, env: env() });
  assert.strictEqual(calls.created.length, 1);
  assert.ok(calls.created[0].body.startsWith("<!-- skillproof-report: skills/pdf -->\n## skillproof"));
  assert.strictEqual(calls.updated.length, 0);
});

test("updates the existing comment for the same skill", async () => {
  const { github, calls } = fakeGithub([
    { id: 1, body: "<!-- skillproof-report: skills/other -->\nold" },
    { id: 2, body: "<!-- skillproof-report: skills/pdf -->\nold" },
  ]);
  await comment({ github, context, core, env: env("new report") });
  assert.strictEqual(calls.created.length, 0);
  assert.deepStrictEqual(calls.updated[0].comment_id, 2);
  assert.ok(calls.updated[0].body.endsWith("new report"));
});

test("a read-only token only warns", async () => {
  const { github } = fakeGithub([]);
  github.rest.issues.createComment = async () => {
    throw new Error("Resource not accessible by integration");
  };
  await comment({ github, context, core, env: env() });
  assert.ok(logs.some((m) => m.startsWith("warn: Could not comment")));
});
