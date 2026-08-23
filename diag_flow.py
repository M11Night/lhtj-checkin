#!/usr/bin/env python3
"""浏览器流程诊断：走一遍真实签到点击流程，观察弹框/网络请求/验证码"""
import os
import time
from playwright.sync_api import sync_playwright

TOKEN = os.getenv('LHTJ_TOKEN', '')
USERTOKEN = os.getenv('LHTJ_USERTOKEN', '') or TOKEN
COOKIE = os.getenv('LHTJ_COOKIE', '')
UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 27_0 like Mac OS X) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.75(0x18004b64) "
      "NetType/WIFI Language/zh_CN miniProgram/wx50282644351869da")
HOME = 'https://longzhu.longfor.com/'
SIGNIN = (f'https://longzhu.longfor.com/#/signin?token={USERTOKEN}'
          '&buCode=C20400&channel=C2&cityCode=440300'
          '&navFontColor=323232&navBgColor=f7dda9'
          '&title=%E6%89%93%E5%8D%A1%E7%AD%BE%E5%88%B0&navTitle=')

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
            reqs.append(('REQ', r.method, r.url[:150]))

    def on_resp(r):
        if r.request.resource_type in ('xhr', 'fetch'):
            reqs.append(('RESP', r.status, r.url[:150]))
    page.on('request', on_req)
    page.on('response', on_resp)

    page.goto(HOME, wait_until='networkidle', timeout=30000)
    page.evaluate('(t)=>{sessionStorage.setItem("token", t)}', USERTOKEN)
    page.evaluate('''()=>{
        sessionStorage.setItem("buCode","C20400");
        sessionStorage.setItem("channel","C2");
        sessionStorage.setItem("cityCode","440300");
    }''')
    page.goto(SIGNIN, wait_until='networkidle', timeout=30000)
    time.sleep(2)

    def dump(tag):
        print(f'===== {tag} =====')
        try:
            els = page.evaluate('''()=>Array.from(
                document.querySelectorAll('button,[class*="sign"],[class*="btn"],[class*="msgbox"] [class*="button"],[class*="button"]'))
                .map(e=>({cls:(typeof e.className==="string"?e.className:"").slice(0,45),
                          txt:(e.innerText||"").trim().slice(0,22)}))
                .filter(x=>x.txt||x.cls.includes("sign")||x.cls.includes("btn")||x.cls.includes("button"))
                .slice(0,40)''')
            print('ELEMENTS:', els)
        except Exception as e:
            print('ELEM ERR', e)
        try:
            print('TEXT:', page.inner_text('body')[:500].replace('\n', ' | '))
        except Exception as e:
            print('TXT ERR', e)

    dump('加载后')

    # 第一步：点 .sign-now
    try:
        page.locator('.sign-now').first.click(timeout=5000)
        print('>>> 已点击 .sign-now')
    except Exception as e:
        print('>>> .sign-now 点击失败:', str(e)[:200])
    time.sleep(2)
    dump('点击.sign-now后')

    # 第二步：找弹框/msgbox 里的按钮依次点击
    clicked = []
    for sel in ['.msgbox .button', 'text=立即签到', 'text=知道了', 'text=确定',
                'text=确认', 'text=签到', 'text=打卡', '.msgbox [class*="button"]']:
        try:
            if page.locator(sel).count() > 0 and page.locator(sel).first.is_visible():
                page.locator(sel).first.click(timeout=3000)
                clicked.append(sel)
                print(f'>>> 已点击: {sel}')
                time.sleep(2)
        except Exception:
            pass
    print('>>> 本次点击的弹框按钮:', clicked)
    dump('点击弹框按钮后')

    # 等 10 秒观察后续
    time.sleep(10)
    dump('10秒后')

    print('===== 网络请求 =====')
    for r in reqs:
        print(r)
    try:
        page.screenshot(path='/tmp/diag_flow.png', full_page=True)
        print('截图已保存 /tmp/diag_flow.png')
    except Exception:
        pass
    browser.close()
