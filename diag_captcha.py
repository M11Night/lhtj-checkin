#!/usr/bin/env python3
"""临时诊断脚本：探查 signature/clock 在空/假 captcha-token 时的 801810 响应结构。
顺序：先空→假→有效，避免有效 token 先签到成功导致后续返回「已签到」污染诊断。
"""
import os
import json
import requests

BASE = "https://gw2c-hw-open.longfor.com/lmarketing-task-api-mvc-prod/openapi/task/v1/signature/clock"
token = os.getenv('LHTJ_TOKEN', '')
usertoken = os.getenv('LHTJ_USERTOKEN', '') or token
dxrisk = os.getenv('LHTJ_DXRISK_TOKEN', '')
cookie = os.getenv('LHTJ_COOKIE', '')
cap = os.getenv('LHTJ_CAPTCHA_TOKEN', '')
UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 27_0 like Mac OS X) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.75(0x18004b64) "
      "NetType/WIFI Language/zh_CN miniProgram/wx50282644351869da")


def call(name, cap_header):
    headers = {
        'User-Agent': UA,
        'Accept': 'application/json, text/plain, */*',
        'Content-Type': 'application/json;charset=UTF-8',
        'X-LF-DXRisk-Source': '5',
        'X-LF-Bu-Code': 'C20400',
        'X-GAIA-API-KEY': 'c06753f1-3e68-437d-b592-b94656ea5517',
        'X-LF-UserToken': usertoken,
        'X-LF-Channel': 'C2',
        'X-LF-DXRisk-Token': dxrisk,
        'X-LF-DXRisk-Captcha-Token': cap_header,
        'token': token,
        'Origin': 'https://longzhu.longfor.com',
        'Referer': 'https://longzhu.longfor.com/',
        'Cookie': cookie,
    }
    data = {"activity_no": os.getenv('LHTJ_ACTIVITY_NO', '') or '11111111111686241863606037740000'}
    print(f"===== {name} =====")
    for attempt in range(3):
        try:
            r = requests.post(BASE, headers=headers, json=data, timeout=15)
            print(f"HTTP {r.status_code}")
            try:
                print(json.dumps(r.json(), ensure_ascii=False, indent=2))
            except Exception:
                print(r.text[:2000])
            break
        except Exception as e:
            print(f"尝试{attempt + 1}失败: {e}")


call("B1: 空 captcha-token", '')
call("B2: 假 captcha-token", 'deadbeefdeadbeefdeadbeefdeadbeefdeadbeef:' + dxrisk)
call("A: 有效 captcha-token", cap)
