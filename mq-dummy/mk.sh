#!/usr/bin/env bash
# Ветки-пустышки сборщика без worktree (plumbing): $1 — имя ветки, $2 — файл-тест, $3 — путь в дереве. База — main.
set -euo pipefail
repo=/home/pakar/igor/remlab
cd "$repo"
idx=$(mktemp -p "${REMLAB_TMP:-$HOME/remlab-scratch/tmp}" mq-idx.XXXX)
export GIT_INDEX_FILE=$idx
git read-tree main
blob=$(git hash-object -w "$2")
git update-index --add --cacheinfo 100644 "$blob" "$3"
tree=$(git write-tree)
c=$(GIT_AUTHOR_NAME=mq GIT_AUTHOR_EMAIL=mq@remlab.local GIT_COMMITTER_NAME=mq GIT_COMMITTER_EMAIL=mq@remlab.local \
  git commit-tree "$tree" -p main -m "mq dummy: $1 ($3)")
git update-ref "refs/heads/$1" "$c"
unset GIT_INDEX_FILE
echo "$1 $c"
