#!/bin/bash

cd -- "$(dirname "$0")" || exit 1

for scoring_python in python3 /opt/homebrew/bin/python3 /usr/local/bin/python3 /Library/Frameworks/Python.framework/Versions/Current/bin/python3; do
    if command -v "$scoring_python" >/dev/null 2>&1 && "$scoring_python" -c 'import sys, tkinter, venv, ensurepip; sys.exit(sys.version_info < (3, 11))' >/dev/null 2>&1; then
        "$scoring_python" -B "$PWD/scripts/launch.py"
        scoring_status=$?
        if [ "$scoring_status" -ne 0 ]; then
            printf '\nStartup failed. Review the message above.\nPress Enter to close...'
            read -r scoring_reply
        fi
        exit "$scoring_status"
    fi
done

printf 'Install Python 3.11 or newer with Tcl/Tk and pip from python.org, then open this launcher again.\n'
printf 'Press Enter to close...'
read -r scoring_reply
exit 1
