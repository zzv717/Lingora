#!/usr/bin/env bash
set -e

# Ushbu skript Lingora loyihasini GitHub repository-ga push qilish uchun mo'ljallangan.
# Ishlatish tartibi:
# GITHUB_TOKEN="ghp_xxx" ./scripts/push_to_github.sh
# yoki
# ./scripts/push_to_github.sh "ghp_xxx"

TOKEN="${1:-$GITHUB_TOKEN}"

if [ -z "$TOKEN" ]; then
  echo "XATOLIK: GitHub Personal Access Token (PAT) kiritilmadi."
  echo "Quyidagicha ishga tushiring:"
  echo "  ./scripts/push_to_github.sh <SIZNING_GITHUB_TOKENINGIZ>"
  echo "yoki:"
  echo "  GITHUB_TOKEN=<TOKEN> ./scripts/push_to_github.sh"
  exit 1
fi

REPO_URL="https://${TOKEN}@github.com/zzv717/Lingora.git"

echo "GitHub repository'ga push qilinmoqda (branch: main)..."
git push "$REPO_URL" main:main

echo "MUVAFFAQIN! O'zgarishlar GitHub'ga muvaffaqiyatli yuborildi."
