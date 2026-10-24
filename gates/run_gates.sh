#!/usr/bin/env bash
# 文风门禁总调度：按语言路由，逐闸执行，给总体裁决。
#   run_gates.sh <文件> [--essay] [--intimacy|--erotica] [--zhuque] [--quiet]
#
# 闸门（中文）：density_check → check_prose → story-deslop(blocking)
#               → prose_dense（本仓库）→ [亲密词表命中时自动叠加 intimacy 层] → [朱雀]
# 闸门（英文）：check_slop_en.py
# 缺失的第三方闸门自动跳过并标 n/a，不影响本仓库自带的两道闸。
# 退出码：0 全绿 / 1 有 blocking / 2 用法错误
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
PY="${PY:-python3}"

# 第三方 skill 根目录：默认探常见位置，可用 SKILLS_DIR 覆盖
SKILLS_DIR="${SKILLS_DIR:-}"
if [ -z "$SKILLS_DIR" ]; then
  for d in "$HOME/.agents/skills" "$HOME/.dsh/skills" "$HOME/.claude/skills" "$HOME/.config/agents/skills"; do
    [ -d "$d" ] && { SKILLS_DIR="$d"; break; }
  done
fi
EN="$HERE/check_slop_en.py"
# 本仓库自带脚本：优先同仓 scripts/，否则退回已安装的 skill
pick() {
  local n="$1"
  for c in "$ROOT/scripts/$n" "$SKILLS_DIR/prose-deai/scripts/$n" \
           "$HOME/.agents/skills/prose-deai/scripts/$n"; do
    [ -f "$c" ] && { printf '%s' "$c"; return; }
  done
  printf '%s' "$ROOT/scripts/$n"
}
DP="$(pick check_prose_dense.py)"
IN="$(pick check_intimacy.py)"

HN="${HN:-$SKILLS_DIR/human-novel-writer/scripts}"
SD="${SD:-$SKILLS_DIR/story-deslop/scripts}"
ST="$(pick check_syntax_tpl.py)"
SC="$(pick check_style_consistency.py)"
ES="$(pick check_essay_slop.py)"
FILE=""; FORCE=0; ZHUQUE=0; QUIET=0; GENRE=fiction
for a in "$@"; do
  case "$a" in
    --intimacy|--erotica) FORCE=1 ;;
    --zhuque) ZHUQUE=1 ;;
    --quiet)  QUIET=1 ;;
    --essay)  GENRE=essay ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) FILE="$a" ;;
  esac
done
[ -z "$FILE" ] && { echo "usage: $0 <file> [--essay] [--intimacy] [--zhuque] [--quiet]" >&2; exit 2; }
[ -f "$FILE" ] || { echo "no such file: $FILE" >&2; exit 2; }

read -r HAN TOTAL < <("$PY" - "$FILE" <<'PYX'
import sys, re
t = open(sys.argv[1], encoding='utf-8', errors='ignore').read()
han = len(re.findall(r'[\u4e00-\u9fff]', t))
total = max(len(re.sub(r'\s', '', t)), 1)
print(han, total)
PYX
)
LANG_CODE=zh
[ "$HAN" -eq 0 ] && LANG_CODE=en
[ "$HAN" -gt 0 ] && [ $(( HAN * 100 / TOTAL )) -lt 8 ] && LANG_CODE=en

RED=$'\033[31m'; GRN=$'\033[32m'; RST=$'\033[0m'
[ ! -t 1 ] && RED=""; GRN=""; RST=""

echo "=== gates :: $FILE (lang=$LANG_CODE, ${HAN} 汉字 / ${TOTAL} 字符) ==="
FAILED=0; ROWS=()
row() { ROWS+=("$(printf '%-18s %-6s %s' "$1" "$2" "$3")"); }

