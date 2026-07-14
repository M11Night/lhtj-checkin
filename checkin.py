#!/usr/bin/env python3
"""
龙湖天街自动签到 — GitHub Actions 版（健壮版 v2）
改进点：
  1. 修复 Token 过期检测被异常吞掉的 Bug
  2. 签到失败自动重试 3 次
  3. 签到前后成长值对比，验证积分真实到账
  4. 签到失败时 exit(1)，让 Actions 显示红色 + 触发告警 Issue
  5. 已签到时静默退出，避免多时段 cron 重复推送
  6. 移除无意义的 asyncio（原为同步 requests 伪装 async）
"""

import os
import sys
import random
import time
import logging
import requests
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

BASE_URL = "https://gw2c-hw-open.longfor.com"
USER_AGENTS = [
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI MiniProgramEnv/Windows WindowsWechat/WMPF",
]

notify_msg = []


def double_log(msg):
    logger.info(msg)
    notify_msg.append(msg)


class TokenExpiredError(Exception):
    """Token 过期异常 — 不被重试吞掉"""
    pass


def http_request(url, headers, method='POST', data=None, timeout=15, retries=2):
    """带重试的 HTTP 请求。Token 过期时直接抛出 TokenExpiredError"""
    last_err = None
    for attempt in range(retries + 1):
        try:
            hdrs = {k.lower(): v for k, v in headers.items()}
            if method.upper() == 'POST':
                resp = requests.post(url, headers=hdrs, json=data, timeout=timeout)
            else:
                resp = requests.get(url, headers=hdrs, params=data, timeout=timeout)
            resp.raise_for_status()
            res = resp.json()
            # Token 过期检测 —— 抛出专用异常，不被下方 except 吞掉
            msg = res.get('message', '')
            if msg and ('登录已过期' in msg or '用户未登录' in msg):
                raise TokenExpiredError(f"Token已过期：{msg}")
            return res
        except TokenExpiredError:
            raise  # 直接上抛，不重试
        except Exception as e:
            last_err = e
            if attempt < retries:
                wait = random.uniform(3, 8)
                logger.warning(f"请求失败(第{attempt+1}次)，{wait:.1f}s后重试: {e}")
                time.sleep(wait)
    logger.error(f"请求彻底失败(共{retries+1}次): {last_err}")
    return {}


def signin(token, usertoken, dxrisk_token, cookie):
    """
    每日签到（带 3 次重试）
    返回状态: 'new'(首次签到成功) / 'already'(今日已签) / 'failed'(失败)
    """
    url = f"{BASE_URL}/lmarketing-task-api-mvc-prod/openapi/task/v1/signature/clock"
    headers = {
        'User-Agent': random.choice(USER_AGENTS),
        'Origin': 'https://longzhu.longfor.com',
        'Referer': 'https://longzhu.longfor.com/',
        'X-LF-DXRisk-Source': '5',
        'X-LF-Bu-Code': 'C20400',
        'X-GAIA-API-KEY': 'c06753f1-3e68-437d-b592-b94656ea5517',
        'X-LF-UserToken': usertoken,
        'X-LF-Channel': 'C2',
        'X-LF-DXRisk-Token': dxrisk_token,
        'X-LF-DXRisk-Captcha-Token': os.getenv('LHTJ_CAPTCHA_TOKEN', ''), # 过滑块后才有，可选
        'token': token,
        'Cookie': cookie,
        'Content-Type': 'application/json;charset=UTF-8'
    }
    activity_no = os.getenv('LHTJ_ACTIVITY_NO', '') or '11111111111686241863606037740000'
    data = {"activity_no": activity_no}
    res = http_request(url, headers, 'POST', data, retries=3)

    if not res:
        double_log("⛔️ 每日签到: 请求失败（网络/风控），已重试3次仍失败")
        return 'failed'

    code = res.get('code')
    data_obj = res.get('data', {})
    is_popup = data_obj.get('is_popup', 0)

    if code == '0000' and is_popup == 1:
        reward_num = data_obj.get('reward_info', [{}])[0].get('reward_num', 0)
        double_log(f"✅ 每日签到: 成功，获得{reward_num}分")
        return 'new'
    elif code == '0000' and is_popup == 0:
        double_log("ℹ️ 每日签到: 今日已签到")
        return 'already'
    else:
        if code == '801810':
            double_log(f"⛔️ 每日签到: 活动不可用 code=801810「{res.get('message', '')}」")
            double_log("⚠️ 可能: activity_no过期 或 风控触发")
            double_log("📋 处理: 手动进小程序签到确认 → 重新抓包更新 LHTJ_ACTIVITY_NO 和 LHTJ_DXRISK_TOKEN")
        else:
            double_log(f"⛔️ 每日签到: 失败 code={code} msg={res.get('message', '未知')}")
        return 'failed'


