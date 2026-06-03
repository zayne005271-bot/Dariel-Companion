#!/bin/bash
FLAG="/c/Users/31654/Desktop/dariel/poll_wake.flag"
sleep 180
if [ -f "$FLAG" ]; then
    echo "QQ_PENDING"
    /d/Python/python.exe -c "
import json
f=json.load(open('$FLAG','r',encoding='utf-8'))
print(f'nick: {f[\"nickname\"]}')
print(f'msg: {f[\"message\"]}')"
    echo "ACTION: REPLY_NEEDED"
else
    echo "QQ_CLEAR"
fi
