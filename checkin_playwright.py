#!/usr/bin/env python3
"""
龙湖天街自动签到 — Playwright 兜底方案（两方案并存策略）
================================================================
定位：API 方案（checkin.py）失败时的兜底，而非替代。
触发：checkin.yml 签到失败时通过 gh workflow run 触发本脚本。
职责：
  1. 用浏览器完整走签到流程（注入长效 Token，无需微信授权）
  2. 过顶象验证码：优先等无感放行(pass_by_server)，不行才 OpenCV 解滑块
  3. 捕获新的 captcha-token 写回 GitHub Secrets，让 API 方案恢复（续命 ~3 天）
  4. 企业微信推送结果
================================================================
"""

import os
import sys
import time
import json
import random
import subprocess
from datetime import datetime

import requests
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# OpenCV 用于滑块缺口识别（可选，缺失则跳过滑块求解）
try:
    import cv2
    import numpy as np
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

# ======================== 配置 ========================
LHTJ_TOKEN = os.getenv('LHTJ_TOKEN', '').strip()
LHTJ_USERTOKEN = os.getenv('LHTJ_USERTOKEN', '').strip()
LHTJ_DXRISK_TOKEN = os.getenv('LHTJ_DXRISK_TOKEN', '').strip()
LHTJ_COOKIE = os.getenv('LHTJ_COOKIE', '').strip()
LHTJ_ACTIVITY_NO = os.getenv('LHTJ_ACTIVITY_NO', '').strip()
WECOM_WEBHOOK = os.getenv('WECOM_WEBHOOK', '').strip()
GH_TOKEN = os.getenv('GH_TOKEN', '').strip() or os.getenv('GITHUB_TOKEN', '').strip()
GITHUB_REPOSITORY = os.getenv('GITHUB_REPOSITORY', '').strip()

# headless 控制：有 DISPLAY（xvfb-run 提供）时默认有头，否则回退 headless
_headless_env = os.getenv('PW_HEADLESS', '').strip().lower()
if _headless_env in ('1', 'true', 'yes'):
    HEADLESS = True
elif _headless_env in ('0', 'false', 'no'):
    HEADLESS = False
else:
    HEADLESS = not bool(os.getenv('DISPLAY', ''))

# 设备像素比：移动端模拟用 2。缺口识别在「截图像素」里做，需除以它换算成 CSS 像素
DEVICE_SCALE_FACTOR = 2

HOME_URL = 'https://longzhu.longfor.com/'
# 签到页：token 通过 URL 参数 + sessionStorage 传递
SIGNIN_URL = ('https://longzhu.longfor.com/#/signin?token={token}'
              '&buCode=C50701&channel=C5&cityCode=440300&task_id=null'
              '&navFontColor=323232&navBgColor=f7dda9&title=%E6%89%93%E5%8D%A1%E7%AD%BE%E5%88%B0&navTitle=')

# 成长值查询（与 API 方案一致，用于验证签到到账）
MINE_INFO_URL = 'https://longzhu-api.longfor.com/lmember-member-open-api-prod/api/member/v1/mine-info'

UA_IPHONE = ('Mozilla/5.0 (iPhone; CPU iPhone OS 17_4_1 like Mac OS X) '
             'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 '
             'Mobile/15E148 Safari/604.1')

notify_msg = []
captured_captcha_token = None  # 从网络请求中捕获的新 captcha-token
captured_dxrisk_token = None   # 新的 dxrisk-token（若有）


# ======================== 日志 / 推送 ========================
def log(msg):
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    notify_msg.append(msg)


def push_wecom(content):
    if not WECOM_WEBHOOK:
        log("ℹ️ 未配置企业微信 Webhook，跳过推送")
        return
    try:
        resp = requests.post(WECOM_WEBHOOK, json={
            'msgtype': 'markdown',
            'markdown': {'content': content}
        }, timeout=10)
        r = resp.json()
        if r.get('errcode') == 0:
            log("✅ 企业微信推送成功")
        else:
            log(f"⛔️ 推送失败: {r.get('errmsg')}")
    except Exception as e:
        log(f"⛔️ 推送异常: {e}")


