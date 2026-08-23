#!/usr/bin/env python3
"""临时诊断脚本 v3：验证「先访问域名获取绑定当前IP的 acw_tc，再调 signature/clock」是否可行"""
import os
import json
import requests

BASE = "https://gw2c-hw-open.longfor.com/lmarketing-task-api-mvc-prod/openapi/task/v1/signature/clock"
token = os.getenv('LHTJ_TOKEN', '')
usertoken = os.getenv('LHTJ_USERTOKEN', '') or token
dxrisk = os.getenv('LHTJ_DXRISK_TOKEN', '')
cookie = os.getenv('LHTJ_COOKIE', '')
cap = os.getenv('LHTJ_CAPTCHA_TOKEN', '')
UA_MINI = ("Mozilla/5.0 (iPhone; CPU iPhone OS 27_0 like Mac OS X) AppleWebKit/605.1.15 "
           "(KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.75(0x18004b64) "
           "NetType/WIFI Language/zh_CN miniProgram/wx50282644351869da")


def base_headers(cap_header):
    h = {
        'User-Agent': UA_MINI,
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
    }
    return h


DATA = {"activity_no": os.getenv('LHTJ_ACTIVITY_NO', '') or '11111111111686241863606037740000'}


def show(name, resp):
    try:
        body = resp.json()
        print(f"== {name} == HTTP {resp.status_code} -> {json.dumps(body, ensure_ascii=False)[:300]}")
    except Exception:
        print(f"== {name} == HTTP {resp.status_code} -> {resp.text[:200]}")


# 0. 连通性：直接 GET gw2c 主机
try:
    r0 = requests.get("https://gw2c-hw-open.longfor.com/", headers={'User-Agent': UA_MINI}, timeout=10)
    print(f"== 0 连通性 GET gw2c == HTTP {r0.status_code} Set-Cookie头: {r0.headers.get('Set-Cookie','')[:120]}")
except Exception as e:
    print(f"== 0 连通性 GET gw2c == ERROR {e}")

# 1. 用手机抓的 cookie（基线）
try:
    h = base_headers(cap)
    h['Cookie'] = cookie
    r1 = requests.post(BASE, headers=h, json=DATA, timeout=15)
    show("1 手机cookie(基线)", r1)
except Exception as e:
    print(f"== 1 手机cookie == ERROR {e}")

# 2. 新建 Session，先访问两个域名拿绑定本IP的新 acw_tc，再调接口
s2 = requests.Session()
s2.headers.update({'User-Agent': UA_MINI})
for u in ['https://longzhu.longfor.com/', 'https://gw2c-hw-open.longfor.com/']:
    try:
        s2.get(u, timeout=10)
    except Exception:
        pass
print(f"== 2 新Session的cookies == {list(s2.cookies.items())}")
try:
    h2 = base_headers(cap)
    r2 = s2.post(BASE, headers=h2, json=DATA, timeout=15)
    show("2 新acw_tc+有效cap", r2)
except Exception as e:
    print(f"== 2 新acw_tc == ERROR {e}")

# 3. 新Session + 空cap
try:
    h3 = base_headers('')
    r3 = s2.post(BASE, headers=h3, json=DATA, timeout=15)
    show("3 新acw_tc+空cap", r3)
except Exception as e:
    print(f"== 3 新acw_tc+空cap == ERROR {e}")
