#!/usr/bin/env python3
"""临时诊断脚本 v2：隔离 8040012「网络故障」的触发因素（cookie/dxrisk/UA）"""
import os
import json
import requests

BASE = "https://gw2c-hw-open.longfor.com/lmarketing-task-api-mvc-prod/openapi/task/v1/signature/clock"
MINE = "https://longzhu-api.longfor.com/lmember-member-open-api-prod/api/member/v1/mine-info"
token = os.getenv('LHTJ_TOKEN', '')
usertoken = os.getenv('LHTJ_USERTOKEN', '') or token
dxrisk = os.getenv('LHTJ_DXRISK_TOKEN', '')
cookie = os.getenv('LHTJ_COOKIE', '')
cap = os.getenv('LHTJ_CAPTCHA_TOKEN', '')
UA_MINI = ("Mozilla/5.0 (iPhone; CPU iPhone OS 27_0 like Mac OS X) AppleWebKit/605.1.15 "
           "(KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.75(0x18004b64) "
           "NetType/WIFI Language/zh_CN miniProgram/wx50282644351869da")
UA_ANDROID = ("Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/124.0.0.0 Mobile Safari/537.36")


def clock(name, ua=UA_MINI, use_cookie=True, use_dxrisk=True, cap_header=None):
    headers = {
        'User-Agent': ua,
        'Accept': 'application/json, text/plain, */*',
        'Content-Type': 'application/json;charset=UTF-8',
        'X-LF-DXRisk-Source': '5',
        'X-LF-Bu-Code': 'C20400',
        'X-GAIA-API-KEY': 'c06753f1-3e68-437d-b592-b94656ea5517',
        'X-LF-UserToken': usertoken,
        'X-LF-Channel': 'C2',
        'token': token,
        'Origin': 'https://longzhu.longfor.com',
        'Referer': 'https://longzhu.longfor.com/',
    }
    if use_dxrisk:
        headers['X-LF-DXRisk-Token'] = dxrisk
    headers['X-LF-DXRisk-Captcha-Token'] = cap_header if cap_header is not None else cap
    if use_cookie:
        headers['Cookie'] = cookie
    data = {"activity_no": os.getenv('LHTJ_ACTIVITY_NO', '') or '11111111111686241863606037740000'}
    try:
        r = requests.post(BASE, headers=headers, json=data, timeout=15)
        body = r.json() if r.headers.get('content-type', '').startswith('application/json') else r.text[:200]
        print(f"== {name} == HTTP {r.status_code} -> {json.dumps(body, ensure_ascii=False)[:300]}")
    except Exception as e:
        print(f"== {name} == ERROR {e}")


def mine():
    headers = {
        'User-Agent': UA_MINI,
        'Referer': 'https://servicewechat.com/wx50282644351869da/424/page-frame.html',
        'token': token,
        'X-Gaia-Api-Key': 'd1eb973c-64ec-4dbe-b23b-22c8117c4e8e',
        'Content-Type': 'application/json',
    }
    data = {"channel": "C2", "bu_code": "C20400", "token": token}
    try:
        r = requests.post(MINE, headers=headers, json=data, timeout=15)
        print(f"== mine-info == HTTP {r.status_code} -> {r.text[:300]}")
    except Exception as e:
        print(f"== mine-info == ERROR {e}")


mine()
clock("1 基线(全部头)", cap_header=cap)
clock("2 无cookie", use_cookie=False)
clock("3 无dxrisk", use_dxrisk=False)
clock("4 AndroidUA+cookie", ua=UA_ANDROID)
clock("5 空cap+无cookie+无dxrisk", use_cookie=False, use_dxrisk=False, cap_header='')
clock("6 假cap+无cookie+无dxrisk", use_cookie=False, use_dxrisk=False,
      cap_header='deadbeefdeadbeefdeadbeefdeadbeefdeadbeef:' + dxrisk)
