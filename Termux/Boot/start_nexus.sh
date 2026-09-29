#!/data/data/com.termux/files/usr/bin/bash
# Place at ~/.termux/boot/start_nexus.sh so Termux:Boot runs it automatically
# on phone restart — Termux never needs to be opened by hand.

termux-wake-lock
cd "$HOME/nexus/termux" || exit 1

nohup bash start_server.sh > "$HOME/nexus_server.log" 2>&1 &
sleep 8   # give uvicorn a moment to bind the port before the loop starts calling it
nohup bash nexus_hands_free.sh > "$HOME/nexus_hands_free.log" 2>&1 &
