#!/bin/bash

current_branch=$(git branch --show-current)
echo $current_branch

if [ "$current_branch" == "main" ]; then
    echo "mainブランチです。"
    exit 1
fi

git checkout main
git merge --no-ff $current_branch -m "Merge branch '$current_branch'"

git push origin main

git branch -D $current_branch