#!/usr/bin/env bash
# ============================================================
# 龙湖天街 Token 自助刷新脚本
# ============================================================
# 用途：captcha-token 每 ~3 天过期。过期后企业微信会收到失败通知，
#       此时在微信小程序抓包拿到新的 3 个值，运行本脚本一条命令刷新。
#
# 用法：
#   ./refresh.sh "<captcha-token>" "<dxrisk-token>" "<cookie>"
#
# 示例：
#   ./refresh.sh "19F6E608...:6a59b246..." "6a59b246RiVk..." "acw_tc=276077..."
#
# 前置：本机已安装 gh CLI 并登录 (gh auth login)，仓库 M11Night/lhtj-checkin
# 刷新后自动触发一次签到验证。
# ============================================================
set -euo pipefail

REPO="M11Night/lhtj-checkin"
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

if [ $# -lt 3 ]; then
  echo -e "${RED}❌ 参数不足${NC}"
  echo "用法: $0 \"<captcha-token>\" \"<dxrisk-token>\" \"<cookie>\""
  echo ""
  echo "抓包获取方式（Stream / Charles / Fiddler 均可）："
  echo "  1. 微信小程序「龙湖天街」→ 签到页 → 触发签到"
  echo "  2. 找请求头里的 3 个值："
  echo "     X-LF-DXRisk-Captcha-Token: <值1>   → 第1个参数"
  echo "     X-LF-DXRisk-Token:         <值2>   → 第2个参数"
  echo "     Cookie:                    <值3>   → 第3个参数"
  exit 1
fi

CAPTCHA_TOKEN="$1"
DXRISK_TOKEN="$2"
COOKIE="$3"

# 校验非空
[ -z "$CAPTCHA_TOKEN" ] && { echo -e "${RED}❌ captcha-token 为空${NC}"; exit 1; }
[ -z "$DXRISK_TOKEN" ]  && { echo -e "${RED}❌ dxrisk-token 为空${NC}"; exit 1; }
[ -z "$COOKIE" ]        && { echo -e "${RED}❌ cookie 为空${NC}"; exit 1; }

# 校验 gh 已登录
if ! gh auth status >/dev/null 2>&1; then
  echo -e "${RED}❌ gh CLI 未登录，请先运行: gh auth login${NC}"
  exit 1
fi

echo -e "${YELLOW}🔄 更新 3 个 Secret...${NC}"
printf '%s' "$CAPTCHA_TOKEN" | gh secret set LHTJ_CAPTCHA_TOKEN -R "$REPO"
printf '%s' "$DXRISK_TOKEN"  | gh secret set LHTJ_DXRISK_TOKEN  -R "$REPO"
printf '%s' "$COOKIE"        | gh secret set LHTJ_COOKIE        -R "$REPO"
echo -e "${GREEN}✅ 3 个 Secret 已更新${NC}"

echo -e "${YELLOW}🚀 触发签到验证...${NC}"
gh workflow run checkin.yml -R "$REPO" -f reason="refresh.sh刷新后验证"
sleep 6
RUN_ID=$(gh run list -R "$REPO" --workflow=checkin.yml -L 1 --json databaseId -q '.[0].databaseId')
echo -e "${GREEN}✅ 已触发签到 (Run ID: $RUN_ID)${NC}"
echo "查看进度: gh run watch $RUN_ID -R $REPO"
echo "或打开: https://github.com/$REPO/actions"
