#!/bin/sh
set -eu

export DISPLAY="${DISPLAY:-:99}"
display_number="${DISPLAY#:}"
screen="${OPC_BROWSER_SCREEN:-1440x900x24}"

rm -f "/tmp/.X${display_number}-lock"
Xvfb "$DISPLAY" -screen 0 "$screen" -nolisten tcp >/tmp/xvfb.log 2>&1 &

attempt=0
while [ ! -S "/tmp/.X11-unix/X${display_number}" ]; do
  attempt=$((attempt + 1))
  if [ "$attempt" -ge 50 ]; then
    printf '可视浏览器图形环境启动失败。\n' >&2
    exit 1
  fi
  sleep 0.1
done

fluxbox >/tmp/fluxbox.log 2>&1 &
x11vnc -display "$DISPLAY" -forever -shared -localhost -rfbport 5900 -nopw -quiet >/tmp/x11vnc.log 2>&1 &
websockify --web=/usr/share/novnc 6080 localhost:5900 >/tmp/novnc.log 2>&1 &

exec "$@"
