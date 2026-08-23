#!/usr/bin/env python3
"""顶象 SDK 实验：在 GitHub Actions 里直接实例化验证码，抓 validate token 与 dxrisk"""
import os
import time
import json
from playwright.sync_api import sync_playwright

TOKEN = os.getenv('LHTJ_TOKEN', '')
COOKIE = os.getenv('LHTJ_COOKIE', '')
APPID = 'd1a43734fc59aeae9f1562dbd70fdf54'
UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 27_0 like Mac OS X) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.75(0x18004b64) "
      "NetType/WIFI Language/zh_CN miniProgram/wx50282644351869da")
STEALTH = r"""
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'platform', {get: () => 'iPhone'});
Object.defineProperty(navigator, 'vendor', {get: () => 'Apple Computer, Inc.'});
Object.defineProperty(navigator, 'hardwareConcurrency', {get: () => 6});
Object.defineProperty(navigator, 'maxTouchPoints', {get: () => 5});
"""

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False, args=[
        '--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu'])
    ctx = browser.new_context(user_agent=UA, viewport={'width': 375, 'height': 812},
                              is_mobile=True, has_touch=True, locale='zh-CN',
                              timezone_id='Asia/Shanghai')
    if COOKIE:
        for part in COOKIE.split(';'):
            if '=' in part:
                k, v = part.strip().split('=', 1)
                try:
                    ctx.add_cookies([{'name': k, 'value': v,
                                      'domain': 'longzhu.longfor.com', 'path': '/'}])
                except Exception:
                    pass
    ctx.add_init_script(STEALTH)
    page = ctx.new_page()
    net = []
    page.on('request', lambda r: net.append(('REQ', r.url[:180])) if any(
        k in r.url for k in ('cap.dingxiang', 'constid', 'eventreport', 'ly-ver')) else None)
    page.on('response', lambda r: net.append(('RESP', r.status, r.url[:150])) if any(
        k in r.url for k in ('cap.dingxiang', 'constid', 'eventreport', 'ly-ver')) else None)

    page.goto('https://longzhu.longfor.com/', wait_until='networkidle', timeout=40000)
    time.sleep(2)

    result = page.evaluate('''(appid) => {
        const el = document.createElement('div'); el.id = 'capbox';
        document.body.appendChild(el);
        window.__events = [];
        const c = new window._dx.Captcha(el, {appId: appid, width: 300, height: 150, originWidth: 300});
        window.__c = c;
        for (const ev of ['ready','success','fail','error','close','verify','loaded','show','pass','refresh']) {
            try { c.on(ev, (...args) => window.__events.push([ev, args.map(a => typeof a === 'object'
                ? JSON.stringify(a).slice(0, 500) : String(a).slice(0, 500))])); } catch (e) {}
        }
        c.show();
        return 'shown';
    }''', APPID)

    # 等最多 40 秒，观察是否出现 success/pass
    final = None
    for _ in range(40):
        time.sleep(1)
        final = page.evaluate('''() => ({
            events: window.__events,
            passByServer: !!document.querySelector('.dx_captcha_loading_pass_by_server'),
            barSuccess: !!document.querySelector('.dx_captcha_loading_bar-success'),
            smartChecking: !!document.querySelector('.dx_captcha_loading_smart_checking'),
            slider: !!document.querySelector('.dx_captcha_loading_pic')
        })''')
        if final['events'] and any(e[0] in ('success', 'pass', 'verify') for e in final['events']):
            break

    # 收集存储里的 constid/dxrisk
    storage = page.evaluate('''() => {
        const out = {};
        for (let i = 0; i < localStorage.length; i++) {
            const k = localStorage.key(i);
            if (/dx|const|risk|captcha|udid/i.test(k)) out[k] = String(localStorage.getItem(k)).slice(0, 120);
        }
        return out;
    }''')

    print('=== 最终状态 ===')
    print(json.dumps(final, indent=1, ensure_ascii=False, default=str)[:4000])
    print('=== localStorage ===')
    print(json.dumps(storage, indent=1, ensure_ascii=False)[:2000])
    print('=== 网络 ===')
    for x in net[:25]:
        print(x)
    try:
        page.screenshot(path='/tmp/diag_sdk.png')
        print('截图已保存')
    except Exception:
        pass
    browser.close()
