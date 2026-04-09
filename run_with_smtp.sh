#!/bin/zsh
set -a

if [ -f ".env.smtp" ]; then
  while IFS='=' read -r key value || [ -n "$key" ]; do
    if [ -z "$key" ]; then
      continue
    fi

    case "$key" in
      \#*)
        continue
        ;;
    esac

    export "$key=$value"
  done < ".env.smtp"
fi

set +a
python3 server.py
