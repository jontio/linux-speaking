#!/usr/bin/env bash
# Started from the application menu. Starts dictation if it isn't running, and asks it to
# show its level meter window, so that clicking the menu entry always does something visible.
mkdir -p "$HOME/.local/state/linux-speaking"
touch "$HOME/.local/state/linux-speaking/show"
systemctl --user start linux-speaking.service
