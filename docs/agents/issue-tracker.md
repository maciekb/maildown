# Issue tracker: GitHub

Issues and specs live in GitHub Issues for maciekb/maildown.
Use the gh CLI from this repository.

## Operations

- Create: gh issue create --title "..." --body-file <file>
- Read with discussion: gh issue view <number> --comments
- Read labels: gh issue view <number> --json labels
- List: gh issue list --state open --json number,title,body,labels
- Comment: gh issue comment <number> --body-file <file>
- Add or remove labels: gh issue edit <number> --add-label "..."
  or --remove-label "..."
- Close: gh issue close <number>

Write multiline bodies to a file and pass it with --body-file.
Infer the repository from the git remote.

When a skill says "publish to the issue tracker", create an issue.
When it says "fetch the relevant ticket", read the issue and comments.

## Pull requests as a triage surface

PRs as a request surface: no.
