// Post or update ONE skillproof comment per skill path on a pull request.
// Called from action.yml via actions/github-script: comment({ github, context, core }).
const fs = require("fs");

function marker(skillPath) {
  return `<!-- skillproof-report: ${skillPath || "."} -->`;
}

async function comment({ github, context, core, env = process.env }) {
  const report = fs.readFileSync(env.REPORT, "utf8");
  const tag = marker(env.SKILL_PATH);
  const body = `${tag}\n${report}`;
  const { owner, repo } = context.repo;
  const issue_number = context.issue.number;

  try {
    const comments = await github.paginate(github.rest.issues.listComments, {
      owner,
      repo,
      issue_number,
      per_page: 100,
    });
    const existing = comments.find((c) => c.body && c.body.startsWith(tag));
    if (existing) {
      await github.rest.issues.updateComment({ owner, repo, comment_id: existing.id, body });
      core.info(`Updated skillproof comment ${existing.id}`);
    } else {
      await github.rest.issues.createComment({ owner, repo, issue_number, body });
      core.info("Posted skillproof comment");
    }
  } catch (error) {
    // Pull requests from forks get a read-only token; don't fail the run over a comment.
    core.warning(`Could not comment on the pull request: ${error.message}`);
  }
}

module.exports = comment;
module.exports.marker = marker;
