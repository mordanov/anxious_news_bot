#!/usr/bin/env bash
set -euo pipefail

OLD_BRANCH="${1:?Usage: $0 <old-branch-name> <new-branch-name>}"
NEW_BRANCH="${2:?Usage: $0 <old-branch-name> <new-branch-name>}"

# Rename local branch
git branch -m "$OLD_BRANCH" "$NEW_BRANCH"

# Push new branch and set upstream
git push origin "$NEW_BRANCH" --set-upstream

# Delete old branch on GitHub
git push origin --delete "$OLD_BRANCH"

echo "Branch renamed: $OLD_BRANCH -> $NEW_BRANCH"