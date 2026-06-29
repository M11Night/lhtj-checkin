#!/usr/bin/env python3
"""
龙湖天街自动签到 — GitHub Actions 版
从环境变量读取 Token，签到后推送企业微信通知
"""

import os
import sys
import json
import random
import asyncio
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


async def fetch(url, headers, method='POST', data=None, timeout=10):
    try:
        headers = {k.lower(): v for k, v in headers.items()}
        if method.upper() == 'POST':
            resp = requests.post(url, headers=headers, json=data, timeout=timeout)
        else:
            resp = requests.get(url, headers=headers, params=data, timeout=timeout)
        resp.raise_for_status()
        res = resp.json()
        if 'message' in res and ('登录已过期' in res['message'] or '用户未登录' in res['message']):
            raise Exception("Token已过期，请更新Secrets")
        return res
    except Exception as e:
        logger.error(f"请求失败: {e}")
        return {}


async def signin(token, usertoken, dxrisk_token, cookie):
    """每日签到"""
    try:
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
            'token': token,
            'Cookie': cookie,
            'Content-Type': 'application/json;charset=UTF-8'
        }
        data = {"activity_no": "11111111111686241863606037740000"}
        res = await fetch(url, headers, 'POST', data)
        is_popup = res.get('data', {}).get('is_popup', 0)
        reward_num = res.get('data', {}).get('reward_info', [{}])[0].get('reward_num', 0) if is_popup == 1 else 0
        if is_popup == 1:
            double_log(f"✅ 每日签到: 成功, 获得{reward_num}分")
        else:
            double_log("⛔️ 每日签到: 今日已签到")
        return reward_num
    except Exception as e:
        double_log(f"⛔️ 每日签到失败: {e}")
        return 0


async def get_user_info(token):
    """查询成长值"""
    try:
        url = "https://longzhu-api.longfor.com/lmember-member-open-api-prod/api/member/v1/mine-info"
        headers = {
            'User-Agent': random.choice(USER_AGENTS),
            'Referer': 'https://servicewechat.com/wx50282644351869da/424/page-frame.html',
            'token': token,
            'X-Gaia-Api-Key': 'd1eb973c-64ec-4dbe-b23b-22c8117c4e8e'
        }
        data = {"channel": "C2", "bu_code": "C20400", "token": token}
        res = await fetch(url, headers, 'POST', data)
        if res.get('code') == '0000':
            growth = res['data'].get('growth_value', 0)
            level = res['data'].get('level', 0)
            double_log(f"🎉 成长值: {growth}  等级: V{level}")
            return res['data']
        return {}
    except Exception as e:
        double_log(f"⛔️ 查询成长值失败: {e}")
        return {}


async def get_balance(token):
    """查询珑珠余额"""
    try:
        url = "https://longzhu-api.longfor.com/lmember-member-open-api-prod/api/member/v1/balance"
        headers = {
            'User-Agent': random.choice(USER_AGENTS),
            'Referer': 'https://servicewechat.com/wx50282644351869da/424/page-frame.html',
            'token': token,
            'X-Gaia-Api-Key': 'd1eb973c-64ec-4dbe-b23b-22c8117c4e8e'
        }
        data = {"channel": "C2", "bu_code": "C20400", "token": token}
        res = await fetch(url, headers, 'POST', data)
        if res.get('code') == '0000':
            balance = res['data'].get('balance', 0)
            double_log(f"💰 珑珠: {balance}")
            return res['data']
        return {}
    except Exception as e:
        double_log(f"⛔️ 查询珑珠失败: {e}")
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


async def main():
    # 从环境变量读取配置
    token = os.getenv('LHTJ_TOKEN', '')
    usertoken = os.getenv('LHTJ_USERTOKEN', '')
    dxrisk_token = os.getenv('LHTJ_DXRISK_TOKEN', '')
    cookie = os.getenv('LHTJ_COOKIE', '')

    if not token or not cookie:
        logger.error("❌ 缺少必要的环境变量！请检查 GitHub Secrets 配置")
        sys.exit(1)

    logger.info("🚀 龙湖天街签到开始")

    # 签到
    await signin(token, usertoken, dxrisk_token, cookie)

    # 查询
    await get_user_info(token)
    await get_balance(token)

    # 推送
    today = datetime.now().strftime('%Y-%m-%d')
    content = f"## 龙湖天街签到报告\n---\n📅 {today}\n\n" + "\n".join(notify_msg)
    push_wecom(content)

    logger.info("✅ 签到任务完成")


if __name__ == "__main__":
    asyncio.run(main())