def write_secret(name, value):
    """用 gh CLI 把新 token 写回 GitHub Secrets"""
    if not GH_TOKEN or not GITHUB_REPOSITORY:
        log(f"⚠️ 无 GH_TOKEN/GITHUB_REPOSITORY，跳过 Secret 写回（{name}）")
        return False
    if not value:
        log(f"⚠️ {name} 值为空，跳过写回")
        return False
    try:
        env = {**os.environ, 'GH_TOKEN': GH_TOKEN, 'GITHUB_TOKEN': GH_TOKEN}
        r = subprocess.run(
            ['gh', 'secret', 'set', name, '-R', GITHUB_REPOSITORY, '--body', value],
            env=env, capture_output=True, timeout=30
        )
        if r.returncode == 0:
            log(f"✅ Secret {name} 已写回（续命 ~3 天）")
            return True
        log(f"⛔️ Secret {name} 写回失败: {r.stderr.decode()[:200]}")
        return False
    except Exception as e:
        log(f"⛔️ Secret 写回异常: {e}")
        return False


# ======================== 成长值查询（验证签到到账）========================
def get_growth_value(token):
    try:
        headers = {
            'User-Agent': UA_IPHONE,
            'Referer': 'https://servicewechat.com/wx50282644351869da/424/page-frame.html',
            'token': token,
            'X-Gaia-Api-Key': 'd1eb973c-64ec-4dbe-b23b-22c8117c4e8e',
            'Content-Type': 'application/json'
        }
        data = {"channel": "C2", "bu_code": "C20400", "token": token}
        r = requests.post(MINE_INFO_URL, headers=headers, json=data, timeout=15)
        res = r.json()
        if res.get('code') == '0000':
            return res['data'].get('growth_value', 0)
    except Exception as e:
        log(f"⚠️ 查询成长值异常: {e}")
    return None


# ======================== 反检测注入 ========================
STEALTH_JS = r"""
// 抹掉 webdriver 标记
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});

// ---- 自洽的 iPhone 指纹（与 UA_IPHONE / is_mobile / has_touch 保持一致，别自相矛盾）----
Object.defineProperty(navigator, 'platform', {get: () => 'iPhone'});
Object.defineProperty(navigator, 'vendor', {get: () => 'Apple Computer, Inc.'});
Object.defineProperty(navigator, 'hardwareConcurrency', {get: () => 6});
Object.defineProperty(navigator, 'maxTouchPoints', {get: () => 5});
// iPhone Safari 不暴露 deviceMemory —— 别硬塞假值（塞 4 反而自相矛盾）
try { Object.defineProperty(navigator, 'deviceMemory', {get: () => undefined}); } catch (e) {}

// plugins 用空 PluginArray 语义（iPhone Safari 的 plugins.length 为 0），而非塞 [1,2,3,4,5]
try {
    Object.defineProperty(navigator, 'plugins', {get: () => ({
        length: 0, item: () => null, namedItem: () => null, refresh: () => {}
    })});
} catch (e) {}

// 移除无头 Chromium 的 chrome 特征对象（iPhone Safari 没有 window.chrome）
try { delete window.chrome; } catch (e) {}
try { Object.defineProperty(window, 'chrome', {get: () => undefined}); } catch (e) {}

// 语言
Object.defineProperty(navigator, 'language', {get: () => 'zh-CN'});
Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh', 'en']});

// permissions.query 劫持（通知权限返回真实状态，避免返回被检测的 pending）
const _q = window.navigator.permissions && window.navigator.permissions.query;
if (_q) {
    window.navigator.permissions.query = (p) => p && p.name === 'notifications'
        ? Promise.resolve({state: Notification.permission})
        : _q(p);
}

// iframe contentWindow 特征抹平
try {
    Object.defineProperty(HTMLIFrameElement.prototype, 'contentWindow', {
        get: function() { return window; }
    });
} catch (e) {}

// canvas 指纹轻量扰动（固定 seed，会话内稳定，避开无头默认值）
(() => {
    const seed = 0x5A5A5A5A;
    const orig = HTMLCanvasElement.prototype.toDataURL;
    HTMLCanvasElement.prototype.toDataURL = function(...a) {
        try {
            const c = this.getContext('2d');
            if (c) {
                const d = c.getImageData(0, 0, Math.min(this.width, 32), Math.min(this.height, 32));
                for (let i = 0; i < d.data.length; i += 4) {
                    d.data[i] = (d.data[i] + ((seed >> (i % 24)) & 3)) & 255;
                }
                c.putImageData(d, 0, 0);
            }
        } catch (e) {}
        return orig.apply(this, a);
    };
})();
"""


