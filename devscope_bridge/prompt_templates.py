"""
prompt_templates.py — Prompt-template builders for /review, /security-review, /pr-comments.

These commands run through the normal run_prompt path (not a card) so the model
streams a real answer into the session where git is available.
"""

_REVIEW_BASE = (
    "Review the current uncommitted git diff for correctness bugs, logic errors, "
    "and risky changes. Run `git diff` and `git diff --staged` to get the diff. "
    "Be concise; cite file:line. If there is no diff, say so clearly."
)

_SECURITY_BASE = (
    "Perform a security review of the current git diff. Run `git diff` and "
    "`git diff --staged` to get the diff. "
    "Check for: injection (SQL/command/XSS), broken authz/authn, secrets or "
    "credentials in code, unsafe deserialization, SSRF, path traversal, open "
    "redirects, and missing input validation. "
    "Cite file:line and severity (high/medium/low) for each finding. "
    "If there is no diff, say so clearly."
)

_PR_COMMENTS_BASE = (
    "Fetch and summarise unresolved review comments on the pull request. "
    "Run `gh pr view {pr_ref} --comments` to get them (requires gh CLI). "
    "Group by file, mark each as actionable or FYI, and give a short action "
    "item for each one that needs a code change. If no PR or no comments, say so."
)


def build_review_prompt(args: str) -> str:
    """Build the /review prompt, appending optional focus from args."""
    if args:
        return f"{_REVIEW_BASE}\n\nExtra focus: {args}"
    return _REVIEW_BASE


def build_security_review_prompt(args: str) -> str:
    """Build the /security-review prompt."""
    if args:
        return f"{_SECURITY_BASE}\n\nExtra focus: {args}"
    return _SECURITY_BASE


def build_pr_comments_prompt(args: str) -> str:
    """Build the /pr-comments prompt.

    args may be a PR number like '123', a URL, or empty (use current branch PR).
    """
    pr_ref = args.strip() if args.strip() else ""
    if pr_ref:
        ref_clause = pr_ref
    else:
        ref_clause = (
            "$(gh pr view --json number --jq .number 2>/dev/null || echo '')"
            " -- or the current branch's PR if no number can be inferred"
        )
    return _PR_COMMENTS_BASE.format(pr_ref=ref_clause)
