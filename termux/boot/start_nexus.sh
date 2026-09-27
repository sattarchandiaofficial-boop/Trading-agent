#!/data/data/com.termux/files/usr/bin/bash
#
# Auto-start script for Termux:Boot.
# Place this file at ~/.termux/boot/start_nexus.sh on the phone (see SETUP.md).
# Termux:Boot runs everything in ~/.termux/boot/ automatically when the phone
# starts — no need to ever open Termux manually.

termux-wake-lock
cd "$HOME" || exit 1
nohup bash nexus_hands_free.sh > "$HOME/nexus.log" 2>&1 &