def get_user_info(token):
    """查询成长值"""
    url = "https://longzhu-api.longfor.com/lmember-member-open-api-prod/api/member/v1/mine-info"
    headers = {
        'User-Agent': random.choice(USER_AGENTS),
        'Referer': 'https://servicewechat.com/wx50282644351869da/424/page-frame.html',
        'token': token,
        'X-Gaia-Api-Key': 'd1eb973c-64ec-4dbe-b23b-22c8117c4e8e'
    }
    data = {"channel": "C2", "bu_code": "C20400", "token": token}
    res = http_request(url, headers, 'POST', data)
    if res.get('code') == '0000':
        growth = res['data'].get('growth_value', 0)
        level = res['data'].get('level', 0)
        double_log(f"🎉 成长值: {growth}  等级: V{level}")
        return res['data']
    double_log(f"⛔️ 查询成长值失败: {res.get('message', '未知')}")
    return {}


def get_balance(token):
    """查询珑珠余额"""
    url = "https://longzhu-api.longfor.com/lmember-member-open-api-prod/api/member/v1/balance"
    headers = {
        'User-Agent': random.choice(USER_AGENTS),
        'Referer': 'https://servicewechat.com/wx50282644351869da/424/page-frame.html',
        'token': token,
        'X-Gaia-Api-Key': 'd1eb973c-64ec-4dbe-b23b-22c8117c4e8e'
    }
    data = {"channel": "C2", "bu_code": "C20400", "token": token}
    res = http_request(url, headers, 'POST', data)
    if res.get('code') == '0000':
        balance = res['data'].get('balance', 0)
        expiring = res['data'].get('expiring_lz', 0)
        double_log(f"💰 珑珠: {balance}" + (f"（⚠️即将过期{expiring}）" if expiring else ""))
        return res['data']
    double_log(f"⛔️ 查询珑珠失败: {res.get('message', '未知')}")
    return {}


def push_wecom(content):
    """企业微信推送"""
    webhook = os.getenv('WECOM_WEBHOOK', '')
    if not webhook:
        logger.info("未配置企业微信Webhook，跳过推送")
        return
    try:
        resp = requests.post(webhook, json={
            'msgtype': 'markdown',
            'markdown': {'content': content}
        }, timeout=10)
        result = resp.json()
        if result.get('errcode') == 0:
            logger.info("✅ 企业微信推送成功")
        else:
            logger.error(f"⛔️ 推送失败: {result.get('errmsg')}")
    except Exception as e:
        logger.error(f"⛔️ 推送异常: {e}")


def main():
    token = os.getenv('LHTJ_TOKEN', '')
    usertoken = os.getenv('LHTJ_USERTOKEN', '')
    dxrisk_token = os.getenv('LHTJ_DXRISK_TOKEN', '')
    cookie = os.getenv('LHTJ_COOKIE', '')

    if not token or not cookie:
        logger.error("❌ 缺少必要的环境变量！请检查 GitHub Secrets 配置")
        sys.exit(1)

    logger.info("🚀 龙湖天街签到开始")
    double_log(f"⏰ 执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    token_expired = False
    signin_status = 'failed'

    try:
        # 签到前查一次成长值（基准）
        before = get_user_info(token)
        growth_before = before.get('growth_value', 0)

        # 签到
        signin_status = signin(token, usertoken, dxrisk_token, cookie)

        # 今日已签到 → 静默退出，不推送（避免多时段 cron 重复打扰）
        if signin_status == 'already':
            logger.info("今日已签到，静默退出，不推送")
            sys.exit(0)

        # 首次签到成功 → 签到后查成长值，验证积分到账
        if signin_status == 'new':
            time.sleep(2)
            after = get_user_info(token)
            growth_after = after.get('growth_value', 0)
            if growth_before and growth_after:
                diff = growth_after - growth_before
                if diff > 0:
                    double_log(f"📈 签到验证: 成长值 {growth_before} → {growth_after}（+{diff}）✅积分已到账")
                else:
                    double_log(f"⚠️ 签到验证: 成长值未变化({growth_before}→{growth_after})，积分可能延迟到账")

        # 珑珠余额
        get_balance(token)

    except TokenExpiredError as e:
        double_log(f"🚨 {e}")
        token_expired = True
        signin_status = 'failed'
    except Exception as e:
        double_log(f"🚨 签到流程异常: {e}")
        signin_status = 'failed'

    # 推送
    today = datetime.now().strftime('%Y-%m-%d')
    if signin_status == 'new':
        status_emoji = "✅"
        title = f"{status_emoji} 龙湖天街签到成功"
    else:
        status_emoji = "🚨"
        title = f"{status_emoji} 龙湖天街签到失败"

    content = f"## {title}\n---\n📅 {today}\n\n" + "\n".join(notify_msg)
    if token_expired:
        content += "\n\n⚠️ **Token已过期，请尽快更新 GitHub Secrets！**"
    push_wecom(content)

    logger.info("签到任务结束")
    # 签到失败时退出码 1，让 Actions 显示红色 + 触发告警 Issue
    if signin_status == 'failed':
        logger.error("签到未成功，退出码 1")
        sys.exit(1)


if __name__ == "__main__":
    main()
