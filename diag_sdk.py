#!/usr/bin/env python3
"""顶象 SDK v2：GitHub Actions 里完整跑验证码，抓 validate token"""
import os
import time
import json
from playwright.sync_api import sync_playwright

TOKEN = os.getenv('LHTJ_TOKEN', '')
COOKIE = os.getenv('LHTJ_COOKIE', '')
CONFIG = {
    'appId': 'd1a43734fc59aeae9f1562dbd70fdf54',
    'constIDServer': 'https://ly-sta.longhu.net/udid/c1',
    'constID_js': 'https://s.longfor.com/dx-captcha/libs/const-id.js',
    'ua_js': 'https://s.longfor.com/dx-captcha/libs/greenseer.js',
    'apiServer': 'https://ly-ver.longhu.net',
    'isSaaS': False,
    'serverlessBgSrc': 'https://ly-sta.longhu.net',
    'style': 'popup', 'width': 300, 'height': 150, 'originWidth': 300,
}
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
HOOK = r"""
window.__net = [];
(function() {
    const oOpen = XMLHttpRequest.prototype.open, oSend = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function(m, u) { this.__u = String(u); return oOpen.apply(this, arguments); };
    XMLHttpRequest.prototype.send = function() {
        const self = this;
        this.addEventListener('load', function() {
            if (/longhu\.net|dingxiang/.test(self.__u)) {
                const t = self.responseText || '';
                window.__net.push(['XHR', self.__u.slice(0, 160), t.slice(0, 900)]);
            }
        });
        return oSend.apply(this, arguments);
    };
})();
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
    ctx.add_init_script(HOOK)
    page = ctx.new_page()
    page.goto('https://longzhu.longfor.com/', wait_until='networkidle', timeout=40000)
    time.sleep(2)

    has_dx = page.evaluate('typeof window._dx')
    print('=== _dx exists:', has_dx, '===')

    page.evaluate('''(config) => {
        const el = document.createElement('div'); el.id = 'capbox'; document.body.appendChild(el);
        window.__events = [];
        const c = new window._dx.Captcha(el, config); window.__c = c;
        for (const ev of ['ready','success','fail','error','verifySuccess','passByServer',
                          'verifyDone','verify','show','hide','dragEnd','loadFail']) {
            try { c.on(ev, (...args) => window.__events.push([ev, args.map(a => typeof a === 'object'
                ? JSON.stringify(a).slice(0, 500) : String(a).slice(0, 500))])); } catch (e) {}
        }
        c.show();
    }''', CONFIG)

    final = None
    for i in range(24):
        time.sleep(5)
        final = page.evaluate('''() => ({
            smart: !!document.querySelector('.dx_captcha_loading_smart_checking'),
            pass: !!document.querySelector('.dx_captcha_loading_pass_by_server'),
            success: !!document.querySelector('.dx_captcha_loading_bar-success'),
            slider: !!document.querySelector('.dx_captcha_loading_pic'),
            basic: !!document.querySelector('.dx_captcha_basic_wrapper'),
            events: window.__events,
            domSnippet: (document.getElementById('capbox')||{}).innerHTML ?
                document.getElementById('capbox').innerHTML.slice(0, 150) : ''
        })''')
        print(f'[{i*5}s] smart={final["smart"]} pass={final["pass"]} success={final["success"]} slider={final["slider"]} events={len(final["events"])}')
        if any(e[0] in ('success', 'verifySuccess', 'passByServer') for e in final['events']):
            break

    print('=== 最终事件 ===')
    print(json.dumps(final['events'], indent=1, ensure_ascii=False, default=str)[:3000])
    print('=== 网络(ly-ver) ===')
    for x in page.evaluate('window.__net'):
        if 'api/' in x[1]:
            print(json.dumps(x, ensure_ascii=False)[:800])
    try:
        page.screenshot(path='/tmp/diag_sdk.png')
        print('截图已保存')
    except Exception:
        pass
    browser.close()
