#!/usr/bin/env python3
"""浏览器流程诊断 v2：带 task_id 重试，捕获 API 响应体，驱动签到流程"""
import os
import time
import json
from playwright.sync_api import sync_playwright

TOKEN = os.getenv('LHTJ_TOKEN', '')
USERTOKEN = os.getenv('LHTJ_USERTOKEN', '') or TOKEN
COOKIE = os.getenv('LHTJ_COOKIE', '')
ACTIVITY = os.getenv('LHTJ_ACTIVITY_NO', '') or '11111111111686241863606037740000'
UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 27_0 like Mac OS X) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.75(0x18004b64) "
      "NetType/WIFI Language/zh_CN miniProgram/wx50282644351869da")
HOME = 'https://longzhu.longfor.com/'


def make_signin(task_id_value):
    q = f'token={USERTOKEN}&buCode=C20400&channel=C2&cityCode=440300'
    if task_id_value:
        q += f'&task_id={task_id_value}'
    q += '&activity_no=' + ACTIVITY
    q += '&navFontColor=323232&navBgColor=f7dda9&title=%E6%89%93%E5%8D%A1%E7%AD%BE%E5%88%B0&navTitle='
    return f'https://longzhu.longfor.com/#/signin?{q}'


with sync_playwright() as p:
    browser = p.chromium.launch(headless=False, args=[
        '--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu'])
    ctx = browser.new_context(user_agent=UA, viewport={'width': 375, 'height': 812},
                              is_mobile=True, has_touch=True, locale='zh-CN')
    if COOKIE:
        for part in COOKIE.split(';'):
            if '=' in part:
                k, v = part.strip().split('=', 1)
                try:
                    ctx.add_cookies([{'name': k, 'value': v,
                                      'domain': 'longzhu.longfor.com', 'path': '/'}])
                except Exception:
                    pass
    page = ctx.new_page()
    reqs = []

    def on_req(r):
        if r.resource_type in ('xhr', 'fetch'):
            reqs.append(('REQ', r.method, r.url[:160]))

    def on_resp(r):
        if r.request.resource_type in ('xhr', 'fetch'):
            body = ''
            if any(k in r.url for k in ('signs/', 'signature/clock', 'verify-token', 'point')):
                try:
                    body = ' BODY=' + r.text()[:300]
                except Exception:
                    pass
            reqs.append(('RESP', r.status, r.url[:160] + body))
    page.on('request', on_req)
    page.on('response', on_resp)

    page.goto(HOME, wait_until='networkidle', timeout=30000)
    page.evaluate('(t)=>{sessionStorage.setItem("token", t)}', USERTOKEN)
    page.evaluate('''()=>{
        sessionStorage.setItem("buCode","C20400");
        sessionStorage.setItem("channel","C2");
        sessionStorage.setItem("cityCode","440300");
    }''')

    def dump(tag):
        print(f'===== {tag} =====')
        try:
            els = page.evaluate('''()=>Array.from(
                document.querySelectorAll('[class*="sign"],[class*="btn"],[class*="button"],[class*="msgbox"]'))
                .map(e=>({cls:(typeof e.className==="string"?e.className:"").slice(0,45),
                          txt:(e.innerText||"").trim().slice(0,22)}))
                .filter(x=>x.txt||x.cls.includes("sign")||x.cls.includes("btn")||x.cls.includes("button"))
                .slice(0,40)''')
            print('ELEMENTS:', els)
        except Exception as e:
            print('ELEM ERR', e)
        try:
            print('TEXT:', page.inner_text('body')[:400].replace('\n', ' | '))
        except Exception as e:
            print('TXT ERR', e)

    for task_val in [ACTIVITY, '', 'null']:
        url = make_signin(task_val)
        print(f'##### 尝试 task_id={task_val or "(无)"} #####')
        page.goto(url, wait_until='networkidle', timeout=30000)
        time.sleep(2)
        dump('加载后')
        # 关掉「知道了」弹窗
        try:
            if page.locator('text=知道了').count() > 0:
                page.locator('text=知道了').first.click(timeout=2000)
                print('>>> 关闭了「知道了」')
                time.sleep(1)
        except Exception:
            pass
        dump('关弹窗后')
        # 若 sign-now 存在则点击
        if page.locator('.sign-now').count() > 0 and page.locator('.sign-now').first.is_visible():
            page.locator('.sign-now').first.click(timeout=5000)
            print('>>> 点击了 .sign-now')
            time.sleep(2)
            dump('点击后')
            for sel in ['.msgbox .button', 'text=立即签到', 'text=知道了']:
                try:
                    if page.locator(sel).count() > 0 and page.locator(sel).first.is_visible():
                        page.locator(sel).first.click(timeout=3000)
                        print('>>> 点击了', sel)
                        time.sleep(2)
                        break
                except Exception:
                    pass
            dump('点击弹框后')
            time.sleep(6)
            dump('6秒后')
            break  # 成功渲染就停止
        else:
            print('>>> .sign-now 未渲染')

    print('===== 网络请求 =====')
    for r in reqs:
        print(r)
    try:
        page.screenshot(path='/tmp/diag_flow.png', full_page=True)
        print('截图已保存')
    except Exception:
        pass
    browser.close()