run_zh() {
  local out rc concl xfail sum b a nq r18 n
  if [ "$GENRE" = "essay" ]; then
    if [ -f "$HN/density_check.py" ]; then
      out=$("$PY" "$HN/density_check.py" "$FILE" 2>&1)
      hits=$(printf '%s\n' "$out" | grep -E '禁词: .*FAIL|零频套语\(硬\): [1-9]|三连排比: [1-9]|破折号: [1-9]' | grep -v '✓')
      if [ -n "$hits" ]; then
        FAILED=1
        row density_check FAIL "作文模式：$(printf '%s' "$hits" | tr '\n' ' ' | cut -c1-64)"
        [ $QUIET -eq 0 ] && printf '%s\n' "$hits" | sed "s/^/  ${RED}/;s/$/${RST}/"
      else row density_check ok "作文模式：禁词/套语/排比 0"; fi
    else row density_check n/a "未安装 human-novel-writer"; fi
    row check_prose n/a "--essay：网文翻案腔闸不适用"
    row story-deslop n/a "--essay：网文结构闸不适用"
  else
  # 1. 网文硬红线（第三方，可选）
  if [ -f "$HN/density_check.py" ]; then
    out=$("$PY" "$HN/density_check.py" "$FILE" 2>&1); rc=$?
    concl=$(printf '%s\n' "$out" | grep -E '^(结论|全部通过)' | tail -1)
    [ -z "$concl" ] && concl=$(printf '%s\n' "$out" | tail -1)
    xfail=$(printf '%s\n' "$out" | grep -c '✗')
    if [ $rc -ne 0 ] && [ "$xfail" -eq 0 ]; then rc=0; concl="仅建议项（✗ 0 处）"; fi
    if [ $rc -ne 0 ]; then FAILED=1; row density_check FAIL "$concl"; else row density_check ok "$concl"; fi
  else row density_check n/a "未安装 human-novel-writer"; fi

  # 2. 翻案腔/黑话（第三方，可选）
  if [ -f "$HN/check_prose.py" ]; then
    out=$("$PY" "$HN/check_prose.py" "$FILE" 2>&1); rc=$?
    sum=$(printf '%s\n' "$out" | head -2 | tr '\n' ' ')
    if [ $rc -ne 0 ]; then FAILED=1; row check_prose FAIL "$sum"; else row check_prose ok "$sum"; fi
  else row check_prose n/a "未安装 human-novel-writer"; fi

  # 3. 结构闸（第三方，可选，只认 blocking）
  if [ -f "$SD/check-ai-patterns.js" ] && command -v node >/dev/null 2>&1; then
    out=$(node "$SD/check-ai-patterns.js" --fail-on=blocking "$FILE" 2>&1); rc=$?
    b=$(printf '%s\n' "$out" | grep -c '\[blocking\]'); a=$(printf '%s\n' "$out" | grep -c '\[advisory\]')
    if [ "$b" -gt 0 ]; then FAILED=1; row story-deslop FAIL "blocking=$b advisory=$a"
      [ $QUIET -eq 0 ] && printf '%s\n' "$out" | grep '\[blocking\]' | head -12 | sed "s/^/  ${RED}/;s/$/${RST}/"
    else row story-deslop ok "blocking=0 advisory=$a"; fi
  else row story-deslop n/a "未安装 story-deslop 或无 node"; fi
  fi

  # 4. 本仓库风格层（自带）
  out=$("$PY" "$DP" "$FILE" 2>&1); rc=$?
  r18=$(printf '%s\n' "$out" | grep -oE 'R18: (yes|no)' | head -1 | awk '{print $2}'); [ -z "$r18" ] && r18=no
  nq=$(printf '%s\n' "$out" | grep -c '^   \[强禁\]')
  if [ $rc -ne 0 ]; then FAILED=1; row prose_dense FAIL "句末单字 $nq 处"
    [ $QUIET -eq 0 ] && printf '%s\n' "$out" | grep -E '\[强禁\]|配额提示|密度提示' | head -8 | sed "s/^/  ${RED}/;s/$/${RST}/"
  else row prose_dense ok "R18=$r18 提示 $(printf '%s\n' "$out" | grep -c '配额提示\|密度提示') 项"; fi

  # 4.4 作文套话层（自带，advisory：强套密度判，人类用弱套不算）
  if [ -f "$ES" ]; then
    out=$("$PY" "$ES" "$FILE" --json 2>/dev/null)
    if [ -n "$out" ]; then
      summary=$(printf '%s' "$out" | "$PY" -c 'import json,sys
f=json.load(sys.stdin)["files"][0]
print(f.get("level","?"), f.get("strong",0), f.get("strong_per_k",0), f.get("weak",0))' 2>/dev/null)
      set -- $summary
      case "$1" in
        bad)  row essay_slop FAIL "强套 $2 处（$3/千字）弱套 $4 处【作文套话过多】（advisory）" ;;
        mild) row essay_slop warn "强套 $2 处（$3/千字）弱套 $4 处【提示】（advisory）" ;;
        *)    row essay_slop ok "强套 $2 处（$3/千字）弱套 $4 处【干净】（advisory）" ;;
      esac
    fi
  fi

  # 4.5 句式模板层（自带，advisory：复读句只提示不阻断）
  if [ -f "$ST" ]; then
    out=$("$PY" "$ST" "$FILE" --quiet --json 2>/dev/null)
    if [ -n "$out" ]; then
      summary=$(printf '%s' "$out" | "$PY" -c 'import json,sys
d=json.load(sys.stdin); f=d["files"][0] if d["files"] else {}
print(f.get("strong",0), f.get("sentences",0), f.get("mean_conc",0), f.get("percentile","?"), f.get("level","?"), f.get("cdr"))' 2>/dev/null)
      set -- $summary
      lv=$5; tag="【正常】"
      [ "$lv" = "high" ] && tag="【偏高】"
      [ "$lv" = "template" ] && tag="【句式模板化】"
      [ "$lv" = "short" ] && tag="【样本短·看句级】"
      row syntax_tpl ok "浓度均值 $3 人类分位~P$4$tag 复读句 $1/$2 CDR=$6（advisory）"
      if [ $QUIET -eq 0 ] && [ "${1:-0}" -gt 0 ]; then
        printf '%s' "$out" | "$PY" -c 'import json,sys
d=json.load(sys.stdin); f=d["files"][0] if d["files"] else {}
for n in f.get("notes",[])[:6]:
    print("  句%3d 浓度%.2f %s" % (n["idx"], n["conc"], n["sent"]))' 2>/dev/null | sed "s/^/  /"
      fi
    else row syntax_tpl n/a "jieba 缺失"; fi
  fi

  # 4.6 文风一致性层（自带，advisory：本章 vs 同目录其他章节）
  if [ -f "$SC" ]; then
    out=$("$PY" "$SC" "$FILE" --ref "$(dirname "$FILE")" --json 2>/dev/null)
    case "$out" in \{*) ;; *) row style_cons n/a "基线不足（同目录需其他文件）"; out="";; esac
    if [ -n "$out" ]; then
      summary=$(printf '%s' "$out" | "$PY" -c 'import json,sys
d=json.load(sys.stdin); dr=d.get("drifted",[])
print(d.get("verdict","?")); print(len(dr)); print("、".join(dr[:3]) if dr else "无")' 2>/dev/null)
      scv=$(printf '%s\n' "$summary" | sed -n 1p)
      scn=$(printf '%s\n' "$summary" | sed -n 2p)
      scl=$(printf '%s\n' "$summary" | sed -n 3p)
      case "$scv" in
        一致) row style_cons ok "一致" ;;
        轻微漂移) row style_cons warn "轻微漂移 $scn 项：$scl" ;;
        *) row style_cons FAIL "明显漂移：$scl" ;;
      esac
    fi
  fi

  # 5. 可选：亲密场景用词层（R18 命中自动叠加，--intimacy 强制）
  if { [ $FORCE -eq 1 ] || [ "$r18" = yes ]; } && [ -f "$IN" ]; then
    out=$("$PY" "$IN" "$FILE" 2>&1); rc=$?
    n=$(printf '%s\n' "$out" | grep -cE '^\s*(HARD|HARD_RE|CTX)')
    if [ $rc -ne 0 ]; then FAILED=1; row intimacy FAIL "命中=$n"; else row intimacy ok "命中=$n"; fi
  fi

  # 6. 平台 AIGC 检测（第三方，可选）
  if [ $ZHUQUE -eq 1 ] && [ -f "$HN/zhuque_check.py" ]; then
    out=$("$PY" "$HN/zhuque_check.py" "$FILE" 2>&1); rc=$?
    local last; last=$(printf '%s\n' "$out" | grep -E 'AIGC|FAIL|PASS' | tail -1)
    if [ $rc -ne 0 ]; then FAILED=1; row zhuque FAIL "$last"; else row zhuque ok "$last"; fi
  fi
}

run_en() {
  local out rc sum
  if [ ! -f "$EN" ]; then row stop-slop n/a "check_slop_en.py 缺失"; return; fi
  out=$("$PY" "$EN" "$FILE" 2>&1); rc=$?
  sum=$(printf '%s\n' "$out" | sed -n '2p')
  if [ $rc -ne 0 ]; then FAILED=1; row stop-slop FAIL "$sum"; else row stop-slop ok "$sum"; fi
  [ $QUIET -eq 0 ] && printf '%s\n' "$out" | grep -E '\[blocking\]' | head -12 | sed "s/^/  ${RED}/;s/$/${RST}/"
}

if [ "$LANG_CODE" = zh ]; then run_zh; else run_en; fi

echo "---"
printf '%s\n' "${ROWS[@]}"
echo "---"
if [ $FAILED -eq 1 ]; then echo "${RED}VERDICT: FAIL 按命中条目改写后重跑，不许留到下一轮${RST}"; exit 1; fi
echo "${GRN}VERDICT: PASS 全闸通过（advisory 不等于问题，人工裁决）${RST}"
exit 0