# ======================== Cookie 注入 ========================
def build_cookies(cookie_str):
    """把 'acw_tc=xxx; k=v' 串解析成 Playwright cookie 列表"""
    cookies = []
    for part in cookie_str.split(';'):
        part = part.strip()
        if '=' not in part:
            continue
        k, _, v = part.partition('=')
        k, v = k.strip(), v.strip()
        if k:
            cookies.append({'name': k, 'value': v, 'domain': 'longzhu.longfor.com', 'path': '/'})
    return cookies


# ======================== 滑块求解（OpenCV）========================
def find_gap_x(screenshot_bytes):
    """
    对滑块背景截图识别缺口，返回缺口左边界横坐标（截图像素）。
    顶象滑块：背景是真实照片，缺口是带阴影边框的「洞」。
    相对旧版（整图按列求和 + 找第一个超阈值列）的三处改进：
      1. 只取图像中部 y 带，排除上下 UI/logo 的竖边干扰
      2. 取「峰值列」而非「第一个超阈值列」，避开背景纹理误报
      3. 峰值必须显著高于基线，否则返回 None（交给上层刷新重试），绝不瞎给坐标
    """
    if not HAS_CV2:
        return None
    arr = np.frombuffer(screenshot_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        return None
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(gray, 80, 200)
    # 只统计中部 y 带，减少上下文字/logo 的竖边干扰
    y0, y1 = int(h * 0.20), int(h * 0.80)
    band = edges[y0:y1, :]
    col_sum = band.sum(axis=0).astype(np.float64)
    # 平滑
    kernel = 5
    smooth = np.convolve(col_sum, np.ones(kernel) / kernel, mode='same')
    # 跳过最左 20%（拼图块及其阴影区，边缘密集会干扰）
    start = int(w * 0.20)
    tail = smooth[start:]
    if len(tail) == 0:
        return None
    peak = int(np.argmax(tail))
    peak_val = float(tail[peak])
    med = float(np.median(tail))
    std = float(np.std(tail))
    # 峰值必须显著：超过 中位数+3σ 且绝对强度足够，否则视为没找到
    if peak_val < med + max(3.0 * std, 25.0):
        return None
    gap_x = start + peak
    # 向左回退到峰的左脚（上升沿起点），更接近缺口真实左边界
    while gap_x > start and smooth[gap_x - 1] > med:
        gap_x -= 1
    return gap_x


def human_drag(page, locator, distance):
    """
    拟人化拖动滑块：三段式变速（慢起步加速→匀速→减速）+ 过冲回调 + 连续事件流。
    distance: 需要移动的横向 CSS 像素数。
    """
    if distance <= 0:
        return False
    box = locator.bounding_box()
    if not box:
        return False
    start_x = box['x'] + box['width'] / 2
    start_y = box['y'] + box['height'] / 2

    overshoot = random.uniform(3, 6)
    target = distance + overshoot
    steps = random.randint(80, 120)          # 事件点翻倍，接近真人事件流密度
    pts = []
    for i in range(steps):
        t = i / steps
        # 三段式：慢起步（加速段）→ 匀速段 → 减速段
        if t < 0.25:
            p = (t / 0.25) ** 2 * 0.25        # 起点速度≈0，避免一步跳 10%
        elif t < 0.75:
            p = 0.25 + (t - 0.25) / 0.5 * 0.6
        else:
            p = 0.85 + (1 - (1 - (t - 0.75) / 0.25) ** 2) * 0.15
        pts.append((target * p + random.uniform(-0.5, 0.5),
                    random.uniform(-1.0, 1.0)))
    # 过冲回拉到真实目标（t 归一化 0→1，确保最终停在 distance）
    back_steps = random.randint(6, 10)
    for i in range(back_steps):
        t = i / max(back_steps - 1, 1)
        x = target - overshoot * t
        pts.append((x + random.uniform(-0.4, 0.4), random.uniform(-0.6, 0.6)))

    page.mouse.move(start_x, start_y)
    page.mouse.down()
    time.sleep(random.uniform(0.10, 0.20))
    for px, py in pts:
        # steps= 让 Playwright 派发连续 mousemove 事件，而不是单点瞬移
        page.mouse.move(start_x + px, start_y + py, steps=random.randint(2, 4))
        time.sleep(random.uniform(0.004, 0.016))
    time.sleep(random.uniform(0.15, 0.30))
    page.mouse.up()
    return True


# 顶象拼图块常见选择器（如与你的版本 DOM 不符，用 DevTools 确认后调整即可）
PIECE_SELECTORS = [
    '.dx_captcha_loading_basic_pic-slide',
    '.dx_captcha_loading_basic_slider-icon',
    '[class*="dx_captcha_loading_basic_pic"] canvas',
    '[class*="jigsaw"]',
    '[class*="slider-icon"]',
    '[class*="slide-piece"]',
    '[class*="slide_piece"]',
]


def _locate_piece(page):
    """尽力定位拼图块元素；找不到返回 None（此时按 piece_left=0 处理）。"""
    for sel in PIECE_SELECTORS:
        try:
            loc = page.locator(sel).first
            if loc.count() > 0 and loc.is_visible():
                return loc
        except Exception:
            continue
    return None


def _refresh_captcha(page):
    """点刷新按钮换一张图，避免同一张图反复误判。"""
    try:
        page.locator('.dx_captcha_loading_refresh, .dx_captcha_loading_img_btn_refresh').first.click(timeout=2000)
        time.sleep(1.2)
    except Exception:
        pass


def solve_slider(page, attempt):
    """尝试解滑块，返回 True/False。"""
    if not HAS_CV2:
        log("⛔️ 未安装 OpenCV，无法解滑块")
        return False
    try:
        pic = page.locator('.dx_captcha_loading_pic').first
        pic.wait_for(state='visible', timeout=8000)
        time.sleep(0.8)  # 等图片加载完
    except Exception:
        log(f"  第{attempt}次: 未找到滑块图片区域")
        return False

    # 截图滑块图区域
    shot = pic.screenshot()
    gap_x_img = find_gap_x(shot)
    if gap_x_img is None:
        log(f"  第{attempt}次: OpenCV 未识别到缺口（低置信度），刷新重试")
        _refresh_captcha(page)
        return False

    # 截图像素 → CSS 像素换算（截图按 deviceScaleFactor 放大）
    try:
        dpr = float(page.evaluate('window.devicePixelRatio')) or 1.0
    except Exception:
        dpr = 1.0
    gap_css = gap_x_img / dpr

    # 距离校准：缺口横坐标(相对截图左边界) - 拼图块初始左边界(相对截图左边界)
    try:
        pic_box = pic.bounding_box()
    except Exception:
        pic_box = None
    piece = _locate_piece(page)
    piece_left = 0.0
    if piece is not None and pic_box is not None:
        try:
            piece_box = piece.bounding_box()
            piece_left = piece_box['x'] - pic_box['x']
        except Exception:
            piece_left = 0.0
    distance = gap_css - piece_left
    if distance <= 0:
        log(f"  第{attempt}次: 计算的拖拽距离异常({distance:.1f}px)，刷新重试")
        _refresh_captcha(page)
        return False
    log(f"  第{attempt}次: 缺口≈{gap_x_img}px(截图) → 拖拽距离≈{distance:.1f}px(CSS)")

    # 找滑块拖动按钮（顶象 slider 按钮）
    handle = None
    for sel in ['.dx_captcha_loading .dx_captcha_loading_state-box',
                '[class*="sliderBar"]', '[class*="slider"]',
                '.dx_captcha_loading_basic_bar', '.dx_captcha_loading_bar-verifying']:
        try:
            if page.locator(sel).count() > 0:
                handle = page.locator(sel).first
                break
        except Exception:
            continue
    if handle is None:
        log(f"  第{attempt}次: 未找到滑块按钮")
        return False

    ok = human_drag(page, handle, distance)
    if not ok:
        return False
    time.sleep(2.0)
    # 检测是否成功（pass_by_server / bar-success / captcha 消失）
    try:
        page.wait_for_selector(
            '.dx_captcha_loading_pass_by_server, .dx_captcha_loading_bar-success',
            state='visible', timeout=5000
        )
        log(f"  ✅ 第{attempt}次滑块通过")
        return True
    except Exception:
        log(f"  第{attempt}次滑块未通过，准备重试")
        _refresh_captcha(page)
        return False


# ======================== 主流程 ========================
def run():
    if not LHTJ_TOKEN:
        log("❌ 缺少 LHTJ_TOKEN，无法启动 Playwright 兜底")
        return 'failed'
    if not HAS_CV2:
        log("⚠️ 未安装 opencv，滑块模式将无法自动过（仅能靠无感放行）")

    log("🚀 Playwright 兜底签到启动")
    log(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    growth_before = get_growth_value(LHTJ_TOKEN)
    if growth_before is not None:
        log(f"📊 签到前成长值: {growth_before}")

    result = 'failed'
    with sync_playwright() as p:
        if HEADLESS:
            log("⚠️ 无 DISPLAY，回退 headless（建议用 xvfb-run -a 启动以获得有头模式）")
        else:
            log("🖥️  有头模式（headful）运行，设备指纹更真实")
        browser = p.chromium.launch(headless=HEADLESS, args=[
            '--no-sandbox', '--disable-setuid-sandbox',
            '--disable-blink-features=AutomationControlled',
            '--disable-dev-shm-usage',
            '--disable-gpu',           # CI 无 GPU，用软件渲染避免崩溃
            '--hide-scrollbars',
        ])
        context = browser.new_context(
            user_agent=UA_IPHONE,
            viewport={'width': 375, 'height': 812},
            screen={'width': 375, 'height': 812},
            is_mobile=True,
            has_touch=True,
            locale='zh-CN',
            timezone_id='Asia/Shanghai',
            device_scale_factor=DEVICE_SCALE_FACTOR,
        )
        context.add_init_script(STEALTH_JS)
        # 注入 cookie
        if LHTJ_COOKIE:
            try:
                context.add_cookies(build_cookies(LHTJ_COOKIE))
            except Exception as e:
                log(f"⚠️ Cookie 注入异常: {e}")

        page = context.new_page()

        # ---- 网络拦截：捕获 captcha-token ----
        def on_request(req):
            global captured_captcha_token, captured_dxrisk_token
            url = req.url
            if 'signature/clock' in url or ('/task/v1/' in url and 'clock' in url):
                h = req.headers
                ct = h.get('x-lf-dxrisk-captcha-token', '')
                dt = h.get('x-lf-dxrisk-token', '')
                if ct:
                    captured_captcha_token = ct
                    log(f"🔓 捕获到 captcha-token: {ct[:30]}...")
                if dt:
                    captured_dxrisk_token = dt
        page.on('request', on_request)

        try:
            result = do_signin(page)
        except Exception as e:
            log(f"🚨 签到流程异常: {e}")
            try:
                page.screenshot(path='/tmp/pw_error.png', full_page=True)
                log("📸 已保存异常截图 /tmp/pw_error.png")
            except Exception:
                pass
            result = 'failed'
        finally:
            browser.close()

    # ---- 写回新 token ----
    token_refreshed = False
    if captured_captcha_token and result in ('new', 'token_only'):
        token_refreshed = write_secret('LHTJ_CAPTCHA_TOKEN', captured_captcha_token)
        if captured_dxrisk_token and captured_dxrisk_token != LHTJ_DXRISK_TOKEN:
            write_secret('LHTJ_DXRISK_TOKEN', captured_dxrisk_token)

    # ---- 验证签到到账 ----
    if result == 'new':
        time.sleep(2)
        growth_after = get_growth_value(LHTJ_TOKEN)
        if growth_before is not None and growth_after is not None:
            diff = growth_after - growth_before
            if diff > 0:
                log(f"📈 签到验证: 成长值 {growth_before} → {growth_after}（+{diff}）✅到账")
            else:
                log(f"⚠️ 成长值未变化({growth_before}→{growth_after})，可能延迟到账")

    # ---- 推送 ----
    today = datetime.now().strftime('%Y-%m-%d')
    if result == 'new':
        title = "🎭 龙湖天街签到成功（Playwright 兜底）"
    elif result == 'already':
        title = "ℹ️ 今日已签到（Playwright 检测）"
    elif result == 'token_only':
        title = "🔓 兜底已刷新 captcha-token（API 可恢复）"
    else:
        title = "🚨 Playwright 兜底失败"
    content = f"## {title}\n---\n📅 {today}\n\n" + "\n".join(notify_msg)
    if token_refreshed:
        content += "\n\n✅ **已自动刷新 LHTJ_CAPTCHA_TOKEN，API 方案恢复 ~3 天**"
    push_wecom(content)

    log("Playwright 兜底任务结束")
    if result == 'failed':
        sys.exit(1)
    return result


def do_signin(page):
    """核心签到流程。返回 'new'/'already'/'token_only'/'failed'"""
    # H5 认证：x-lf-usertoken 头 ← sessionStorage "token"。
    # 实测 H5 web token 对应 LHTJ_USERTOKEN（与 API 的 LHTJ_TOKEN 是两个不同凭证）。
    # 优先用 LHTJ_USERTOKEN，失败则退回 LHTJ_TOKEN 尝试。
    h5_tokens = [t for t in [LHTJ_USERTOKEN, LHTJ_TOKEN] if t]
    if not h5_tokens:
        log("⛔️ 无可用 Token（LHTJ_USERTOKEN / LHTJ_TOKEN 均为空）")
        return 'failed'

    for idx, h5_token in enumerate(h5_tokens):
        which = 'LHTJ_USERTOKEN' if idx == 0 and LHTJ_USERTOKEN else 'LHTJ_TOKEN'
        log(f"→ 打开首页并注入 Token（尝试 {which}）...")
        page.goto(HOME_URL, wait_until='networkidle', timeout=30000)
        page.evaluate('(t) => { sessionStorage.setItem("token", t); }', h5_token)
        page.evaluate('''() => {
            sessionStorage.setItem("buCode", "C50701");
            sessionStorage.setItem("channel", "C5");
            sessionStorage.setItem("cityCode", "440300");
        }''')

        # 2. 跳转签到页（带 token 参数）
        log("→ 跳转签到页...")
        page.goto(SIGNIN_URL.format(token=h5_token), wait_until='networkidle', timeout=30000)
        time.sleep(2)
        page.screenshot(path='/tmp/pw_signin_page.png', full_page=True)

        body_text = page.inner_text('body')
        # 检测登录态
        if '登录已过期' in body_text or '请重新登录' in body_text:
            log(f"⚠️ {which} 无效（H5 判定登录已过期）")
            # 点"知道了"关闭弹窗
            try:
                page.locator('text=知道了').first.click(timeout=2000)
            except Exception:
                pass
            if idx < len(h5_tokens) - 1:
                log("→ 换下一个 Token 重试...")
                continue
            log("⛔️ 两个 Token 均无法通过 H5 认证。长效 Token 可能已过期，需重新抓包")
            return 'failed'
        # 认证通过，继续签到
        log(f"✅ {which} 认证通过")
        break

    # 检测今日已签到
    if '今日已签到' in body_text or '已签到' in body_text:
        if '今日还未签到' not in body_text:
            log("ℹ️ 今日已签到，无需操作")
            return 'already'

    # 3. 点击「立即签到」
    log("→ 点击「立即签到」...")
    clicked = False
    for sel in ['.sign-now', 'text=立即签到', 'text=签到', '[class*="sign-now"]']:
        try:
            btn = page.locator(sel).first
            if btn.count() > 0 and btn.is_visible():
                btn.click(timeout=5000)
                clicked = True
                log(f"  点击成功: {sel}")
                break
        except Exception:
            continue
    if not clicked:
        log("⚠️ 未找到签到按钮，尝试直接调用 sign()")
        # 兜底：尝试 JS 触发 Vue 组件的 handleSign
        try:
            page.evaluate('''() => {
                const els = document.querySelectorAll('*');
                for (const el of els) {
                    if (el.className && typeof el.className === 'string' && el.className.includes('sign-now')) {
                        el.click(); return true;
                    }
                }
                return false;
            }''')
            clicked = True
        except Exception:
            pass

    time.sleep(2)
    page.screenshot(path='/tmp/pw_after_click.png', full_page=True)

    # 4. 等待结果：成功 / 验证码 / 失败
    log("→ 等待签到结果（成功/验证码/失败）...")
    signin_done = False
    captcha_appeared = False

    # 轮询检测 8 秒
    for _ in range(16):
        time.sleep(0.5)
        try:
            html = page.content()
        except Exception:
            break
        # 顶象验证码出现
        if 'dx_captcha' in html and ('dx_captcha_loading_smart_checking' in html
                                      or 'dx_captcha_loading_main-box' in html
                                      or 'dx_captcha_loading_state-box' in html):
            captcha_appeared = True
            log("🤖 检测到顶象验证码")
            break
        # 签到成功标志
        if 'signing finish' in html or 'signin-done' in html or '签到成功' in page.inner_text('body'):
            signin_done = True
            log("✅ 签到成功（无需验证码）")
            break
        # 错误弹窗
        bt = page.inner_text('body')
        if '活动太火爆' in bt:
            log("⚠️ 活动太火爆（801810），稍后重试")
            break

    # 5. 处理验证码
    if captcha_appeared:
        handled = handle_captcha(page)
        if handled:
            time.sleep(2)
            bt = page.inner_text('body')
            if '签到成功' in bt or 'signing finish' in page.content() or 'signin-done' in page.content():
                signin_done = True
                log("✅ 验证码通过，签到成功")
            else:
                # 验证码过了但签到状态未明确 → 至少 token 已刷新
                if captured_captcha_token:
                    log("🔓 验证码已过，captcha-token 已捕获（签到结果待确认）")
                    return 'token_only'
                else:
                    log("⚠️ 验证码通过但未捕获到 token 且签到未确认")
        else:
            log("⛔️ 验证码未通过")
            page.screenshot(path='/tmp/pw_captcha_fail.png', full_page=True)

    # 6. 最终判定
    if signin_done:
        return 'new'
    # 即使签到没确认，但只要捕获到新 token 也算部分成功
    if captured_captcha_token:
        log("🔓 签到结果未确认，但已捕获新 captcha-token")
        return 'token_only'
    return 'failed'


def handle_captcha(page):
    """处理顶象验证码：先等无感放行，不行再解滑块。返回 True/False"""
    # 5.1 先等无感放行（pass_by_server），最多 6 秒
    log("  → 等待顶象无感检测（pass_by_server）...")
    for _ in range(12):
        time.sleep(0.5)
        try:
            html = page.content()
        except Exception:
            break
        if 'dx_captcha_loading_pass_by_server' in html:
            log("  ✅ 顶象无感放行（pass_by_server）")
            return True
        # 滑块图出现 = 需要手动解
        if 'dx_captcha_loading_pic' in html and page.locator('.dx_captcha_loading_pic').count() > 0:
            try:
                if page.locator('.dx_captcha_loading_pic').first.is_visible():
                    log("  → 无感未过，进入滑块模式")
                    break
            except Exception:
                pass
        # 直接成功
        if 'dx_captcha_loading_bar-success' in html:
            log("  ✅ 顶象验证成功")
            return True

    # 5.2 滑块模式：OpenCV 求解，最多 5 次
    if not HAS_CV2:
        log("  ⛔️ 滑块模式但无 OpenCV，无法继续")
        return False
    for attempt in range(1, 6):
        log(f"  → 第 {attempt}/5 次解滑块")
        if solve_slider(page, attempt):
            return True
        time.sleep(1.0)
    return False


if __name__ == '__main__':
    run()
